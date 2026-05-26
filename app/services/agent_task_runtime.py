"""Concurrent task-group execution for delegated child agents."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from dataclasses import dataclass, field
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.agent_task_protocols import AgentTaskStore
from app.domain.agent_tasks import AgentTaskRecord, AgentTaskSpec
from app.domain.models import RunContext
from app.runtime.agent_events import (
    AGENT_RESULT_SUMMARY_EVENT,
    AGENT_TASK_COMPLETED_EVENT,
    AGENT_TASK_FAILED_EVENT,
    AGENT_TASK_GROUP_COMPLETED_EVENT,
    AGENT_TASK_GROUP_CREATED_EVENT,
    AGENT_TASK_STARTED_EVENT,
    AgentResultSummaryPayload,
)
from app.runtime.event_recorder import EventRecorder
from app.services.agent_invocation_service import AgentInvocationRequest, AgentInvocationService
from app.services.task_context_builder import TaskContextBuilder

__all__ = [
    "AgentTaskGroupRequest",
    "AgentTaskGroupResult",
    "AgentTaskRecord",
    "AgentTaskResult",
    "AgentTaskRuntime",
    "AgentTaskSpec",
]

_DEFAULT_MAX_CONCURRENCY = 3
_MAX_TASKS_PER_GROUP = 8
_TOOL_CALL_LIMIT_MESSAGE = "Tool call limit reached"
_UNRELIABLE_FALLBACK_MARKERS = (
    "没有生成可用的最终答复",
    "已停止继续执行重复步骤",
)


@dataclass(slots=True)
class AgentTaskGroupRequest:
    """Input contract for one task group."""

    source_context: RunContext
    tasks: list[AgentTaskSpec]
    wait: bool = True
    max_concurrency: int = _DEFAULT_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        if not isinstance(self.source_context, RunContext):
            raise ValidationError("source_context must be RunContext.")
        if not isinstance(self.tasks, list) or not self.tasks:
            raise ValidationError("tasks must be a non-empty list.")
        if len(self.tasks) > _MAX_TASKS_PER_GROUP:
            raise ValidationError(f"tasks cannot exceed {_MAX_TASKS_PER_GROUP} items.")
        for task in self.tasks:
            if not isinstance(task, AgentTaskSpec):
                raise ValidationError("tasks must contain AgentTaskSpec items.")
        if not isinstance(self.wait, bool):
            raise ValidationError("wait must be bool.")
        if self.max_concurrency <= 0:
            raise ValidationError("max_concurrency must be positive.")
        self.max_concurrency = min(self.max_concurrency, len(self.tasks), _MAX_TASKS_PER_GROUP)


@dataclass(slots=True)
class AgentTaskResult:
    """Completed task result returned to main-agent tooling."""

    task_id: str
    target_agent_id: str
    status: str
    summary: str
    answer: str
    child_run_id: str | None = None
    artifact_refs: list[str] = field(default_factory=list)
    output_artifact_refs: list[str] = field(default_factory=list)
    product_refs: list[str] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        self.task_id = _require_non_empty("task_id", self.task_id)
        self.target_agent_id = _require_non_empty("target_agent_id", self.target_agent_id)
        self.status = _require_non_empty("status", self.status)
        self.summary = _require_non_empty("summary", self.summary)
        self.answer = _require_non_empty("answer", self.answer)
        self.child_run_id = _normalize_optional_string("child_run_id", self.child_run_id)
        self.artifact_refs = _normalize_string_list("artifact_refs", self.artifact_refs)
        self.output_artifact_refs = _normalize_string_list("output_artifact_refs", self.output_artifact_refs)
        self.product_refs = _normalize_string_list("product_refs", self.product_refs)
        self.error = _normalize_optional_string("error", self.error)

    def to_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "target_agent_id": self.target_agent_id,
            "status": self.status,
            "summary": self.summary,
            "answer": self.answer,
            "child_run_id": self.child_run_id,
            "artifact_refs": self.artifact_refs,
            "output_artifact_refs": self.output_artifact_refs,
            "product_refs": self.product_refs,
            "error": self.error,
        }


@dataclass(slots=True)
class AgentTaskGroupResult:
    """Aggregated result for one delegated task group."""

    task_group_id: str
    status: str
    results: list[AgentTaskResult]
    max_concurrency: int

    def __post_init__(self) -> None:
        self.task_group_id = _require_non_empty("task_group_id", self.task_group_id)
        self.status = _require_non_empty("status", self.status)
        if not isinstance(self.results, list):
            raise ValidationError("results must be a list.")
        if self.max_concurrency <= 0:
            raise ValidationError("max_concurrency must be positive.")

    def to_payload(self) -> dict[str, object]:
        return {
            "task_group_id": self.task_group_id,
            "status": self.status,
            "max_concurrency": self.max_concurrency,
            "results": [result.to_payload() for result in self.results],
        }


class AgentTaskRuntime:
    """Run independent child-agent tasks concurrently and aggregate results."""

    def __init__(
        self,
        *,
        invocation_service: AgentInvocationService,
        task_store: AgentTaskStore,
        event_recorder: EventRecorder | None = None,
        task_context_builder: TaskContextBuilder | None = None,
        default_max_concurrency: int = _DEFAULT_MAX_CONCURRENCY,
    ) -> None:
        if default_max_concurrency <= 0:
            raise ValidationError("default_max_concurrency must be positive.")
        self._invocation_service = invocation_service
        self._task_store = task_store
        self._event_recorder = event_recorder
        self._task_context_builder = task_context_builder
        self._default_max_concurrency = default_max_concurrency

    def run_group(self, request: AgentTaskGroupRequest) -> AgentTaskGroupResult:
        return _run_coroutine_sync(self.run_group_async(request))

    async def run_group_async(self, request: AgentTaskGroupRequest) -> AgentTaskGroupResult:
        if not isinstance(request, AgentTaskGroupRequest):
            raise ValidationError("request must be AgentTaskGroupRequest.")
        if not request.wait:
            raise ValidationError("wait=false is not supported yet.")
        unsupported_dependencies = [task for task in request.tasks if task.depends_on]
        if unsupported_dependencies:
            raise ValidationError("depends_on is reserved for later; v1 only supports independent tasks.")

        max_concurrency = request.max_concurrency or self._default_max_concurrency
        group = self._task_store.create_group(
            session_id=request.source_context.session_id,
            source_agent_id=request.source_context.agent_id,
            source_run_id=request.source_context.run_id,
            max_concurrency=max_concurrency,
            specs=request.tasks,
        )
        task_records = self._task_store.list_group_tasks(request.source_context.session_id, group.task_group_id)
        self._record_progress_event(
            request.source_context,
            AGENT_TASK_GROUP_CREATED_EVENT,
            {
                "task_group_id": group.task_group_id,
                "status": group.status,
                "max_concurrency": max_concurrency,
                "title": "委派子任务",
                "detail": f"已委派 {len(task_records)} 个 agent 任务",
                "tasks": [_task_progress_payload(task) for task in task_records],
            },
        )
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run_one(spec: AgentTaskSpec, record: AgentTaskRecord) -> AgentTaskResult:
            async with semaphore:
                child_run_id = f"run_{uuid4().hex[:12]}"
                running = self._task_store.mark_running(
                    request.source_context.session_id,
                    record.task_id,
                    child_run_id=child_run_id,
                )
                self._record_progress_event(
                    request.source_context,
                    AGENT_TASK_STARTED_EVENT,
                    {
                        **_task_progress_payload(running),
                        "detail": _running_detail(running),
                    },
                )
                task_context = self._build_task_context(
                    request=request,
                    spec=spec,
                    task_id=record.task_id,
                )
                try:
                    result = await asyncio.to_thread(
                        self._invocation_service.invoke,
                        AgentInvocationRequest(
                            source_context=request.source_context,
                            target_agent_id=spec.target_agent_id,
                            instruction=spec.instruction,
                            constraints=spec.constraints,
                            artifact_refs=spec.artifact_refs,
                            skill_names=spec.skill_names,
                            max_tool_rounds=spec.max_tool_rounds,
                            task_id=record.task_id,
                            child_run_id=child_run_id,
                            task_context=task_context,
                            record_result_summary=self._event_recorder is None,
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    error = _safe_error_message(exc)
                    failed = self._task_store.mark_failed(request.source_context.session_id, record.task_id, error=error)
                    self._record_progress_event(
                        request.source_context,
                        AGENT_TASK_FAILED_EVENT,
                        {
                            **_task_progress_payload(failed),
                            "detail": _shorten(error, 160),
                        },
                    )
                    self._record_result_summary_event(
                        request.source_context,
                        task_id=record.task_id,
                        target_agent_id=spec.target_agent_id,
                        status="failed",
                        summary=error,
                        child_run_id=child_run_id,
                        artifact_refs=spec.artifact_refs,
                        output_artifact_refs=[],
                        product_refs=[],
                    )
                    return AgentTaskResult(
                        task_id=record.task_id,
                        target_agent_id=spec.target_agent_id,
                        status="failed",
                        summary=error,
                        answer=error,
                        child_run_id=child_run_id,
                        artifact_refs=spec.artifact_refs,
                        output_artifact_refs=[],
                        product_refs=[],
                        error=error,
                    )
                completion_error = _child_completion_error(spec=spec, result=result)
                if completion_error is not None:
                    failed = self._task_store.mark_failed(
                        request.source_context.session_id,
                        record.task_id,
                        error=completion_error,
                    )
                    self._record_progress_event(
                        request.source_context,
                        AGENT_TASK_FAILED_EVENT,
                        {
                            **_task_progress_payload(failed),
                            "detail": _shorten(completion_error, 160),
                            "artifact_refs": list(spec.artifact_refs),
                            "output_artifact_refs": [],
                            "product_refs": [],
                        },
                    )
                    self._record_result_summary_event(
                        request.source_context,
                        task_id=record.task_id,
                        target_agent_id=spec.target_agent_id,
                        status="failed",
                        summary=completion_error,
                        child_run_id=result.child_run_id,
                        artifact_refs=spec.artifact_refs,
                        output_artifact_refs=[],
                        product_refs=[],
                    )
                    return AgentTaskResult(
                        task_id=record.task_id,
                        target_agent_id=spec.target_agent_id,
                        status="failed",
                        summary=completion_error,
                        answer=completion_error,
                        child_run_id=result.child_run_id,
                        artifact_refs=list(spec.artifact_refs),
                        output_artifact_refs=[],
                        product_refs=[],
                        error=completion_error,
                    )
                completed = self._task_store.mark_completed(
                    request.source_context.session_id,
                    record.task_id,
                    summary=result.summary,
                    answer=result.answer,
                    artifact_refs=result.artifact_refs,
                )
                self._record_progress_event(
                    request.source_context,
                    AGENT_TASK_COMPLETED_EVENT,
                    {
                        **_task_progress_payload(completed),
                        "detail": _shorten(result.summary, 160),
                        "artifact_refs": result.artifact_refs,
                        "output_artifact_refs": result.output_artifact_refs,
                        "product_refs": result.product_refs,
                    },
                )
                self._record_result_summary_event(
                    request.source_context,
                    task_id=record.task_id,
                    target_agent_id=spec.target_agent_id,
                    status="completed",
                    summary=result.summary,
                    child_run_id=result.child_run_id,
                    artifact_refs=result.artifact_refs,
                    output_artifact_refs=result.output_artifact_refs,
                    product_refs=result.product_refs,
                )
                return AgentTaskResult(
                    task_id=record.task_id,
                    target_agent_id=spec.target_agent_id,
                    status="completed",
                    summary=result.summary,
                    answer=result.answer,
                    child_run_id=result.child_run_id,
                    artifact_refs=result.artifact_refs,
                    output_artifact_refs=result.output_artifact_refs,
                    product_refs=result.product_refs,
                )

        results = await asyncio.gather(
            *[_run_one(spec, record) for spec, record in zip(request.tasks, task_records, strict=True)]
        )
        final_group = self._task_store.get_group(request.source_context.session_id, group.task_group_id)
        group_status = final_group.status if final_group is not None else _derive_result_group_status(results)
        self._record_progress_event(
            request.source_context,
            AGENT_TASK_GROUP_COMPLETED_EVENT,
            {
                "task_group_id": group.task_group_id,
                "status": group_status,
                "max_concurrency": max_concurrency,
                "title": "子任务已结束",
                "detail": _group_completion_detail(group_status, results),
                "tasks": [result.to_payload() for result in results],
            },
        )
        return AgentTaskGroupResult(
            task_group_id=group.task_group_id,
            status=group_status,
            results=results,
            max_concurrency=max_concurrency,
        )

    def _record_progress_event(self, context: RunContext, event_type: str, payload: dict[str, object]) -> None:
        if self._event_recorder is None:
            return
        self._event_recorder.record(context=context, event_type=event_type, payload=payload)

    def _record_result_summary_event(
        self,
        context: RunContext,
        *,
        task_id: str,
        target_agent_id: str,
        status: str,
        summary: str,
        child_run_id: str | None,
        artifact_refs: list[str],
        output_artifact_refs: list[str],
        product_refs: list[str],
    ) -> None:
        if self._event_recorder is None or child_run_id is None:
            return
        payload = AgentResultSummaryPayload(
            task_id=task_id,
            source_agent_id=target_agent_id,
            target_agent_id=context.agent_id,
            status=status,
            summary=summary,
            artifact_refs=artifact_refs,
            output_artifact_refs=output_artifact_refs,
            product_refs=product_refs,
            parent_run_id=context.run_id,
        )
        child_context = RunContext(
            session_id=context.session_id,
            run_id=child_run_id,
            agent_id=target_agent_id,
            turn_id=context.turn_id,
            entry_agent_id=context.entry_agent_id,
            parent_run_id=context.run_id,
            trace_flags=dict(context.trace_flags),
            task_id=task_id,
        )
        self._event_recorder.record(
            context=child_context,
            event_type=AGENT_RESULT_SUMMARY_EVENT,
            payload=payload.to_payload(),
        )

    def _build_task_context(
        self,
        *,
        request: AgentTaskGroupRequest,
        spec: AgentTaskSpec,
        task_id: str,
    ) -> dict[str, object]:
        if self._task_context_builder is None:
            return {}
        try:
            return self._task_context_builder.build(
                source_context=request.source_context,
                target_agent_id=spec.target_agent_id,
                task_id=task_id,
                instruction=spec.instruction,
                artifact_refs=spec.artifact_refs,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "schema_version": 1,
                "task_id": task_id,
                "target_agent_id": spec.target_agent_id,
                "context_build_error": _safe_error_message(exc),
            }


def _run_coroutine_sync(coro: Coroutine[object, object, AgentTaskGroupResult]) -> AgentTaskGroupResult:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: AgentTaskGroupResult | None = None
    error: BaseException | None = None

    def _runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            error = exc

    thread = threading.Thread(target=_runner, name="agent-task-runtime-sync-wrapper", daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    if result is None:
        raise ValidationError("agent task runtime returned no result.")
    return result


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _derive_result_group_status(results: list[AgentTaskResult]) -> str:
    if all(result.status == "completed" for result in results):
        return "completed"
    if all(result.status == "failed" for result in results):
        return "failed"
    return "partial_failed"


def _task_progress_payload(task: AgentTaskRecord) -> dict[str, object]:
    return {
        "task_group_id": task.task_group_id,
        "task_id": task.task_id,
        "target_agent_id": task.target_agent_id,
        "status": task.status,
        "title": _task_title(task.target_agent_id),
        "detail": _queued_detail(task),
        "artifact_refs": list(task.artifact_refs),
        "product_refs": [],
        "child_run_id": task.child_run_id,
    }


def _task_title(target_agent_id: str) -> str:
    if target_agent_id == "resume_agent":
        return "解析简历"
    if target_agent_id == "job_agent":
        return "分析岗位"
    return "执行子任务"


def _queued_detail(task: AgentTaskRecord) -> str:
    if task.artifact_refs:
        return f"等待处理 {len(task.artifact_refs)} 个 artifact"
    return "等待执行"


def _running_detail(task: AgentTaskRecord) -> str:
    if task.target_agent_id == "resume_agent":
        return "正在解析简历 artifact"
    if task.target_agent_id == "job_agent":
        return "正在分析 JD 和匹配度"
    return "正在执行委派任务"


def _group_completion_detail(status: str, results: list[AgentTaskResult]) -> str:
    completed = sum(1 for result in results if result.status == "completed")
    failed = sum(1 for result in results if result.status == "failed")
    if status == "completed":
        return f"{completed} 个 agent 任务已完成"
    if status == "failed":
        return f"{failed} 个 agent 任务失败"
    return f"{completed} 个完成，{failed} 个失败"


def _child_completion_error(*, spec: AgentTaskSpec, result: object) -> str | None:
    answer = _result_text(result, "answer")
    summary = _result_text(result, "summary")
    if _TOOL_CALL_LIMIT_MESSAGE in answer or _TOOL_CALL_LIMIT_MESSAGE in summary:
        return "子 Agent 达到工具调用上限，未生成可靠最终结果；该任务不能标记为完成。"
    if any(marker in answer or marker in summary for marker in _UNRELIABLE_FALLBACK_MARKERS):
        return "子 Agent 未生成可靠最终结果；该任务不能标记为完成。"
    if spec.target_agent_id == "job_agent" and _task_requires_job_fit_report(spec.instruction):
        product_refs = _result_refs(result, "product_refs")
        output_artifact_refs = _result_refs(result, "output_artifact_refs")
        missing: list[str] = []
        if not any(ref.startswith("fit_") for ref in product_refs):
            missing.append("job_fit_report")
        if not output_artifact_refs:
            missing.append("report_artifact")
        if missing:
            return f"job_agent JD 匹配子任务未完成：缺少 {', '.join(missing)}。"
    if spec.target_agent_id == "resume_agent" and _task_requires_resume_profile(spec.instruction):
        product_refs = _result_refs(result, "product_refs")
        output_artifact_refs = _result_refs(result, "output_artifact_refs")
        missing = []
        if not any(_is_real_resume_profile_ref(ref) for ref in product_refs):
            missing.append("resume_profile")
        if _task_requires_resume_diagnosis_artifact(spec.instruction) and not output_artifact_refs:
            missing.append("diagnosis_artifact")
        if missing:
            return f"resume_agent 简历解析子任务未完成：缺少 {', '.join(missing)}。"
    return None


def _task_requires_resume_profile(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "resumeprofile",
            "resume_profile",
            "简历画像",
            "保存简历",
            "保存 resumeprofile",
            "保存 resume_profile",
        )
    )


def _task_requires_resume_diagnosis_artifact(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "诊断报告",
            "diagnosis",
            "markdown",
            "artifact",
        )
    )


def _is_real_resume_profile_ref(ref: str) -> bool:
    if not ref.startswith("resume_profile_"):
        return False
    lowered = ref.lower()
    return not any(marker in lowered for marker in ("xxx", "todo", "placeholder", "example", "示例", "占位"))


def _task_requires_job_fit_report(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "匹配报告",
            "岗位匹配",
            "jobfitreport",
            "job_fit_report",
            "fit report",
        )
    )


def _result_text(result: object, field_name: str) -> str:
    value = getattr(result, field_name, "")
    return value if isinstance(value, str) else ""


def _result_refs(result: object, field_name: str) -> list[str]:
    value = getattr(result, field_name, [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _shorten(value: str, max_chars: int) -> str:
    text = " ".join(value.strip().split())
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def _require_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _normalize_optional_string(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_non_empty(name, value)


def _normalize_string_list(name: str, values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(f"{name} must be a list.")
    output: list[str] = []
    for raw in values:
        output.append(_require_non_empty(name, raw))
    return output
