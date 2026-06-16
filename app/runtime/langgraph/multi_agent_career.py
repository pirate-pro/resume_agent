"""LangGraph workflow for durable resume and JD multi-agent analysis."""

from __future__ import annotations

import asyncio
import json
import re
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, TimeoutPolicy, interrupt

from app.career.store import CareerProductStore
from app.core.errors import ValidationError
from app.domain.graph_agent_tasks import (
    GRAPH_TASK_STATUS_COMPLETED,
    GRAPH_TASK_STATUS_FAILED,
    GraphAgentTaskAttemptRecord,
)
from app.domain.models import AgentRunInput, AgentRunOutput, RunContext, SessionArtifact, ToolCall, ToolExecutionResult
from app.domain.protocols import SessionRepository
from app.domain.workflow_instance_protocols import WorkflowInstanceStore
from app.domain.workflow_instances import (
    WORKFLOW_STATUS_CANCELLED,
    WORKFLOW_STATUS_COMPLETED,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_RUNNING,
    WORKFLOW_STATUS_WAITING,
    WorkflowInstanceRecord,
)
from app.runtime.agent.tool_gateway import ToolGateway
from app.runtime.event_channel import EventChannel
from app.runtime.event_recorder import EventRecorder
from app.runtime.langgraph.checkpointer import WorkflowCheckpointerHandle
from app.runtime.langgraph.multi_agent_contracts import CAREER_INTAKE_TASK_GRAPH
from app.runtime.langgraph.types import (
    MULTI_AGENT_CAREER_WORKFLOW_ID,
    MultiAgentCareerGraphState,
    WorkflowGraphRunResult,
    WorkflowResumeRequest,
)
from app.runtime.langgraph.write_retry import (
    parse_write_retry_action,
    write_failure_update,
    write_retry_interrupt_payload,
)
from app.services.graph_agent_task_executor import GraphAgentTaskExecutor, GraphAgentTaskRequest
from app.tools.builtin_tools.session_artifact_helpers import (
    ensure_session_artifact_text_ready,
)

__all__ = ["MultiAgentCareerWorkflowRunner"]

_PHASE_STARTED = "started"
_PHASE_INPUT_CONFIRMATION = "input_confirmation"
_PHASE_PARALLEL_ANALYSIS = "parallel_analysis"
_PHASE_FIT_ANALYSIS = "fit_analysis"
_PHASE_TASK_RETRY = "task_retry"
_PHASE_PROJECT_CONFIRMATION = "project_confirmation"
_PHASE_APPLICATION_WRITE = "application_write"
_PHASE_WRITE_RETRY = "write_retry"
_PHASE_COMPLETED = "completed"
_PHASE_CANCELLED = "cancelled"
_PHASE_FAILED = "failed"

_TASK_LABELS = {
    "resume_analysis": "解析简历",
    "jd_analysis": "分析岗位",
    "job_fit_analysis": "生成匹配报告",
}
_ARTIFACT_ID_PATTERN = re.compile(r"\bartifact_[A-Za-z0-9][A-Za-z0-9_-]*\b")
_RESUME_MARKERS = ("简历", "履历", "resume", "curriculum vitae", "cv")
_JD_MARKERS = ("职位描述", "岗位描述", "岗位职责", "任职要求", "job description", "requirements", "jd")


@dataclass(frozen=True, slots=True)
class _ExecutionBindings:
    context: RunContext
    channel: EventChannel | None


_CURRENT_BINDINGS: ContextVar[_ExecutionBindings | None] = ContextVar(
    "multi_agent_career_workflow_bindings",
    default=None,
)


