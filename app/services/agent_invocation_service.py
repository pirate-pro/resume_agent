"""Service for one controlled child-agent invocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.models import AgentRunInput, RunContext
from app.domain.protocols import SessionRepository
from app.runtime.agent_events import (
    AGENT_RESULT_SUMMARY_EVENT,
    AGENT_TASK_ASSIGNED_EVENT,
    AgentResultSummaryPayload,
    AgentTaskAssignedPayload,
)
from app.runtime.agent_registry import AgentRegistry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.event_recorder import EventRecorder
from app.services.agent_artifact_refs import normalize_agent_artifact_refs
from app.services.agent_result_refs import AgentOutputRefs, collect_agent_output_refs

_ARTIFACT_PREVIEW_CHARS = 1600

__all__ = [
    "AgentInvocationRequest",
    "AgentInvocationResult",
    "AgentInvocationService",
]

@dataclass(slots=True)
class AgentInvocationRequest:
    """Input contract for a single delegated agent run."""

    source_context: RunContext
    target_agent_id: str
    instruction: str
    constraints: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    skill_names: list[str] = field(default_factory=list)
    max_tool_rounds: int = 10
    task_id: str | None = None
    child_run_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_context, RunContext):
            raise ValidationError("source_context must be RunContext.")
        self.target_agent_id = _require_non_empty("target_agent_id", self.target_agent_id)
        self.instruction = _require_non_empty("instruction", self.instruction)
        self.constraints = _normalize_string_list("constraints", self.constraints)
        self.artifact_refs = normalize_agent_artifact_refs("artifact_refs", self.artifact_refs)
        self.skill_names = _normalize_optional_string_list("skill_names", self.skill_names)
        if self.max_tool_rounds < 0 or self.max_tool_rounds > 20:
            raise ValidationError("max_tool_rounds must be in range 0..20.")
        if self.task_id is not None:
            self.task_id = _require_non_empty("task_id", self.task_id)
        if self.child_run_id is not None:
            self.child_run_id = _require_non_empty("child_run_id", self.child_run_id)


@dataclass(slots=True)
class AgentInvocationResult:
    """Result returned after a child agent run completes."""

    task_id: str
    source_agent_id: str
    target_agent_id: str
    child_run_id: str
    status: str
    summary: str
    artifact_refs: list[str]
    output_artifact_refs: list[str]
    product_refs: list[str]
    answer: str

    def __post_init__(self) -> None:
        self.task_id = _require_non_empty("task_id", self.task_id)
        self.source_agent_id = _require_non_empty("source_agent_id", self.source_agent_id)
        self.target_agent_id = _require_non_empty("target_agent_id", self.target_agent_id)
        self.child_run_id = _require_non_empty("child_run_id", self.child_run_id)
        self.status = _require_non_empty("status", self.status)
        self.summary = _require_non_empty("summary", self.summary)
        self.artifact_refs = normalize_agent_artifact_refs("artifact_refs", self.artifact_refs)
        self.output_artifact_refs = normalize_agent_artifact_refs("output_artifact_refs", self.output_artifact_refs)
        self.product_refs = _normalize_string_list("product_refs", self.product_refs)
        self.answer = _require_non_empty("answer", self.answer)


class AgentInvocationService:
    """Authorize and execute one child-agent run using the existing runtime."""

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        runtime: AgentRuntime,
        event_recorder: EventRecorder,
        session_repository: SessionRepository,
    ) -> None:
        self._agent_registry = agent_registry
        self._runtime = runtime
        self._event_recorder = event_recorder
        self._session_repository = session_repository

    def invoke(self, request: AgentInvocationRequest) -> AgentInvocationResult:
        if not isinstance(request, AgentInvocationRequest):
            raise ValidationError("request must be AgentInvocationRequest.")

        source_agent_id = request.source_context.agent_id
        target_agent_id = request.target_agent_id
        self._validate_invocation(source_agent_id=source_agent_id, target_agent_id=target_agent_id)
        self._validate_artifact_refs(
            session_id=request.source_context.session_id,
            target_agent_id=target_agent_id,
            artifact_refs=request.artifact_refs,
        )

        task_id = request.task_id or f"task_{uuid4().hex[:12]}"
        child_context = self._build_child_context(
            source_context=request.source_context,
            target_agent_id=target_agent_id,
            child_run_id=request.child_run_id,
        )
        self._record_task_assignment(task_id=task_id, request=request, child_context=child_context)

        try:
            output = self._runtime.run(
                AgentRunInput(
                    session_id=request.source_context.session_id,
                    user_message=_build_child_instruction_message(
                        task_id=task_id,
                        request=request,
                        artifact_previews=self._build_artifact_previews(
                            session_id=request.source_context.session_id,
                            artifact_refs=request.artifact_refs,
                        ),
                    ),
                    skill_names=self._resolve_child_skill_names(request),
                    max_tool_rounds=request.max_tool_rounds,
                    context=child_context,
                )
            )
        except Exception as exc:
            summary = _failure_summary(exc)
            failed_refs = AgentOutputRefs(input_artifact_refs=list(request.artifact_refs))
            self._record_result_summary(
                context=child_context,
                task_id=task_id,
                source_agent_id=target_agent_id,
                target_agent_id=source_agent_id,
                status="failed",
                summary=summary,
                refs=failed_refs,
            )
            raise

        summary = output.answer.strip() or "(no answer)"
        output_refs = collect_agent_output_refs(
            session_repository=self._session_repository,
            session_id=request.source_context.session_id,
            agent_id=target_agent_id,
            run_id=child_context.run_id,
            input_artifact_refs=request.artifact_refs,
        )
        self._record_result_summary(
            context=child_context,
            task_id=task_id,
            source_agent_id=target_agent_id,
            target_agent_id=source_agent_id,
            status="completed",
            summary=summary,
            refs=output_refs,
        )
        return AgentInvocationResult(
            task_id=task_id,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            child_run_id=child_context.run_id,
            status="completed",
            summary=summary,
            artifact_refs=output_refs.artifact_refs,
            output_artifact_refs=output_refs.output_artifact_refs,
            product_refs=output_refs.product_refs,
            answer=output.answer,
        )

    def _validate_invocation(self, *, source_agent_id: str, target_agent_id: str) -> None:
        self._agent_registry.require(source_agent_id)
        self._agent_registry.require(target_agent_id)
        if not self._agent_registry.can_invoke(source_agent_id, target_agent_id):
            raise ValidationError(f"Agent '{source_agent_id}' is not allowed to invoke '{target_agent_id}'.")

    def _validate_artifact_refs(self, *, session_id: str, target_agent_id: str, artifact_refs: list[str]) -> None:
        _ = target_agent_id
        for artifact_id in artifact_refs:
            artifact = self._session_repository.get_session_artifact(session_id, artifact_id)
            if artifact is None:
                raise ValidationError(f"Artifact not found in session: artifact_id={artifact_id}")
            if artifact.visibility != "session_shared":
                raise ValidationError(f"Artifact is not visible to child agents: artifact_id={artifact_id}")

    def _resolve_child_skill_names(self, request: AgentInvocationRequest) -> list[str]:
        return self._agent_registry.capability_for(request.target_agent_id).resolve_skill_names(
            request.skill_names or None
        )

    def _build_child_context(
        self,
        *,
        source_context: RunContext,
        target_agent_id: str,
        child_run_id: str | None,
    ) -> RunContext:
        return RunContext(
            session_id=source_context.session_id,
            run_id=child_run_id or f"run_{uuid4().hex[:12]}",
            agent_id=target_agent_id,
            turn_id=f"turn_{uuid4().hex[:12]}",
            entry_agent_id=source_context.entry_agent_id,
            parent_run_id=source_context.run_id,
            trace_flags=dict(source_context.trace_flags),
        )

    def _record_task_assignment(
        self,
        *,
        task_id: str,
        request: AgentInvocationRequest,
        child_context: RunContext,
    ) -> None:
        payload = AgentTaskAssignedPayload(
            task_id=task_id,
            source_agent_id=request.source_context.agent_id,
            target_agent_id=request.target_agent_id,
            instruction=request.instruction,
            constraints=request.constraints,
            artifact_refs=request.artifact_refs,
            parent_run_id=request.source_context.run_id,
            child_run_id=child_context.run_id,
        )
        self._event_recorder.record(
            context=request.source_context,
            event_type=AGENT_TASK_ASSIGNED_EVENT,
            payload=payload.to_payload(),
        )

    def _record_result_summary(
        self,
        *,
        context: RunContext,
        task_id: str,
        source_agent_id: str,
        target_agent_id: str,
        status: str,
        summary: str,
        refs: AgentOutputRefs,
    ) -> None:
        payload = AgentResultSummaryPayload(
            task_id=task_id,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            status=status,
            summary=summary,
            artifact_refs=refs.artifact_refs,
            output_artifact_refs=refs.output_artifact_refs,
            product_refs=refs.product_refs,
            parent_run_id=context.parent_run_id,
        )
        self._event_recorder.record(
            context=context,
            event_type=AGENT_RESULT_SUMMARY_EVENT,
            payload=payload.to_payload(),
        )

    def _build_artifact_previews(self, *, session_id: str, artifact_refs: list[str]) -> list[dict[str, str]]:
        previews: list[dict[str, str]] = []
        for artifact_id in artifact_refs:
            artifact = self._session_repository.get_session_artifact(session_id, artifact_id)
            if artifact is None:
                continue
            try:
                text = self._session_repository.read_session_artifact_text(session_id, artifact_id)
            except Exception:  # noqa: BLE001
                text = ""
            previews.append(
                {
                    "artifact_id": artifact.artifact_id,
                    "title": artifact.title,
                    "text": _truncate_text(text, _ARTIFACT_PREVIEW_CHARS),
                }
            )
        return previews


def _build_child_instruction_message(
    *,
    task_id: str,
    request: AgentInvocationRequest,
    artifact_previews: list[dict[str, str]] | None = None,
) -> str:
    lines = [
        f"你收到一个来自 {request.source_context.agent_id} 的子任务。",
        f"task_id: {task_id}",
        f"target_agent_id: {request.target_agent_id}",
        "",
        "instruction:",
        request.instruction,
    ]
    if request.constraints:
        lines.extend(["", "constraints:", *[f"- {item}" for item in request.constraints]])
    if request.artifact_refs:
        lines.extend(["", "artifact_refs:", *[f"- {item}" for item in request.artifact_refs]])
        lines.extend(
            [
                "",
                "artifact 事实源规则:",
                "- artifact_refs 指向的会话资料是本子任务的事实源。",
                "- 如果 instruction 内联文本、示例或历史内容与 artifact 内容冲突，必须以 artifact 为准。",
                "- 保存产品记录时，不要写入 artifact 中未出现的人名、公司、学校、项目、时间、指标或技能。",
            ]
        )
    if artifact_previews:
        lines.extend(["", "artifact 内容预览:"])
        for item in artifact_previews:
            lines.extend(
                [
                    f"- artifact_id: {item['artifact_id']}",
                    f"  title: {item['title']}",
                    "  text:",
                    _indent_block(item["text"] or "(无可用文本预览)", prefix="    "),
                ]
            )
    lines.extend(["", "请只完成该子任务，并输出可供主 agent 汇总的结果。"])
    return "\n".join(lines)


def _truncate_text(text: str, limit: int) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + f"\n...（已截断，完整内容请读取 artifact）"


def _indent_block(text: str, *, prefix: str) -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def _failure_summary(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        message = exc.__class__.__name__
    return f"child agent run failed: {message}"


def _require_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _normalize_string_list(name: str, values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(f"{name} must be a list.")
    output: list[str] = []
    for raw in values:
        output.append(_require_non_empty(name, raw))
    return output


def _normalize_optional_string_list(name: str, values: list[str]) -> list[str]:
    if not values:
        return []
    return _normalize_string_list(name, values)