class MultiAgentCareerWorkflowRunner:
    """Run the code-owned `career.intake.analysis.interactive.v1` graph."""

    workflow_id = MULTI_AGENT_CAREER_WORKFLOW_ID

    def __init__(
        self,
        *,
        task_executor: GraphAgentTaskExecutor | None = None,
        tool_gateway: ToolGateway | None = None,
        event_recorder: EventRecorder | None = None,
        session_repository: SessionRepository | None = None,
        career_store: CareerProductStore | None = None,
        workflow_store: WorkflowInstanceStore | None = None,
        checkpoint_backend: str = "memory",
        checkpoint_path: Path | None = None,
        node_timeout_seconds: float = 300.0,
    ) -> None:
        normalized_backend = checkpoint_backend.strip().lower()
        if normalized_backend not in {"memory", "sqlite"}:
            raise ValidationError("checkpoint_backend must be memory/sqlite.")
        if node_timeout_seconds <= 0:
            raise ValidationError("node_timeout_seconds must be positive.")
        self._task_executor = task_executor
        self._tool_gateway = tool_gateway
        self._event_recorder = event_recorder
        self._session_repository = session_repository
        self._career_store = career_store
        self._workflow_store = workflow_store
        self._checkpoint_backend = normalized_backend
        self._checkpoint_path = checkpoint_path
        self._memory_checkpointer = InMemorySaver() if normalized_backend == "memory" else None
        self._node_timeout_seconds = node_timeout_seconds

    def initial_state_for(
        self,
        run_input: AgentRunInput,
        *,
        workflow_instance_id: str | None = None,
    ) -> MultiAgentCareerGraphState:
        workflow_id = _workflow_instance_id(workflow_instance_id)
        return MultiAgentCareerGraphState(
            session_id=run_input.session_id,
            run_id=run_input.context.run_id,
            workflow_instance_id=workflow_id,
            thread_id=f"{run_input.session_id}:{workflow_id}",
            contract_id=CAREER_INTAKE_TASK_GRAPH.contract_version,
            user_goal=run_input.user_message,
            phase=_PHASE_STARTED,
            resume_artifact_id=None,
            jd_artifact_id=None,
            selected_career_profile_id=None,
            task_specs={
                task.task_key: {
                    "target_agent_id": task.target_agent_id,
                    "required_inputs": list(task.required_inputs),
                    "required_outputs": list(task.required_outputs),
                    "depends_on": list(task.depends_on),
                    "max_tool_rounds": task.max_tool_rounds,
                }
                for task in CAREER_INTAKE_TASK_GRAPH.tasks
            },
            task_execution_keys={},
            task_attempts={},
            task_results={},
            task_updates=[],
            failed_task_keys=[],
            retry_task_keys=[],
            input_candidates=[],
            project_preview=None,
            known_refs={},
            retry_counters={},
            last_error=None,
            outputs={},
            tool_calls=[],
            answer="",
        )

    async def run_stream(
        self,
        run_input: AgentRunInput,
        *,
        channel: EventChannel | None = None,
    ) -> WorkflowGraphRunResult:
        self._require_runtime_dependencies()
        state = self.initial_state_for(run_input)
        token = _CURRENT_BINDINGS.set(_ExecutionBindings(context=run_input.context, channel=channel))
        try:
            await self._persist_workflow_state(
                run_input.context,
                dict(state),
                status=WORKFLOW_STATUS_RUNNING,
            )
            await self._emit_workflow_event(
                run_input.context,
                "workflow_started",
                {
                    "workflow_instance_id": state["workflow_instance_id"],
                    "thread_id": state["thread_id"],
                    "contract_id": MULTI_AGENT_CAREER_WORKFLOW_ID,
                    "task_contract_id": CAREER_INTAKE_TASK_GRAPH.contract_version,
                },
                channel=channel,
            )
            async with self._checkpointer_handle() as checkpointer:
                graph = self._build_graph(checkpointer.checkpointer)
                result = await graph.ainvoke(
                    state,
                    config={"configurable": {"thread_id": state["thread_id"]}},
                )
        finally:
            _CURRENT_BINDINGS.reset(token)
        return await self._result_from_graph_output(result, context=run_input.context, channel=channel)

    async def resume_stream(
        self,
        request: WorkflowResumeRequest,
        *,
        channel: EventChannel | None = None,
    ) -> WorkflowGraphRunResult:
        self._require_runtime_dependencies()
        token = _CURRENT_BINDINGS.set(_ExecutionBindings(context=request.context, channel=channel))
        try:
            await self._emit_workflow_event(
                request.context,
                "workflow_resumed",
                {
                    "workflow_instance_id": request.workflow_instance_id,
                    "thread_id": request.thread_id,
                    "payload_keys": sorted(request.payload.payload.keys()),
                },
                channel=channel,
            )
            async with self._checkpointer_handle() as checkpointer:
                if not await self._has_checkpoint(checkpointer.checkpointer, request.thread_id):
                    raise ValidationError(
                        f"Missing LangGraph checkpoint for workflow_instance_id={request.workflow_instance_id}."
                    )
                graph = self._build_graph(checkpointer.checkpointer)
                result = await graph.ainvoke(
                    Command(resume=request.payload.payload),
                    config={"configurable": {"thread_id": request.thread_id}},
                )
        finally:
            _CURRENT_BINDINGS.reset(token)
        return await self._result_from_graph_output(result, context=request.context, channel=channel)

    def _require_runtime_dependencies(self) -> None:
        missing = [
            name
            for name, value in (
                ("task_executor", self._task_executor),
                ("tool_gateway", self._tool_gateway),
                ("event_recorder", self._event_recorder),
                ("session_repository", self._session_repository),
                ("career_store", self._career_store),
            )
            if value is None
        ]
        if missing:
            raise ValidationError(f"multi-agent career runner dependencies are missing: {', '.join(missing)}")

    def _checkpointer_handle(self) -> WorkflowCheckpointerHandle:
        return WorkflowCheckpointerHandle(
            backend=self._checkpoint_backend,
            checkpoint_path=self._checkpoint_path,
            memory_checkpointer=self._memory_checkpointer,
        )

    async def _has_checkpoint(self, checkpointer: Any, thread_id: str) -> bool:
        return await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}}) is not None

    def _build_graph(self, checkpointer: Any) -> Any:
        timeout = TimeoutPolicy(run_timeout=self._node_timeout_seconds)
        builder = StateGraph(MultiAgentCareerGraphState)
        builder.add_node("resolve_inputs", self._resolve_inputs)
        builder.add_node("input_confirmation", self._input_confirmation)
        builder.add_node("prepare_inputs", self._prepare_inputs)
        builder.add_node("prepare_parallel_tasks", self._prepare_parallel_tasks)
        builder.add_node("run_parallel_task", self._run_parallel_task, timeout=timeout)
        builder.add_node("join_analysis", self._join_analysis)
        builder.add_node("run_job_fit_analysis", self._run_job_fit_analysis, timeout=timeout)
        builder.add_node("review_task_results", self._review_task_results)
        builder.add_node("task_failure_review", self._task_failure_review)
        builder.add_node("prepare_retry_tasks", self._prepare_retry_tasks)
        builder.add_node("run_retry_task", self._run_retry_task, timeout=timeout)
        builder.add_node("join_retry", self._join_retry)
        builder.add_node("prepare_project_preview", self._prepare_project_preview)
        builder.add_node("project_confirmation", self._project_confirmation)
        builder.add_node("create_career_application", self._create_career_application, timeout=timeout)
        builder.add_node("write_retry", self._write_retry)
        builder.add_node("final_answer", self._final_answer)
        builder.add_edge(START, "resolve_inputs")
        builder.add_conditional_edges(
            "resolve_inputs",
            _route_after_input_resolution,
            {
                "confirm": "input_confirmation",
                "prepare": "prepare_inputs",
            },
        )
        builder.add_edge("input_confirmation", "prepare_inputs")
        builder.add_conditional_edges(
            "prepare_inputs",
            _route_after_input_preparation,
            {
                "confirm": "input_confirmation",
                "parallel": "prepare_parallel_tasks",
            },
        )
        builder.add_conditional_edges("prepare_parallel_tasks", _dispatch_parallel_tasks)
        builder.add_edge("run_parallel_task", "join_analysis")
        builder.add_conditional_edges(
            "join_analysis",
            _route_after_parallel_join,
            {
                "retry": "task_failure_review",
                "fit": "run_job_fit_analysis",
            },
        )
        builder.add_edge("run_job_fit_analysis", "review_task_results")
        builder.add_conditional_edges(
            "review_task_results",
            _route_after_task_review,
            {
                "retry": "task_failure_review",
                "project": "prepare_project_preview",
            },
        )
        builder.add_conditional_edges(
            "task_failure_review",
            _route_after_task_failure_review,
            {
                "retry": "prepare_retry_tasks",
                "final": "final_answer",
            },
        )
        builder.add_conditional_edges("prepare_retry_tasks", _dispatch_retry_tasks)
        builder.add_edge("run_retry_task", "join_retry")
        builder.add_conditional_edges(
            "join_retry",
            _route_after_retry_join,
            {
                "retry": "task_failure_review",
                "fit": "run_job_fit_analysis",
                "project": "prepare_project_preview",
            },
        )
        builder.add_edge("prepare_project_preview", "project_confirmation")
        builder.add_edge("project_confirmation", "create_career_application")
        builder.add_conditional_edges(
            "create_career_application",
            _route_after_application_write,
            {
                "retry": "write_retry",
                "final": "final_answer",
            },
        )
        builder.add_conditional_edges(
            "write_retry",
            _route_after_write_retry,
            {
                "retry": "create_career_application",
                "final": "final_answer",
            },
        )
        builder.add_edge("final_answer", END)
        return builder.compile(checkpointer=checkpointer)

    async def _resolve_inputs(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        if state.get("resume_artifact_id") and state.get("jd_artifact_id"):
            return {"phase": _PHASE_PARALLEL_ANALYSIS}
        repository = cast(SessionRepository, self._session_repository)
        artifacts = [
            item
            for item in repository.list_session_artifacts(state["session_id"])
            if item.status in {"uploaded", "ready"}
            and item.visibility == "session_shared"
        ]
        candidates = _artifact_candidates(repository, state["session_id"], artifacts)
        resume_id, jd_id = _auto_select_inputs(
            user_goal=state.get("user_goal", ""),
            candidates=candidates,
            active_ids=repository.get_active_artifact_ids(state["session_id"]),
        )
        if resume_id and jd_id:
            return {
                "phase": _PHASE_PARALLEL_ANALYSIS,
                "resume_artifact_id": resume_id,
                "jd_artifact_id": jd_id,
                "input_candidates": candidates,
                "known_refs": {
                    "resume_artifact_id": resume_id,
                    "jd_artifact_id": jd_id,
                },
            }
        return {
            "phase": _PHASE_INPUT_CONFIRMATION,
            "input_candidates": candidates,
        }

    async def _input_confirmation(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        payload = {
            "type": "career_input_confirmation",
            "workflow_instance_id": state["workflow_instance_id"],
            "thread_id": state["thread_id"],
            "question": "请选择本次要分析的简历和目标岗位 JD。",
            "candidates": state.get("input_candidates", []),
            "resume_artifact_id": state.get("resume_artifact_id"),
            "jd_artifact_id": state.get("jd_artifact_id"),
        }
        answer = interrupt(payload)
        resume_id, jd_id = _parse_input_confirmation(answer, state.get("input_candidates", []))
        return {
            "phase": _PHASE_PARALLEL_ANALYSIS,
            "resume_artifact_id": resume_id,
            "jd_artifact_id": jd_id,
            "known_refs": {
                "resume_artifact_id": resume_id,
                "jd_artifact_id": jd_id,
            },
            "pending_question": None,
        }

    async def _prepare_inputs(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        repository = cast(SessionRepository, self._session_repository)
        artifact_ids = [
            _required_string(state.get("resume_artifact_id"), "resume_artifact_id"),
            _required_string(state.get("jd_artifact_id"), "jd_artifact_id"),
        ]
        artifacts: list[SessionArtifact] = []
        for artifact_id in artifact_ids:
            artifact = repository.get_session_artifact(state["session_id"], artifact_id)
            if artifact is None or artifact.visibility != "session_shared":
                return {
                    "phase": _PHASE_INPUT_CONFIRMATION,
                    "resume_artifact_id": None,
                    "jd_artifact_id": None,
                    "last_error": {
                        "node": "prepare_inputs",
                        "error": f"资料不可用：{artifact_id}",
                    },
                }
            artifacts.append(artifact)
        try:
            for artifact in artifacts:
                await asyncio.to_thread(
                    ensure_session_artifact_text_ready,
                    repository,
                    state["session_id"],
                    artifact,
                )
        except Exception as exc:  # noqa: BLE001
            refreshed = repository.list_session_artifacts(state["session_id"])
            return {
                "phase": _PHASE_INPUT_CONFIRMATION,
                "resume_artifact_id": None,
                "jd_artifact_id": None,
                "input_candidates": _artifact_candidates(
                    repository,
                    state["session_id"],
                    [
                        item
                        for item in refreshed
                        if item.status in {"uploaded", "ready"}
                        and item.visibility == "session_shared"
                    ],
                ),
                "last_error": {
                    "node": "prepare_inputs",
                    "error": str(exc).strip() or exc.__class__.__name__,
                },
            }
        return {
            "phase": _PHASE_PARALLEL_ANALYSIS,
            "last_error": None,
        }

    async def _prepare_parallel_tasks(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        task_keys = [
            key
            for key in ("resume_analysis", "jd_analysis")
            if _task_status(state, key) != GRAPH_TASK_STATUS_COMPLETED
        ]
        attempts = [
            self._executor().ensure_attempt(self._task_request(state, key))
            for key in task_keys
        ]
        await self._emit_task_group_created(state, attempts, group_suffix="analysis")
        return {
            "phase": _PHASE_PARALLEL_ANALYSIS,
            "retry_task_keys": task_keys,
        }

    async def _run_parallel_task(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        task_key = _required_task_key(state)
        return {"task_updates": [await self._execute_task(state, task_key, retry_failed=False)]}

    async def _join_analysis(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        results = _normalized_task_results(state)
        failed = [
            key
            for key in ("resume_analysis", "jd_analysis")
            if _result_status(results, key) == GRAPH_TASK_STATUS_FAILED
        ]
        await self._emit_task_group_completed(state, results, task_keys=("resume_analysis", "jd_analysis"))
        return {
            "task_results": results,
            "task_attempts": _task_attempts(results),
            "failed_task_keys": failed,
            "phase": _PHASE_TASK_RETRY if failed else _PHASE_FIT_ANALYSIS,
        }

    async def _run_job_fit_analysis(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        results = _normalized_task_results(state)
        career_profile_id = _career_profile_id(results, self._career_store)
        fit_state = dict(state)
        fit_state["task_results"] = results
        fit_state["selected_career_profile_id"] = career_profile_id
        retry_failed = _result_status(results, "job_fit_analysis") == GRAPH_TASK_STATUS_FAILED
        update = await self._execute_task(
            cast(MultiAgentCareerGraphState, fit_state),
            "job_fit_analysis",
            retry_failed=retry_failed,
        )
        return {
            "phase": _PHASE_FIT_ANALYSIS,
            "selected_career_profile_id": career_profile_id,
            "task_updates": [update],
        }

    async def _review_task_results(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        results = _normalized_task_results(state)
        failed = [
            task.task_key
            for task in CAREER_INTAKE_TASK_GRAPH.tasks
            if _result_status(results, task.task_key) == GRAPH_TASK_STATUS_FAILED
        ]
        await self._emit_task_group_completed(
            state,
            results,
            task_keys=tuple(task.task_key for task in CAREER_INTAKE_TASK_GRAPH.tasks),
        )
        return {
            "task_results": results,
            "task_attempts": _task_attempts(results),
            "failed_task_keys": failed,
            "phase": _PHASE_TASK_RETRY if failed else _PHASE_PROJECT_CONFIRMATION,
        }

    async def _task_failure_review(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        results = _normalized_task_results(state)
        failed_keys = [
            key
            for key in state.get("failed_task_keys", [])
            if _result_status(results, key) == GRAPH_TASK_STATUS_FAILED
        ]
        payload = {
            "type": "workflow_task_retry",
            "workflow_instance_id": state["workflow_instance_id"],
            "thread_id": state["thread_id"],
            "question": "部分分析步骤失败。可以只重试失败步骤，已完成结果不会重复执行。",
            "failed_tasks": [
                {
                    "task_key": key,
                    "title": _TASK_LABELS.get(key, key),
                    "target_agent_id": results.get(key, {}).get("target_agent_id"),
                    "attempt": results.get(key, {}).get("attempt"),
                    "error": results.get(key, {}).get("error"),
                }
                for key in failed_keys
            ],
            "completed_tasks": [
                key
                for key, value in results.items()
                if value.get("status") == GRAPH_TASK_STATUS_COMPLETED
            ],
            "actions": ["retry_failed", "cancel"],
        }
        answer = interrupt(payload)
        action = _parse_task_retry_action(answer)
        if action == "cancel":
            return {
                "phase": _PHASE_CANCELLED,
                "answer": "已停止后续分析。已经生成的分析产物会保留。",
                "outputs": {**dict(state.get("outputs") or {}), "cancelled": True},
                "pending_question": None,
            }
        return {
            "phase": _PHASE_TASK_RETRY,
            "retry_task_keys": failed_keys,
            "pending_question": None,
            "last_error": None,
        }

    async def _prepare_retry_tasks(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        attempts = [
            self._executor().ensure_attempt(
                self._task_request(state, key),
                retry_failed=True,
            )
            for key in state.get("retry_task_keys", [])
        ]
        await self._emit_task_group_created(state, attempts, group_suffix="retry")
        return {}

    async def _run_retry_task(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        task_key = _required_task_key(state)
        return {"task_updates": [await self._execute_task(state, task_key, retry_failed=True)]}

    async def _join_retry(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        results = _normalized_task_results(state)
        failed = [
            key
            for key in state.get("retry_task_keys", [])
            if _result_status(results, key) == GRAPH_TASK_STATUS_FAILED
        ]
        all_roots_completed = all(
            _result_status(results, key) == GRAPH_TASK_STATUS_COMPLETED
            for key in ("resume_analysis", "jd_analysis")
        )
        fit_completed = _result_status(results, "job_fit_analysis") == GRAPH_TASK_STATUS_COMPLETED
        if failed:
            phase = _PHASE_TASK_RETRY
        elif all_roots_completed and not fit_completed:
            phase = _PHASE_FIT_ANALYSIS
        else:
            phase = _PHASE_PROJECT_CONFIRMATION
        return {
            "task_results": results,
            "task_attempts": _task_attempts(results),
            "failed_task_keys": failed,
            "phase": phase,
        }

    async def _prepare_project_preview(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        if state.get("project_preview") is not None:
            return {"phase": _PHASE_PROJECT_CONFIRMATION}
        results = _normalized_task_results(state)
        resume_profile_id = _required_output_ref(results, "resume_analysis", "resume_profile_")
        jd_analysis_id = _required_output_ref(results, "jd_analysis", "jd_")
        job_fit_report_id = _required_output_ref(results, "job_fit_analysis", "fit_")
        career_profile_id = state.get("selected_career_profile_id") or "career_profile_default"
        store = cast(CareerProductStore, self._career_store)
        jd_record = store.get_jd_analysis(jd_analysis_id)
        fit_record = store.get_job_fit_report(job_fit_report_id)
        preview = {
            "company": jd_record.company if jd_record is not None else "",
            "position": jd_record.position if jd_record is not None else "",
            "location": "",
            "stage": "draft",
            "priority": "medium",
            "summary": (
                f"岗位匹配度 {fit_record.overall_score}/100，建议：{fit_record.recommendation}。"
                if fit_record is not None
                else "已完成简历、JD 和岗位匹配分析。"
            ),
            "resume_profile_id": resume_profile_id,
            "career_profile_id": career_profile_id,
            "jd_analysis_id": jd_analysis_id,
            "job_fit_report_id": job_fit_report_id,
            "source_artifact_id": state.get("jd_artifact_id"),
            "evidence_refs": _dedupe_strings(
                [
                    resume_profile_id,
                    career_profile_id,
                    jd_analysis_id,
                    job_fit_report_id,
                    state.get("resume_artifact_id"),
                    state.get("jd_artifact_id"),
                    *_result_refs(results, "resume_analysis", "output_artifact_refs"),
                    *_result_refs(results, "job_fit_analysis", "output_artifact_refs"),
                ]
            ),
        }
        return {
            "phase": _PHASE_PROJECT_CONFIRMATION,
            "project_preview": preview,
            "known_refs": {
                "resume_profile_id": resume_profile_id,
                "career_profile_id": career_profile_id,
                "jd_analysis_id": jd_analysis_id,
                "job_fit_report_id": job_fit_report_id,
            },
        }

    async def _project_confirmation(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        if state.get("outputs", {}).get("project_confirmed") is True:
            return {}
        payload = {
            "type": "career_project_confirmation",
            "workflow_instance_id": state["workflow_instance_id"],
            "thread_id": state["thread_id"],
            "question": "分析已完成。确认后再创建求职项目。",
            "project_preview": state.get("project_preview") or {},
            "task_results": _public_task_results(_normalized_task_results(state)),
            "actions": ["approve", "edit_project_fields", "cancel"],
        }
        answer = interrupt(payload)
        action, preview = _parse_project_confirmation(answer, state.get("project_preview") or {})
        if action == "cancel":
            return {
                "phase": _PHASE_CANCELLED,
                "answer": "已保留分析产物，未创建求职项目。",
                "outputs": {**dict(state.get("outputs") or {}), "cancelled": True},
                "pending_question": None,
            }
        return {
            "phase": _PHASE_APPLICATION_WRITE,
            "project_preview": preview,
            "outputs": {**dict(state.get("outputs") or {}), "project_confirmed": True},
            "pending_question": None,
        }

    async def _create_career_application(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        if state.get("phase") == _PHASE_CANCELLED:
            return {}
        outputs = dict(state.get("outputs") or {})
        if isinstance(outputs.get("application_id"), str):
            return {"phase": _PHASE_COMPLETED}
        preview = dict(state.get("project_preview") or {})
        args = {
            "application_id": _application_id(state["workflow_instance_id"]),
            "company": _string(preview.get("company")) or "",
            "position": _string(preview.get("position")) or "",
            "location": _string(preview.get("location")) or "",
            "stage": _string(preview.get("stage")) or "draft",
            "priority": _string(preview.get("priority")) or "medium",
            "summary": _string(preview.get("summary")) or "",
            "resume_profile_id": _string(preview.get("resume_profile_id")),
            "career_profile_id": _string(preview.get("career_profile_id")),
            "jd_analysis_id": _string(preview.get("jd_analysis_id")),
            "job_fit_report_id": _string(preview.get("job_fit_report_id")),
            "source_artifact_id": _string(preview.get("source_artifact_id")),
            "evidence_refs": [
                item
                for item in preview.get("evidence_refs", [])
                if isinstance(item, str) and item.strip()
            ],
        }
        result = await self._execute_tool(
            "career_application_create",
            args,
            state=state,
            missing_output="career_application",
        )
        if not result.success:
            await self._emit_node_failed(state, "create_career_application", result.content)
            return write_failure_update(
                dict(state),
                failed_node="create_career_application",
                error=result.content,
                retry_phase=_PHASE_WRITE_RETRY,
            )
        payload = _json_object(result.content)
        application_id = (
            _string(payload.get("record_id"))
            or _string(payload.get("application_id"))
            or _application_id(state["workflow_instance_id"])
        )
        return {
            "phase": _PHASE_COMPLETED,
            "last_error": None,
            "outputs": {
                **outputs,
                "project_confirmed": True,
                "application_id": application_id,
            },
            "tool_calls": _append_tool_call(state, "career_application_create", args),
        }

    async def _write_retry(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        payload = write_retry_interrupt_payload(
            dict(state),
            question="求职项目创建失败。可以只重试创建步骤，分析任务不会重复执行。",
            operation_label="创建求职项目",
        )
        answer = interrupt(payload)
        action = parse_write_retry_action(answer)
        if action == "cancel":
            return {
                "phase": _PHASE_CANCELLED,
                "answer": "已保留分析产物，未创建求职项目。",
                "outputs": {**dict(state.get("outputs") or {}), "cancelled": True},
                "pending_question": None,
            }
        return {
            "phase": _PHASE_APPLICATION_WRITE,
            "last_error": None,
            "pending_question": None,
        }

    async def _final_answer(self, state: MultiAgentCareerGraphState) -> dict[str, Any]:
        if state.get("phase") == _PHASE_CANCELLED:
            return {"answer": _string(state.get("answer")) or "已取消本次 workflow。"}
        if state.get("phase") == _PHASE_FAILED:
            return {"answer": _string(state.get("answer")) or "求职分析 workflow 失败。"}
        outputs = dict(state.get("outputs") or {})
        application_id = _string(outputs.get("application_id"))
        answer = (
            "已完成简历分析、JD 分析和岗位匹配，并创建求职项目。"
            f"\n\napplication_id: {application_id}"
            if application_id
            else "已完成分析，未创建求职项目。"
        )
        await self._emit_workflow_event(
            _bindings().context,
            "workflow_completed",
            {
                "workflow_instance_id": state.get("workflow_instance_id"),
                "thread_id": state.get("thread_id"),
                "application_id": application_id,
            },
            channel=_bindings().channel,
        )
        return {"answer": answer}

    async def _execute_task(
        self,
        state: MultiAgentCareerGraphState,
        task_key: str,
        *,
        retry_failed: bool,
    ) -> dict[str, Any]:
        request = self._task_request(state, task_key)
        attempt = self._executor().ensure_attempt(request, retry_failed=retry_failed)
        child_run_id = attempt.child_run_id or f"run_{uuid4().hex[:12]}"
        request = replace(request, child_run_id=child_run_id)
        if attempt.status != GRAPH_TASK_STATUS_COMPLETED:
            await self._emit_agent_task_event(
                "agent_task_started",
                attempt,
                state=state,
                status="running",
                child_run_id=child_run_id,
                detail=f"正在{_TASK_LABELS.get(task_key, '执行任务')}",
            )
        result = await self._executor().execute(request, retry_failed=retry_failed)
        event_type = (
            "agent_task_completed"
            if result.status == GRAPH_TASK_STATUS_COMPLETED
            else "agent_task_failed"
        )
        await self._emit_agent_task_event(
            event_type,
            result,
            state=state,
            status=result.status,
            child_run_id=result.child_run_id,
            detail=result.summary or result.error or result.status,
        )
        return _attempt_result(result)

    def _task_request(
        self,
        state: MultiAgentCareerGraphState,
        task_key: str,
    ) -> GraphAgentTaskRequest:
        definition = CAREER_INTAKE_TASK_GRAPH.task(task_key)
        if task_key == "resume_analysis":
            artifact_id = _required_string(state.get("resume_artifact_id"), "resume_artifact_id")
            input_refs = {"resume_artifact_id": artifact_id}
            artifact_refs = (artifact_id,)
            instruction = (
                f"读取简历 artifact `{artifact_id}`，完成简历诊断。"
                "必须生成可预览的诊断 artifact，并调用 career_resume_profile_save 保存 ResumeProfile。"
                "保存前逐项核对源文档中的教育经历、工作经历、项目经历和技能；"
                "源文档存在的章节必须写入对应结构化字段，不得遗漏。"
                "最终答复明确列出真实 resume_profile_id 和 diagnosis artifact_id。"
                "不要分析 JD，不要创建求职项目。"
            )
        elif task_key == "jd_analysis":
            artifact_id = _required_string(state.get("jd_artifact_id"), "jd_artifact_id")
            input_refs = {"jd_artifact_id": artifact_id}
            artifact_refs = (artifact_id,)
            instruction = (
                f"读取目标岗位 JD artifact `{artifact_id}`，提取岗位要求并调用 "
                "career_jd_analysis_save 保存 JDAnalysis。最终答复明确列出真实 jd_analysis_id。"
                "本任务只做 JD 分析，不生成岗位匹配报告，不创建求职项目。"
            )
        else:
            results = _normalized_task_results(state)
            resume_profile_id = _required_output_ref(results, "resume_analysis", "resume_profile_")
            jd_analysis_id = _required_output_ref(results, "jd_analysis", "jd_")
            career_profile_id = (
                state.get("selected_career_profile_id")
                or _career_profile_id(results, self._career_store)
            )
            input_refs = {
                "resume_profile_id": resume_profile_id,
                "career_profile_id": career_profile_id,
                "jd_analysis_id": jd_analysis_id,
            }
            jd_artifact_id = _required_string(state.get("jd_artifact_id"), "jd_artifact_id")
            artifact_refs = (jd_artifact_id,)
            instruction = (
                f"基于 resume_profile_id=`{resume_profile_id}`、career_profile_id=`{career_profile_id}`、"
                f"jd_analysis_id=`{jd_analysis_id}` 生成岗位匹配报告。"
                "必须生成可预览的报告 artifact，并调用 career_job_fit_report_save 保存 JobFitReport。"
                "最终答复明确列出真实 job_fit_report_id 和 report artifact_id。"
                "不要创建 CareerApplication。"
            )
        return GraphAgentTaskRequest(
            source_context=_bindings().context,
            workflow_instance_id=state["workflow_instance_id"],
            graph=CAREER_INTAKE_TASK_GRAPH,
            definition=definition,
            instruction=instruction,
            input_refs=input_refs,
            constraints=(
                "只使用当前 session 中可验证的 artifact 和产品记录。",
                "缺少 required output 时必须明确失败，不得编造引用。",
            ),
            artifact_refs=artifact_refs,
        )

    def _executor(self) -> GraphAgentTaskExecutor:
        return cast(GraphAgentTaskExecutor, self._task_executor)

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        state: MultiAgentCareerGraphState,
        missing_output: str,
    ) -> ToolExecutionResult:
        bindings = _bindings()
        tool_call = ToolCall(name=tool_name, arguments=arguments)
        recorder = cast(EventRecorder, self._event_recorder)
        await recorder.record_async(
            bindings.context,
            "tool_call",
            {"name": tool_call.name, "arguments": tool_call.arguments, "tool_call_id": tool_call.tool_call_id},
            channel=bindings.channel,
        )
        gateway_result = await cast(ToolGateway, self._tool_gateway).execute_async(
            tool_call,
            bindings.context,
            pending_runtime_plan={
                "phase": "career_intake_application_write",
                "contract_id": CAREER_INTAKE_TASK_GRAPH.contract_version,
                "next_action": f"LangGraph workflow 正在执行 {tool_name}。",
                "current_allowed_tools": [tool_name],
                "next_allowed_tools": [tool_name],
                "required_tools": [tool_name],
                "upcoming_required_tools": [],
                "known_refs": state.get("known_refs") or {},
                "missing_outputs": [missing_output],
                "final_answer_ready": False,
                "discouraged_tools": [],
            },
        )
        result = gateway_result.result
        await recorder.record_async(
            bindings.context,
            "tool_result",
            {
                "tool_name": result.tool_name,
                "success": result.success,
                "content": result.content,
                "tool_call_id": gateway_result.tool_call.tool_call_id,
            },
            channel=bindings.channel,
        )
        return result

    async def _emit_task_group_created(
        self,
        state: MultiAgentCareerGraphState,
        attempts: list[GraphAgentTaskAttemptRecord],
        *,
        group_suffix: str,
    ) -> None:
        if not attempts:
            return
        payload = {
            "task_group_id": f"{state['workflow_instance_id']}:{group_suffix}",
            "status": "running",
            "max_concurrency": len(attempts),
            "title": "求职分析",
            "detail": f"准备执行 {len(attempts)} 个分析步骤",
            "tasks": [
                _task_event_payload(
                    attempt,
                    status=attempt.status,
                    child_run_id=attempt.child_run_id,
                    detail="等待执行",
                )
                for attempt in attempts
            ],
        }
        await self._record_agent_task_event("agent_task_group_created", payload)

    async def _emit_task_group_completed(
        self,
        state: MultiAgentCareerGraphState,
        results: dict[str, dict[str, Any]],
        *,
        task_keys: tuple[str, ...],
    ) -> None:
        statuses = [_result_status(results, key) for key in task_keys]
        status = (
            "completed"
            if statuses and all(item == GRAPH_TASK_STATUS_COMPLETED for item in statuses)
            else "partial_failed"
        )
        await self._record_agent_task_event(
            "agent_task_group_completed",
            {
                "task_group_id": f"{state['workflow_instance_id']}:analysis",
                "status": status,
                "title": "求职分析",
                "detail": "分析步骤已汇总" if status == "completed" else "部分分析步骤失败",
            },
        )

    async def _emit_agent_task_event(
        self,
        event_type: str,
        attempt: GraphAgentTaskAttemptRecord,
        *,
        state: MultiAgentCareerGraphState,
        status: str,
        child_run_id: str | None,
        detail: str,
    ) -> None:
        _ = state
        await self._record_agent_task_event(
            event_type,
            _task_event_payload(
                attempt,
                status=status,
                child_run_id=child_run_id,
                detail=detail,
            ),
        )

    async def _record_agent_task_event(self, event_type: str, payload: dict[str, Any]) -> None:
        bindings = _bindings()
        await cast(EventRecorder, self._event_recorder).record_async(
            bindings.context,
            event_type,
            payload,
            channel=bindings.channel,
        )

    async def _emit_node_failed(
        self,
        state: MultiAgentCareerGraphState,
        node_name: str,
        error: str,
    ) -> None:
        await self._emit_workflow_event(
            _bindings().context,
            "workflow_node_failed",
            {
                "workflow_instance_id": state.get("workflow_instance_id"),
                "thread_id": state.get("thread_id"),
                "node": node_name,
                "phase": state.get("phase"),
                "error": error[:500],
            },
            channel=_bindings().channel,
        )

    async def _result_from_graph_output(
        self,
        result: Any,
        *,
        context: RunContext,
        channel: EventChannel | None,
    ) -> WorkflowGraphRunResult:
        state = cast(dict[str, Any], result if isinstance(result, dict) else {})
        interrupt_payload = _interrupt_payload(state)
        if interrupt_payload is not None:
            record = await self._persist_workflow_state(
                context,
                state,
                status=WORKFLOW_STATUS_WAITING,
                pending_interrupt_payload=interrupt_payload,
            )
            if record is not None and record.pending_interrupt_payload is not None:
                interrupt_payload = record.pending_interrupt_payload
            await self._emit_workflow_event(
                context,
                "workflow_waiting_for_input",
                interrupt_payload,
                channel=channel,
            )
            output = AgentRunOutput(
                session_id=context.session_id,
                answer=_answer_for_interrupt(interrupt_payload),
                tool_calls=_tool_calls_from_state(state),
                memory_hits=[],
            )
            return WorkflowGraphRunResult(
                handled=True,
                output=output,
                status="interrupted",
                workflow_instance_id=_string(interrupt_payload.get("workflow_instance_id")),
                thread_id=_string(interrupt_payload.get("thread_id")),
                interrupt_payload=interrupt_payload,
                tool_calls=output.tool_calls,
            )
        answer = _string(state.get("answer")) or "workflow 已结束。"
        output = AgentRunOutput(
            session_id=context.session_id,
            answer=answer,
            tool_calls=_tool_calls_from_state(state),
            memory_hits=[],
        )
        status: Any = "failed" if state.get("phase") == _PHASE_FAILED else "completed"
        await self._persist_workflow_state(
            context,
            state,
            status=(
                WORKFLOW_STATUS_FAILED
                if status == "failed"
                else WORKFLOW_STATUS_CANCELLED
                if state.get("phase") == _PHASE_CANCELLED
                else WORKFLOW_STATUS_COMPLETED
            ),
            output_refs=state.get("outputs") if isinstance(state.get("outputs"), dict) else {},
            last_error=state.get("last_error") if isinstance(state.get("last_error"), dict) else None,
        )
        return WorkflowGraphRunResult(
            handled=True,
            output=output,
            status=status,
            workflow_instance_id=_string(state.get("workflow_instance_id")),
            thread_id=_string(state.get("thread_id")),
            tool_calls=output.tool_calls,
        )

    async def _persist_workflow_state(
        self,
        context: RunContext,
        state: dict[str, Any],
        *,
        status: str,
        pending_interrupt_payload: dict[str, Any] | None = None,
        output_refs: dict[str, Any] | None = None,
        last_error: dict[str, Any] | None = None,
    ) -> WorkflowInstanceRecord | None:
        if self._workflow_store is None:
            return None
        workflow_instance_id = _string(state.get("workflow_instance_id"))
        thread_id = _string(state.get("thread_id"))
        if workflow_instance_id is None or thread_id is None:
            return None
        snapshot = _json_safe_state(state)
        if pending_interrupt_payload is not None:
            snapshot["pending_question"] = pending_interrupt_payload
        return self._workflow_store.create_or_update(
            session_id=context.session_id,
            workflow_instance_id=workflow_instance_id,
            workflow_id=MULTI_AGENT_CAREER_WORKFLOW_ID,
            thread_id=thread_id,
            run_id=context.run_id,
            status=status,
            phase=_string(state.get("phase")) or _PHASE_STARTED,
            state_snapshot=snapshot,
            pending_interrupt_payload=pending_interrupt_payload,
            output_refs=output_refs,
            last_error=last_error,
        )

    async def _emit_workflow_event(
        self,
        context: RunContext,
        event_type: str,
        payload: dict[str, Any],
        *,
        channel: EventChannel | None,
    ) -> None:
        await cast(EventRecorder, self._event_recorder).record_async(
            context,
            event_type,
            payload,
            channel=None,
        )
        if channel is not None:
            await channel.emit(event_type, payload)


def _bindings() -> _ExecutionBindings:
    bindings = _CURRENT_BINDINGS.get()
    if bindings is None:
        raise ValidationError("workflow execution bindings are missing.")
    return bindings


def _workflow_instance_id(value: str | None) -> str:
    if value is None:
        return f"wf_{uuid4().hex[:12]}"
    normalized = value.strip()
    if not normalized:
        raise ValidationError("workflow_instance_id must be non-empty.")
    return normalized


def _route_after_input_resolution(state: MultiAgentCareerGraphState) -> str:
    return "confirm" if state.get("phase") == _PHASE_INPUT_CONFIRMATION else "prepare"


def _route_after_input_preparation(state: MultiAgentCareerGraphState) -> str:
    return "confirm" if state.get("phase") == _PHASE_INPUT_CONFIRMATION else "parallel"


def _dispatch_parallel_tasks(state: MultiAgentCareerGraphState) -> list[Send] | str:
    task_keys = state.get("retry_task_keys", [])
    if not task_keys:
        return "join_analysis"
    return [
        Send("run_parallel_task", {**dict(state), "_task_key": task_key})
        for task_key in task_keys
    ]


def _route_after_parallel_join(state: MultiAgentCareerGraphState) -> str:
    return "retry" if state.get("failed_task_keys") else "fit"


def _route_after_task_review(state: MultiAgentCareerGraphState) -> str:
    return "retry" if state.get("failed_task_keys") else "project"


def _route_after_task_failure_review(state: MultiAgentCareerGraphState) -> str:
    return "final" if state.get("phase") == _PHASE_CANCELLED else "retry"


def _dispatch_retry_tasks(state: MultiAgentCareerGraphState) -> list[Send] | str:
    task_keys = state.get("retry_task_keys", [])
    if not task_keys:
        return "join_retry"
    return [
        Send("run_retry_task", {**dict(state), "_task_key": task_key})
        for task_key in task_keys
    ]


def _route_after_retry_join(state: MultiAgentCareerGraphState) -> str:
    if state.get("failed_task_keys"):
        return "retry"
    if state.get("phase") == _PHASE_FIT_ANALYSIS:
        return "fit"
    return "project"


def _route_after_application_write(state: MultiAgentCareerGraphState) -> str:
    return "retry" if state.get("phase") == _PHASE_WRITE_RETRY else "final"


def _route_after_write_retry(state: MultiAgentCareerGraphState) -> str:
    return "final" if state.get("phase") == _PHASE_CANCELLED else "retry"


def _required_task_key(state: MultiAgentCareerGraphState) -> str:
    value = state.get("_task_key")
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("dispatched graph task is missing _task_key.")
    CAREER_INTAKE_TASK_GRAPH.task(value)
    return value


def _artifact_candidates(
    repository: SessionRepository,
    session_id: str,
    artifacts: list[SessionArtifact],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for artifact in artifacts:
        try:
            sample = repository.read_session_artifact_text(session_id, artifact.artifact_id)[:2400]
        except Exception:  # noqa: BLE001
            sample = ""
        resume_score = _marker_score(f"{artifact.title}\n{artifact.description or ''}\n{sample}", _RESUME_MARKERS)
        jd_score = _marker_score(f"{artifact.title}\n{artifact.description or ''}\n{sample}", _JD_MARKERS)
        role_hint = "resume" if resume_score > jd_score else "jd" if jd_score > resume_score else "unknown"
        output.append(
            {
                "artifact_id": artifact.artifact_id,
                "title": artifact.title,
                "description": artifact.description or "",
                "role_hint": role_hint,
                "resume_score": resume_score,
                "jd_score": jd_score,
            }
        )
    return output


def _auto_select_inputs(
    *,
    user_goal: str,
    candidates: list[dict[str, Any]],
    active_ids: list[str],
) -> tuple[str | None, str | None]:
    by_id = {
        str(item.get("artifact_id")): item
        for item in candidates
        if isinstance(item.get("artifact_id"), str)
    }
    explicit_ids = [item for item in _ARTIFACT_ID_PATTERN.findall(user_goal) if item in by_id]
    preferred_ids = explicit_ids or [item for item in active_ids if item in by_id]
    pool = [by_id[item] for item in preferred_ids] if preferred_ids else candidates
    resumes = sorted(pool, key=lambda item: int(item.get("resume_score") or 0), reverse=True)
    jobs = sorted(pool, key=lambda item: int(item.get("jd_score") or 0), reverse=True)
    resume = resumes[0] if resumes and int(resumes[0].get("resume_score") or 0) > 0 else None
    jd = jobs[0] if jobs and int(jobs[0].get("jd_score") or 0) > 0 else None
    resume_id = _string(resume.get("artifact_id")) if resume else None
    jd_id = _string(jd.get("artifact_id")) if jd else None
    if resume_id and jd_id and resume_id != jd_id:
        return resume_id, jd_id
    return None, None


def _marker_score(text: str, markers: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for marker in markers if marker in lowered)


def _parse_input_confirmation(
    answer: Any,
    candidates: list[dict[str, Any]],
) -> tuple[str, str]:
    if not isinstance(answer, dict):
        raise ValidationError("career input confirmation payload must be an object.")
    valid_ids = {
        str(item.get("artifact_id"))
        for item in candidates
        if isinstance(item.get("artifact_id"), str)
    }
    resume_id = _required_string(answer.get("resume_artifact_id"), "resume_artifact_id")
    jd_id = _required_string(answer.get("jd_artifact_id"), "jd_artifact_id")
    if resume_id == jd_id:
        raise ValidationError("resume_artifact_id and jd_artifact_id must be different.")
    if resume_id not in valid_ids or jd_id not in valid_ids:
        raise ValidationError("selected artifacts are not available in this workflow.")
    return resume_id, jd_id


def _parse_task_retry_action(answer: Any) -> str:
    if not isinstance(answer, dict):
        raise ValidationError("workflow task retry payload must be an object.")
    action = (_string(answer.get("action")) or "").lower()
    if action not in {"retry_failed", "cancel"}:
        raise ValidationError("workflow task retry action must be retry_failed/cancel.")
    return action


def _parse_project_confirmation(
    answer: Any,
    current_preview: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if not isinstance(answer, dict):
        raise ValidationError("career project confirmation payload must be an object.")
    action = (_string(answer.get("action")) or "approve").lower()
    if action not in {"approve", "edit_project_fields", "cancel"}:
        raise ValidationError("project confirmation action must be approve/edit_project_fields/cancel.")
    if action == "cancel":
        return action, current_preview
    preview = dict(current_preview)
    edited = answer.get("edited_project_fields")
    if isinstance(edited, dict):
        for key in ("company", "position", "location", "stage", "priority", "summary"):
            value = edited.get(key)
            if isinstance(value, str):
                preview[key] = value.strip()
    return action, preview


def _normalized_task_results(state: MultiAgentCareerGraphState) -> dict[str, dict[str, Any]]:
    output = {
        key: dict(value)
        for key, value in state.get("task_results", {}).items()
        if isinstance(key, str) and isinstance(value, dict)
    }
    for update in state.get("task_updates", []):
        if not isinstance(update, dict):
            continue
        task_key = _string(update.get("task_key"))
        attempt = update.get("attempt")
        if task_key is None or not isinstance(attempt, int):
            continue
        previous = output.get(task_key)
        if previous is None or int(previous.get("attempt") or 0) <= attempt:
            output[task_key] = dict(update)
    return output


def _attempt_result(record: GraphAgentTaskAttemptRecord) -> dict[str, Any]:
    return {
        "task_key": record.task_key,
        "attempt_id": record.attempt_id,
        "attempt": record.attempt,
        "target_agent_id": record.target_agent_id,
        "status": record.status,
        "child_run_id": record.child_run_id,
        "summary": _short_text(record.summary, 1000),
        "error": _short_text(record.error, 1000),
        "output_artifact_refs": list(record.output_artifact_refs),
        "product_refs": list(record.product_refs),
    }


def _task_status(state: MultiAgentCareerGraphState, task_key: str) -> str | None:
    return _result_status(_normalized_task_results(state), task_key)


def _result_status(results: dict[str, dict[str, Any]], task_key: str) -> str | None:
    value = results.get(task_key, {}).get("status")
    return value if isinstance(value, str) else None


def _task_attempts(results: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {
        key: int(value["attempt"])
        for key, value in results.items()
        if isinstance(value.get("attempt"), int)
    }


def _result_refs(
    results: dict[str, dict[str, Any]],
    task_key: str,
    field_name: str,
) -> list[str]:
    value = results.get(task_key, {}).get(field_name)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _required_output_ref(
    results: dict[str, dict[str, Any]],
    task_key: str,
    prefix: str,
) -> str:
    ref = next(
        (item for item in _result_refs(results, task_key, "product_refs") if item.startswith(prefix)),
        None,
    )
    if ref is None:
        raise ValidationError(f"{task_key} is missing required output ref with prefix={prefix}.")
    return ref


def _career_profile_id(
    results: dict[str, dict[str, Any]],
    career_store: CareerProductStore | None,
) -> str:
    ref = next(
        (
            item
            for item in _result_refs(results, "resume_analysis", "product_refs")
            if item.startswith("career_profile_")
        ),
        None,
    )
    if ref is not None:
        return ref
    if career_store is not None:
        profiles = career_store.list_career_profiles()
        if profiles:
            default = next(
                (item for item in profiles if item.career_profile_id == "career_profile_default"),
                profiles[0],
            )
            return default.career_profile_id
    return "career_profile_default"


def _task_event_payload(
    attempt: GraphAgentTaskAttemptRecord,
    *,
    status: str,
    child_run_id: str | None,
    detail: str,
) -> dict[str, Any]:
    return {
        "task_group_id": f"{attempt.workflow_instance_id}:analysis",
        "task_id": attempt.attempt_id,
        "task_key": attempt.task_key,
        "attempt": attempt.attempt,
        "target_agent_id": attempt.target_agent_id,
        "status": status,
        "title": _TASK_LABELS.get(attempt.task_key, "执行分析"),
        "detail": detail[:300],
        "artifact_refs": list(attempt.artifact_refs),
        "output_artifact_refs": list(attempt.output_artifact_refs),
        "product_refs": list(attempt.product_refs),
        "child_run_id": child_run_id,
    }


def _public_task_results(results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "task_key": key,
            "title": _TASK_LABELS.get(key, key),
            "status": value.get("status"),
            "summary": _short_text(value.get("summary"), 240),
            "product_refs": value.get("product_refs") or [],
            "output_artifact_refs": value.get("output_artifact_refs") or [],
        }
        for key, value in results.items()
    ]


def _short_text(value: Any, limit: int) -> str | None:
    text = _string(value)
    if text is None or len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _answer_for_interrupt(payload: dict[str, Any]) -> str:
    interrupt_type = _string(payload.get("type"))
    if interrupt_type == "career_input_confirmation":
        return "需要先确认本次使用的简历和目标岗位 JD。"
    if interrupt_type == "workflow_task_retry":
        return "部分分析步骤失败，已暂停 workflow 等待你确认是否重试。"
    if interrupt_type == "career_project_confirmation":
        return "分析已经完成，确认后再创建求职项目。"
    if interrupt_type == "workflow_write_retry":
        return "求职项目创建失败，已暂停 workflow 等待你重试或取消。"
    return _string(payload.get("question")) or "workflow 正在等待你的确认。"


def _application_id(workflow_instance_id: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", workflow_instance_id).strip("_")
    return f"application_{stem or uuid4().hex[:12]}"


def _append_tool_call(
    state: MultiAgentCareerGraphState,
    tool_name: str,
    arguments: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        *[item for item in state.get("tool_calls", []) if isinstance(item, dict)],
        {"name": tool_name, "arguments": arguments},
    ]


def _tool_calls_from_state(state: dict[str, Any]) -> list[ToolCall]:
    output: list[ToolCall] = []
    for item in state.get("tool_calls", []):
        if not isinstance(item, dict):
            continue
        name = _string(item.get("name"))
        arguments = item.get("arguments")
        if name is not None and isinstance(arguments, dict):
            output.append(ToolCall(name=name, arguments=arguments))
    return output


def _interrupt_payload(state: dict[str, Any]) -> dict[str, Any] | None:
    raw = state.get("__interrupt__")
    if not isinstance(raw, list) or not raw:
        return None
    value = getattr(raw[0], "value", None)
    return value if isinstance(value, dict) else None


def _json_safe_state(state: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in state.items():
        if key == "__interrupt__":
            continue
        try:
            json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            continue
        output[key] = value
    return output


def _json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _dedupe_strings(values: list[object]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = _string(raw)
        if value is None or value in seen:
            continue
        output.append(value)
        seen.add(value)
    return output
