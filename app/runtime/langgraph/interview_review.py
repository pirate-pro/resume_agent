"""Interactive interview-review workflow implemented with LangGraph."""

from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy, TimeoutPolicy, interrupt

from app.core.errors import ValidationError
from app.domain.models import AgentRunInput, AgentRunOutput, RunContext, ToolCall, ToolExecutionResult
from app.domain.protocols import ChatModelClient, TokenUsage
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
from app.runtime.context_compaction.text_utils import estimate_tokens_from_object, estimate_tokens_from_text
from app.runtime.event_channel import EventChannel
from app.runtime.event_recorder import EventRecorder
from app.runtime.langgraph.checkpointer import WorkflowCheckpointerHandle
from app.runtime.langgraph.types import (
    INTERVIEW_REVIEW_WORKFLOW_ID,
    InterviewReviewGraphState,
    WorkflowGraphRunResult,
    WorkflowResumeRequest,
)
from app.runtime.langgraph.write_retry import (
    WRITE_RETRY_INTERRUPT_TYPE,
    failed_write_node,
    parse_write_retry_action,
    write_failure_update,
    write_retry_interrupt_payload,
)
from app.runtime.workflow.action_payloads import ActionPayloadBuilder

__all__ = ["InterviewReviewWorkflowRunner"]

INTERVIEW_REVIEW_ACTION_CONTRACT_ID = "interview.review.update.v1"
_PHASE_STARTED = "started"
_PHASE_SCOPE_SELECTION = "scope_selection"
_PHASE_SCOPE_CONFIRMED = "scope_confirmed"
_PHASE_CONTEXT_PACK = "context_pack"
_PHASE_DRAFT = "draft"
_PHASE_REVIEW = "review"
_PHASE_REVIEW_CONFIRMED = "review_confirmed"
_PHASE_NOTE_WRITTEN = "note_written"
_PHASE_APPLICATION_MERGED = "application_merged"
_PHASE_WRITE_RETRY = "write_retry"
_PHASE_COMPLETED = "completed"
_PHASE_CANCELLED = "cancelled"
_PHASE_FAILED = "failed"
_DEFAULT_UPDATE_FIELDS = ["stage", "risks", "next_actions", "notes"]
_ALLOWED_UPDATE_FIELDS = {"stage", "summary", "risks", "next_actions", "notes"}
_SUPPORTED_NOTE_SOURCE_TYPES = {
    "career_application",
    "resume_profile",
    "career_profile",
    "jd_analysis",
    "job_fit_report",
    "resume_version",
    "artifact",
}
_RETRIEVAL_TO_NOTE_SOURCE_TYPE = {
    "session_artifact": "artifact",
    "career_application": "career_application",
    "resume_profile": "resume_profile",
    "career_profile": "career_profile",
    "jd_analysis": "jd_analysis",
    "job_fit_report": "job_fit_report",
    "resume_version": "resume_version",
}
_FORBIDDEN_WRITE_TOOLS = [
    "note_create",
    "note_append",
    "career_application_merge",
    "learning_task_create",
    "memory_write",
    "delegate_agents",
    "career_resume_version_create",
    "career_jd_analysis_save",
    "career_job_fit_report_save",
    "career_profile_merge",
]


@dataclass(frozen=True, slots=True)
class _ExecutionBindings:
    context: RunContext
    channel: EventChannel | None


_CURRENT_BINDINGS: ContextVar[_ExecutionBindings | None] = ContextVar(
    "interview_review_workflow_bindings",
    default=None,
)


class WorkflowTransientError(Exception):
    """Retryable workflow node failure."""


class InterviewReviewWorkflowRunner:
    """Run the interactive `interview.review.update.interactive.v1` graph."""

    workflow_id = INTERVIEW_REVIEW_WORKFLOW_ID

    def __init__(
        self,
        *,
        tool_gateway: ToolGateway,
        model_client: ChatModelClient,
        event_recorder: EventRecorder,
        workflow_store: WorkflowInstanceStore | None = None,
        checkpoint_backend: str = "memory",
        checkpoint_path: Path | None = None,
        node_timeout_seconds: float = 90.0,
        draft_node_timeout_seconds: float | None = None,
        node_retry_attempts: int = 3,
    ) -> None:
        normalized_backend = checkpoint_backend.strip().lower()
        if normalized_backend not in {"memory", "sqlite"}:
            raise ValidationError("checkpoint_backend must be memory/sqlite.")
        if node_timeout_seconds <= 0:
            raise ValidationError("node_timeout_seconds must be positive.")
        if draft_node_timeout_seconds is not None and draft_node_timeout_seconds <= 0:
            raise ValidationError("draft_node_timeout_seconds must be positive.")
        if node_retry_attempts <= 0:
            raise ValidationError("node_retry_attempts must be positive.")
        self._tool_gateway = tool_gateway
        self._model_client = model_client
        self._event_recorder = event_recorder
        self._workflow_store = workflow_store
        self._action_payload_builder = ActionPayloadBuilder()
        self._checkpoint_backend = normalized_backend
        self._checkpoint_path = checkpoint_path
        self._memory_checkpointer = InMemorySaver() if normalized_backend == "memory" else None
        self._node_timeout_seconds = node_timeout_seconds
        self._draft_node_timeout_seconds = draft_node_timeout_seconds or node_timeout_seconds
        self._node_retry_attempts = node_retry_attempts

    def initial_state_for(
        self,
        run_input: AgentRunInput,
        *,
        workflow_instance_id: str | None = None,
    ) -> InterviewReviewGraphState:
        workflow_id = _workflow_instance_id(workflow_instance_id)
        thread_id = f"{run_input.session_id}:{workflow_id}"
        return InterviewReviewGraphState(
            session_id=run_input.session_id,
            run_id=run_input.context.run_id,
            workflow_instance_id=workflow_id,
            thread_id=thread_id,
            contract_id=INTERVIEW_REVIEW_ACTION_CONTRACT_ID,
            user_goal=run_input.user_message,
            phase=_PHASE_STARTED,
            known_refs={},
            retrieval_candidates=[],
            application_candidates=[],
            selected_source_refs=[],
            selected_application_id=None,
            user_supplement=None,
            context_pack=None,
            review_facts={},
            note_draft=None,
            application_update_preview=None,
            pending_question=None,
            retry_counters={},
            last_error=None,
            outputs={},
            update_fields=[],
            save_note=True,
            update_application=True,
            tool_calls=[],
            answer="",
        )

    async def run_stream(
        self,
        run_input: AgentRunInput,
        *,
        channel: EventChannel | None = None,
    ) -> WorkflowGraphRunResult:
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
                    "contract_id": INTERVIEW_REVIEW_WORKFLOW_ID,
                    "action_contract_id": INTERVIEW_REVIEW_ACTION_CONTRACT_ID,
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

    def _checkpointer_handle(self) -> WorkflowCheckpointerHandle:
        return WorkflowCheckpointerHandle(
            backend=self._checkpoint_backend,
            checkpoint_path=self._checkpoint_path,
            memory_checkpointer=self._memory_checkpointer,
        )

    async def _has_checkpoint(self, checkpointer: Any, thread_id: str) -> bool:
        return await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}}) is not None

    def _build_graph(
        self,
        checkpointer: Any,
    ) -> Any:
        retry = RetryPolicy(max_attempts=self._node_retry_attempts)
        timeout = TimeoutPolicy(run_timeout=self._node_timeout_seconds)
        draft_timeout = TimeoutPolicy(run_timeout=self._draft_node_timeout_seconds)
        builder = StateGraph(InterviewReviewGraphState)
        builder.add_node("init_interview_review", self._init_interview_review)
        builder.add_node("retrieval_search", self._retrieval_search, retry_policy=retry, timeout=timeout)
        builder.add_node("review_scope", self._review_scope)
        builder.add_node("retrieval_context_pack", self._retrieval_context_pack, retry_policy=retry, timeout=timeout)
        builder.add_node("draft_review_update", self._draft_review_update, retry_policy=retry, timeout=draft_timeout)
        builder.add_node("review_confirmation", self._review_confirmation)
        builder.add_node("write_review_note", self._write_review_note, timeout=timeout)
        builder.add_node("merge_career_application", self._merge_career_application, timeout=timeout)
        builder.add_node("write_retry", self._write_retry)
        builder.add_node("final_answer", self._final_answer)
        builder.add_edge(START, "init_interview_review")
        builder.add_edge("init_interview_review", "retrieval_search")
        builder.add_edge("retrieval_search", "review_scope")
        builder.add_edge("review_scope", "retrieval_context_pack")
        builder.add_edge("retrieval_context_pack", "draft_review_update")
        builder.add_edge("draft_review_update", "review_confirmation")
        builder.add_edge("review_confirmation", "write_review_note")
        builder.add_conditional_edges(
            "write_review_note",
            _route_after_review_note_write,
            {
                "retry": "write_retry",
                "next": "merge_career_application",
            },
        )
        builder.add_conditional_edges(
            "merge_career_application",
            _route_after_application_merge,
            {
                "retry": "write_retry",
                "final": "final_answer",
            },
        )
        builder.add_conditional_edges(
            "write_retry",
            _route_after_write_retry,
            {
                "note": "write_review_note",
                "application": "merge_career_application",
                "final": "final_answer",
            },
        )
        builder.add_edge("final_answer", END)
        return builder.compile(checkpointer=checkpointer)

    async def _init_interview_review(self, state: InterviewReviewGraphState) -> dict[str, Any]:
        await self._emit_node_event(state, "init_interview_review", "workflow_node_succeeded")
        if state.get("phase") != _PHASE_STARTED:
            return {}
        return {"phase": _PHASE_STARTED}

    async def _retrieval_search(self, state: InterviewReviewGraphState) -> dict[str, Any]:
        if state.get("retrieval_candidates"):
            return {}
        await self._emit_node_event(state, "retrieval_search", "workflow_node_started")
        args = {
            "query": _non_empty(state.get("user_goal"), "面试复盘 更新求职项目"),
            "source_types": ["career", "notes", "knowledge", "learning", "artifacts"],
            "top_k": 8,
            "max_chars": 12000,
        }
        result = await self._execute_tool(
            "retrieval_search",
            args,
            state=state,
            missing_output="retrieval_search",
        )
        if not result.success:
            await self._emit_node_failed(state, "retrieval_search", result.content)
            raise WorkflowTransientError(result.content)
        payload = _json_object(result.content)
        raw_hits = payload.get("hits")
        hits = raw_hits if isinstance(raw_hits, list) else []
        candidates = [_candidate_from_hit(item) for item in hits if isinstance(item, dict)]
        application_candidates = _application_candidates(candidates)
        await self._emit_node_event(
            state,
            "retrieval_search",
            "workflow_node_succeeded",
            {
                "candidate_count": len(candidates),
                "application_candidate_count": len(application_candidates),
            },
        )
        return {
            "phase": _PHASE_SCOPE_SELECTION,
            "retrieval_candidates": candidates,
            "application_candidates": application_candidates,
            "tool_calls": _append_tool_call(state, "retrieval_search", args),
        }

    async def _review_scope(self, state: InterviewReviewGraphState) -> dict[str, Any]:
        if state.get("outputs", {}).get("scope_confirmed") is True:
            return {}
        payload = {
            "type": "interview_review_scope",
            "workflow_instance_id": state["workflow_instance_id"],
            "thread_id": state["thread_id"],
            "question": "确认要更新的面试复盘范围。",
            "application_candidates": state.get("application_candidates", []),
            "source_candidates": state.get("retrieval_candidates", []),
            "default_update_fields": list(_DEFAULT_UPDATE_FIELDS),
            "allow_save_note": True,
            "allow_update_application": True,
            "allow_user_supplement": True,
        }
        answer = interrupt(payload)
        parsed = _parse_scope_answer(answer, state.get("application_candidates", []))
        selected_application_id = cast(str | None, parsed["selected_application_id"])
        selected_refs = _selected_refs_for_scope(
            application_id=selected_application_id,
            candidates=state.get("retrieval_candidates", []),
        )
        return {
            "phase": _PHASE_SCOPE_CONFIRMED,
            "selected_application_id": selected_application_id,
            "selected_source_refs": selected_refs,
            "user_supplement": parsed["user_supplement"],
            "save_note": parsed["save_note"],
            "update_application": parsed["update_application"],
            "update_fields": parsed["update_fields"],
            "outputs": {"scope_confirmed": True},
            "pending_question": None,
        }

    async def _retrieval_context_pack(self, state: InterviewReviewGraphState) -> dict[str, Any]:
        if state.get("context_pack") is not None:
            return {}
        await self._emit_node_event(state, "retrieval_context_pack", "workflow_node_started")
        args = {
            "query": _context_pack_query(state),
            "source_types": _context_pack_source_types(state),
            "top_k": 8,
            "max_chars": 16000,
        }
        result = await self._execute_tool(
            "retrieval_context_pack",
            args,
            state=state,
            missing_output="retrieval_context_pack",
        )
        if not result.success:
            await self._emit_node_failed(state, "retrieval_context_pack", result.content)
            raise WorkflowTransientError(result.content)
        payload = _json_object(result.content)
        await self._emit_node_event(
            state,
            "retrieval_context_pack",
            "workflow_node_succeeded",
            {"context_char_count": payload.get("context_char_count")},
        )
        return {
            "phase": _PHASE_DRAFT,
            "context_pack": payload,
            "tool_calls": _append_tool_call(state, "retrieval_context_pack", args),
        }

    async def _draft_review_update(self, state: InterviewReviewGraphState) -> dict[str, Any]:
        if state.get("note_draft") is not None and state.get("application_update_preview") is not None:
            return {}
        await self._emit_node_event(state, "draft_review_update", "workflow_node_started")
        draft, usage_payload = await asyncio.to_thread(self._generate_review_draft, state)
        await self._event_recorder.record_async(
            _bindings().context,
            "llm_usage",
            usage_payload,
            channel=_bindings().channel,
        )
        note_draft = _normalize_note_draft(draft.get("note_draft"), state)
        update_preview = _normalize_application_update_preview(draft.get("application_update_preview"), state)
        await self._emit_node_event(state, "draft_review_update", "workflow_node_succeeded")
        return {
            "phase": _PHASE_REVIEW,
            "note_draft": note_draft,
            "application_update_preview": update_preview,
        }

    async def _review_confirmation(self, state: InterviewReviewGraphState) -> dict[str, Any]:
        if state.get("outputs", {}).get("review_confirmed") is True:
            return {}
        payload = {
            "type": "interview_review_confirmation",
            "workflow_instance_id": state["workflow_instance_id"],
            "thread_id": state["thread_id"],
            "question": "确认面试复盘草稿和项目更新预览后，我再执行写入。",
            "note_draft": state.get("note_draft") or {},
            "application_update_preview": state.get("application_update_preview") or {},
            "source_refs": state.get("selected_source_refs", []),
            "actions": ["approve", "edit", "regenerate", "cancel"],
        }
        answer = interrupt(payload)
        action, note_draft, update_preview = _parse_confirmation_answer(
            answer,
            note_draft=state.get("note_draft") or {},
            application_update_preview=state.get("application_update_preview") or {},
            state=state,
        )
        if action == "cancel":
            return {
                "phase": _PHASE_CANCELLED,
                "outputs": {"scope_confirmed": True, "review_confirmed": True, "cancelled": True},
                "answer": "已取消面试复盘写入；没有创建 Note，也没有更新求职项目。",
                "pending_question": None,
            }
        return {
            "phase": _PHASE_REVIEW_CONFIRMED,
            "note_draft": note_draft,
            "application_update_preview": update_preview,
            "outputs": {"scope_confirmed": True, "review_confirmed": True},
            "pending_question": None,
        }

    async def _write_review_note(self, state: InterviewReviewGraphState) -> dict[str, Any]:
        if state.get("phase") == _PHASE_CANCELLED:
            return {}
        outputs = _outputs(state)
        if _string(outputs.get("note_id")) is not None:
            return {}
        if state.get("save_note") is not True:
            return {
                "phase": _PHASE_NOTE_WRITTEN,
                "outputs": _merged_outputs(state, {"note_skipped": True}),
            }
        await self._emit_node_event(state, "write_review_note", "workflow_node_started")
        args = _note_create_args(state)
        result = await self._execute_write_tool(
            "note_create",
            args,
            state=state,
            missing_output="note",
        )
        if not result.success:
            await self._emit_node_failed(state, "write_review_note", result.content)
            return write_failure_update(
                dict(state),
                failed_node="write_review_note",
                error=result.content,
                retry_phase=_PHASE_WRITE_RETRY,
            )
        payload = _json_object(result.content)
        note_id = _string(payload.get("record_id")) or _string(payload.get("note_id")) or _note_id(state)
        await self._emit_node_event(
            state,
            "write_review_note",
            "workflow_node_succeeded",
            {"note_id": note_id},
        )
        return {
            "phase": _PHASE_NOTE_WRITTEN,
            "last_error": None,
            "known_refs": _known_refs_with(state, {"note_id": note_id, "record_id": note_id}),
            "outputs": _merged_outputs(
                state,
                {
                    "note_id": note_id,
                    "note_title": args.get("title"),
                },
            ),
            "tool_calls": _append_tool_call(state, "note_create", args),
        }

    async def _merge_career_application(self, state: InterviewReviewGraphState) -> dict[str, Any]:
        if state.get("phase") == _PHASE_CANCELLED:
            return {}
        outputs = _outputs(state)
        if _string(outputs.get("application_id")) is not None:
            return {}
        if state.get("update_application") is not True:
            return {"phase": _PHASE_COMPLETED, "outputs": _merged_outputs(state, {"application_update_skipped": True})}
        note_id = _string(outputs.get("note_id"))
        if note_id is None:
            return {
                "phase": _PHASE_FAILED,
                "last_error": {"node": "merge_career_application", "error": "missing note_id before merge"},
                "answer": "面试复盘 Note 尚未保存，已停止项目更新。",
            }
        args = self._career_application_merge_args(state, note_id=note_id)
        if args is None:
            return {
                "phase": _PHASE_FAILED,
                "last_error": {"node": "merge_career_application", "error": "missing merge arguments"},
                "answer": "缺少求职项目或 Note 引用，已停止项目更新。",
            }
        await self._emit_node_event(state, "merge_career_application", "workflow_node_started")
        result = await self._execute_write_tool(
            "career_application_merge",
            args,
            state=state,
            missing_output="career_application_update",
        )
        if not result.success:
            await self._emit_node_failed(state, "merge_career_application", result.content)
            return write_failure_update(
                dict(state),
                failed_node="merge_career_application",
                error=result.content,
                retry_phase=_PHASE_WRITE_RETRY,
            )
        payload = _json_object(result.content)
        application_id = _string(payload.get("record_id")) or _string(payload.get("application_id")) or _string(
            args.get("application_id")
        )
        await self._emit_node_event(
            state,
            "merge_career_application",
            "workflow_node_succeeded",
            {"application_id": application_id},
        )
        return {
            "phase": _PHASE_APPLICATION_MERGED,
            "last_error": None,
            "known_refs": _known_refs_with(state, {"application_id": application_id}),
            "outputs": _merged_outputs(state, {"application_id": application_id}),
            "tool_calls": _append_tool_call(state, "career_application_merge", args),
        }

    async def _write_retry(self, state: InterviewReviewGraphState) -> dict[str, Any]:
        failed_node = failed_write_node(dict(state))
        is_application_merge = failed_node == "merge_career_application"
        payload = write_retry_interrupt_payload(
            dict(state),
            question=(
                "求职项目更新失败。面试复盘 Note 已保存，你可以重试项目更新，或保留 Note 并取消更新。"
                if is_application_merge
                else "面试复盘 Note 保存失败。你可以重试保存，或取消本次写入。"
            ),
            operation_label="更新求职项目" if is_application_merge else "保存面试复盘 Note",
        )
        answer = interrupt(payload)
        action = parse_write_retry_action(answer)
        if action == "cancel":
            outputs = _outputs(state)
            note_id = _string(outputs.get("note_id"))
            return {
                "phase": _PHASE_CANCELLED,
                "outputs": _merged_outputs(
                    state,
                    {
                        "cancelled": True,
                        "application_update_cancelled": is_application_merge,
                    },
                ),
                "answer": (
                    f"面试复盘 Note 已保存（note_id: {note_id}），已取消更新求职项目。"
                    if is_application_merge and note_id is not None
                    else "已取消面试复盘写入。"
                ),
                "pending_question": None,
            }
        return {
            "phase": _PHASE_NOTE_WRITTEN if is_application_merge else _PHASE_REVIEW_CONFIRMED,
            "pending_question": None,
        }

    async def _final_answer(self, state: InterviewReviewGraphState) -> dict[str, Any]:
        outputs = _outputs(state)
        if state.get("phase") == _PHASE_CANCELLED:
            return {"answer": _non_empty(state.get("answer"), "已取消面试复盘写入。")}
        if state.get("phase") == _PHASE_FAILED:
            return {"answer": _non_empty(state.get("answer"), "面试复盘 workflow 失败，已停止写入。")}
        note_id = _string(outputs.get("note_id"))
        application_id = _string(outputs.get("application_id")) or _string(state.get("selected_application_id"))
        raw_note = state.get("note_draft")
        note_draft = raw_note if isinstance(raw_note, dict) else {}
        title = _string(outputs.get("note_title")) or _string(note_draft.get("title")) or "面试复盘"
        await self._emit_workflow_event(
            _bindings().context,
            "workflow_completed",
            {
                "workflow_instance_id": state["workflow_instance_id"],
                "thread_id": state["thread_id"],
                "note_id": note_id,
                "application_id": application_id,
                "title": title,
            },
            channel=_bindings().channel,
        )
        return {
            "phase": _PHASE_COMPLETED,
            "answer": (
                f"已保存面试复盘：{title}\n\n"
                f"note_id: {note_id or '未创建'}\n"
                f"application_id: {application_id or '未更新'}"
            ),
            "outputs": _merged_outputs(state, {"completed": True}),
        }

    def _generate_review_draft(self, state: InterviewReviewGraphState) -> tuple[dict[str, Any], dict[str, Any]]:
        system_prompt = (
            "你是求职面试复盘助手。只输出 JSON 对象，字段为 note_draft 和 application_update_preview。"
            "note_draft 包含 title, body_markdown, summary, tags。"
            "application_update_preview 只能包含 stage, summary, next_actions, risks, notes。"
            "不要调用工具，不要创建学习任务，不要输出 Markdown 代码块。"
        )
        messages = [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "goal": state.get("user_goal"),
                        "selected_application_id": state.get("selected_application_id"),
                        "selected_sources": state.get("selected_source_refs", []),
                        "user_supplement": state.get("user_supplement"),
                        "update_fields": state.get("update_fields", []),
                        "context_pack": state.get("context_pack"),
                    },
                    ensure_ascii=False,
                ),
            }
        ]
        response = self._model_client.generate(system_prompt=system_prompt, messages=messages, tools=[])
        parsed = _json_object_from_text(response.content)
        usage_payload = _langgraph_llm_usage_payload(
            system_prompt=system_prompt,
            messages=messages,
            content=response.content,
            reasoning_content=response.reasoning_content,
            usage=response.usage,
            model=response.model,
            model_client=self._model_client,
        )
        if parsed:
            return parsed, usage_payload
        return _fallback_review_draft(state), usage_payload

    def _career_application_merge_args(self, state: InterviewReviewGraphState, *, note_id: str) -> dict[str, Any] | None:
        plan = {"known_refs": _known_refs_for_merge(state, note_id=note_id)}
        base_args = self._action_payload_builder.interview_review_application_merge_arguments(plan)
        if base_args is None:
            return None
        preview = state.get("application_update_preview")
        if isinstance(preview, dict):
            base_args["updates"] = _merge_updates(base_args.get("updates"), preview, note_id=note_id)
        return base_args

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        state: InterviewReviewGraphState,
        missing_output: str,
    ) -> ToolExecutionResult:
        bindings = _bindings()
        tool_call = ToolCall(name=tool_name, arguments=arguments)
        await self._event_recorder.record_async(
            bindings.context,
            "tool_call",
            {"name": tool_call.name, "arguments": tool_call.arguments, "tool_call_id": tool_call.tool_call_id},
            channel=bindings.channel,
        )
        gateway_result = await self._tool_gateway.execute_async(
            tool_call,
            bindings.context,
            pending_runtime_plan=_runtime_plan_for_tool(
                state=state,
                tool_name=tool_name,
                missing_output=missing_output,
            ),
        )
        result = gateway_result.result
        await self._event_recorder.record_async(
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
        if gateway_result.event_payload is not None:
            await self._event_recorder.record_async(
                bindings.context,
                "workflow_runtime_decision",
                gateway_result.event_payload,
                channel=bindings.channel,
            )
        return result

    async def _execute_write_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        state: InterviewReviewGraphState,
        missing_output: str,
    ) -> ToolExecutionResult:
        result: ToolExecutionResult | None = None
        for _ in range(self._node_retry_attempts):
            result = await self._execute_tool(
                tool_name,
                arguments,
                state=state,
                missing_output=missing_output,
            )
            if result.success:
                return result
        if result is None:
            raise ValidationError("write tool execution produced no result.")
        return result

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
            workflow_instance_id = _string(interrupt_payload.get("workflow_instance_id"))
            thread_id = _string(interrupt_payload.get("thread_id"))
            record = await self._persist_workflow_state(
                context,
                state,
                status=WORKFLOW_STATUS_WAITING,
                pending_interrupt_payload=interrupt_payload,
            )
            if record is not None and record.pending_interrupt_payload is not None:
                interrupt_payload = record.pending_interrupt_payload
            await self._emit_workflow_event(context, "workflow_waiting_for_input", interrupt_payload, channel=channel)
            answer = _answer_for_interrupt(interrupt_payload)
            output = AgentRunOutput(
                session_id=context.session_id,
                answer=answer,
                tool_calls=_tool_calls_from_state(state),
                memory_hits=[],
            )
            return WorkflowGraphRunResult(
                handled=True,
                output=output,
                status="interrupted",
                workflow_instance_id=workflow_instance_id,
                thread_id=thread_id,
                interrupt_payload=interrupt_payload,
                tool_calls=output.tool_calls,
            )
        answer = _non_empty(state.get("answer"), "interview review workflow 已结束。")
        output = AgentRunOutput(
            session_id=context.session_id,
            answer=answer,
            tool_calls=_tool_calls_from_state(state),
            memory_hits=[],
        )
        status: Any = _terminal_result_status(state)
        if status == "failed":
            await self._persist_workflow_state(
                context,
                state,
                status=WORKFLOW_STATUS_FAILED,
                last_error=state.get("last_error") if isinstance(state.get("last_error"), dict) else None,
            )
            await self._emit_workflow_event(
                context,
                "workflow_failed",
                {
                    "workflow_instance_id": state.get("workflow_instance_id"),
                    "thread_id": state.get("thread_id"),
                    "last_error": state.get("last_error"),
                },
                channel=channel,
            )
        else:
            await self._persist_workflow_state(
                context,
                state,
                status=_persisted_terminal_status(state),
                output_refs=state.get("outputs") if isinstance(state.get("outputs"), dict) else {},
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
        phase = _string(state.get("phase")) or _PHASE_STARTED
        if workflow_instance_id is None or thread_id is None:
            return None
        return self._workflow_store.create_or_update(
            session_id=context.session_id,
            workflow_instance_id=workflow_instance_id,
            workflow_id=INTERVIEW_REVIEW_WORKFLOW_ID,
            thread_id=thread_id,
            run_id=context.run_id,
            status=status,
            phase=phase,
            state_snapshot=_snapshot_for_persistence(state, pending_interrupt_payload=pending_interrupt_payload),
            pending_interrupt_payload=pending_interrupt_payload,
            output_refs=output_refs,
            last_error=last_error,
        )

    async def _emit_node_event(
        self,
        state: InterviewReviewGraphState,
        node_name: str,
        event_type: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        bindings = _bindings()
        payload = {
            "workflow_instance_id": state.get("workflow_instance_id"),
            "thread_id": state.get("thread_id"),
            "node": node_name,
            "phase": state.get("phase"),
        }
        if extra:
            payload.update(extra)
        await self._emit_workflow_event(bindings.context, event_type, payload, channel=bindings.channel)

    async def _emit_node_failed(self, state: InterviewReviewGraphState, node_name: str, error: str) -> None:
        await self._emit_node_event(state, node_name, "workflow_node_failed", {"error": error[:500]})

    async def _emit_workflow_event(
        self,
        context: RunContext,
        event_type: str,
        payload: dict[str, Any],
        *,
        channel: EventChannel | None,
    ) -> None:
        await self._event_recorder.record_async(context, event_type, payload, channel=None)
        if channel is not None:
            await channel.emit(event_type, payload)


def _workflow_instance_id(value: str | None) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"wf_{uuid4().hex[:12]}"


def _bindings() -> _ExecutionBindings:
    bindings = _CURRENT_BINDINGS.get()
    if bindings is None:
        raise ValidationError("workflow execution bindings are missing.")
    return bindings


def _json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_object_from_text(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return _json_object(text)


def _candidate_from_hit(hit: dict[str, Any]) -> dict[str, Any]:
    raw_source = hit.get("source")
    source = raw_source if isinstance(raw_source, dict) else {}
    source_type = _string(source.get("source_type")) or ""
    source_id = _string(source.get("source_id")) or ""
    return {
        "source_ref": {
            "source_type": source_type,
            "source_id": source_id,
            "source_session_id": _string(source.get("source_session_id")),
            "artifact_id": _string(source.get("artifact_id")),
        },
        "title": _string(hit.get("title")) or "未命名来源",
        "snippet": _string(hit.get("snippet")) or _string(hit.get("summary")) or "",
        "summary": _string(hit.get("summary")) or "",
        "stage": _string(hit.get("stage")),
        "score": hit.get("score") if isinstance(hit.get("score"), (int, float)) else None,
        "evidence_refs": hit.get("evidence_refs") if isinstance(hit.get("evidence_refs"), list) else [],
    }


def _application_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        raw_ref = candidate.get("source_ref")
        ref = raw_ref if isinstance(raw_ref, dict) else {}
        if _string(ref.get("source_type")) != "career_application":
            continue
        application_id = _string(ref.get("source_id"))
        if application_id is None or application_id in seen:
            continue
        output.append(
            {
                "application_id": application_id,
                "title": _string(candidate.get("title")) or application_id,
                "stage": _string(candidate.get("stage")),
                "snippet": _string(candidate.get("snippet")) or _string(candidate.get("summary")) or "",
                "score": candidate.get("score") if isinstance(candidate.get("score"), (int, float)) else None,
            }
        )
        seen.add(application_id)
    return output


def _parse_scope_answer(answer: Any, application_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(answer, dict):
        raise ValidationError("interview review scope resume payload must be an object.")
    save_note = _bool_value(answer.get("save_note"), default=True)
    update_application = _bool_value(answer.get("update_application"), default=True)
    if update_application and not save_note:
        raise ValidationError("save_note must be true when update_application is true.")
    selected_application_id = _string(answer.get("selected_application_id"))
    if selected_application_id is None and update_application and len(application_candidates) == 1:
        selected_application_id = _string(application_candidates[0].get("application_id"))
    if update_application and selected_application_id is None:
        raise ValidationError("selected_application_id is required when update_application is true.")
    update_fields = _update_fields(answer.get("update_fields"))
    return {
        "selected_application_id": selected_application_id,
        "save_note": save_note,
        "update_application": update_application,
        "update_fields": update_fields,
        "user_supplement": _string(answer.get("user_supplement")),
    }


def _selected_refs_for_scope(
    *,
    application_id: str | None,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for candidate in candidates:
        raw_ref = candidate.get("source_ref")
        ref = raw_ref if isinstance(raw_ref, dict) else {}
        source_type = _string(ref.get("source_type"))
        source_id = _string(ref.get("source_id"))
        if source_type is None or source_id is None:
            continue
        if application_id is not None and source_type == "career_application" and source_id != application_id:
            continue
        output.append(
            {
                "source_type": source_type,
                "source_id": source_id,
                "source_session_id": _string(ref.get("source_session_id")),
                "artifact_id": _string(ref.get("artifact_id")),
                "title": _string(candidate.get("title")),
                "quote": _string(candidate.get("snippet")),
            }
        )
    return _dedupe_refs(output)


def _update_fields(value: Any) -> list[str]:
    if not isinstance(value, list):
        return list(_DEFAULT_UPDATE_FIELDS)
    output: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = _string(item)
        if normalized is None or normalized not in _ALLOWED_UPDATE_FIELDS or normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output or list(_DEFAULT_UPDATE_FIELDS)


def _bool_value(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _note_create_args(state: InterviewReviewGraphState) -> dict[str, Any]:
    raw_draft = state.get("note_draft")
    draft = _normalize_note_draft(raw_draft if isinstance(raw_draft, dict) else {}, state)
    evidence_refs, source_refs = _note_refs_from_selected_sources(state)
    application_id = _string(state.get("selected_application_id"))
    if application_id is not None:
        evidence_refs = _dedupe_strings([application_id, *evidence_refs])
        if not any(
            ref.get("source_type") == "career_application" and ref.get("source_id") == application_id
            for ref in source_refs
        ):
            source_refs.insert(
                0,
                {
                    "source_type": "career_application",
                    "source_id": application_id,
                    "source_session_id": state["session_id"],
                    "title": "关联求职项目",
                },
            )
    supplement = _string(state.get("user_supplement"))
    if supplement:
        source_refs.append(
            {
                "source_type": "manual",
                "source_id": None,
                "source_session_id": state["session_id"],
                "title": "用户补充",
                "quote": supplement[:500],
            }
        )
    return {
        "note_id": _note_id(state),
        "title": draft["title"],
        "body_markdown": draft["body_markdown"],
        "body_format": "markdown",
        "summary": draft["summary"],
        "tags": draft["tags"],
        "source_refs": source_refs,
        "evidence_refs": evidence_refs,
        "related_application_id": application_id,
        "note_type": "note",
    }


def _note_refs_from_selected_sources(state: InterviewReviewGraphState) -> tuple[list[str], list[dict[str, Any]]]:
    evidence_refs: list[str] = []
    source_refs: list[dict[str, Any]] = []
    for ref in state.get("selected_source_refs") or []:
        if not isinstance(ref, dict):
            continue
        source_type = _string(ref.get("source_type"))
        source_id = _string(ref.get("source_id"))
        if source_type is None:
            continue
        if source_id is not None and _is_evidence_ref(source_id):
            evidence_refs.append(source_id)
        note_source_type = _RETRIEVAL_TO_NOTE_SOURCE_TYPE.get(source_type)
        if note_source_type not in _SUPPORTED_NOTE_SOURCE_TYPES or source_id is None:
            continue
        if note_source_type == "artifact":
            source_id = _string(ref.get("artifact_id")) or source_id
        source_refs.append(
            {
                "source_type": note_source_type,
                "source_id": source_id,
                "source_session_id": _string(ref.get("source_session_id")),
                "artifact_id": _string(ref.get("artifact_id")),
                "title": _string(ref.get("title")),
                "quote": _string(ref.get("quote")),
            }
        )
    return _dedupe_strings(evidence_refs), _dedupe_source_refs(source_refs)


def _known_refs_for_merge(state: InterviewReviewGraphState, *, note_id: str) -> dict[str, Any]:
    known_refs = dict(state.get("known_refs") or {})
    application_id = _string(state.get("selected_application_id"))
    if application_id is not None:
        known_refs["application_id"] = application_id
    known_refs["note_id"] = note_id
    known_refs["record_id"] = note_id
    for ref in state.get("selected_source_refs") or []:
        if not isinstance(ref, dict):
            continue
        source_type = _string(ref.get("source_type"))
        source_id = _string(ref.get("source_id"))
        if source_type is None or source_id is None:
            continue
        key = _known_ref_key_for_source_type(source_type)
        if key is not None:
            known_refs.setdefault(key, source_id)
    return known_refs


def _known_ref_key_for_source_type(source_type: str) -> str | None:
    return {
        "career_application": "application_id",
        "resume_profile": "resume_profile_id",
        "career_profile": "career_profile_id",
        "jd_analysis": "jd_analysis_id",
        "job_fit_report": "job_fit_report_id",
        "resume_version": "resume_version_id",
        "session_artifact": "report_artifact_id",
        "artifact": "report_artifact_id",
    }.get(source_type)


def _merge_updates(base_value: Any, preview: dict[str, Any], *, note_id: str) -> dict[str, Any]:
    base = dict(base_value) if isinstance(base_value, dict) else {}
    updates = dict(base)
    updates.update(_preview_updates_for_merge(preview))
    notes = _string(updates.get("notes"))
    note_line = f"面试复盘已保存为 Note {note_id}。"
    updates["notes"] = f"{notes}\n{note_line}".strip() if notes and note_line not in notes else notes or note_line
    return updates


def _preview_updates_for_merge(preview: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    stage = _string(preview.get("stage"))
    if stage is not None:
        output["stage"] = stage
    summary = _string(preview.get("summary"))
    if summary is not None:
        output["summary"] = summary[:500]
    next_actions = _string_list(preview.get("next_actions"))
    if next_actions:
        output["next_actions"] = next_actions[:8]
    risks = _string_list(preview.get("risks"))
    if risks:
        output["risks"] = risks[:8]
    notes = _string(preview.get("notes"))
    if notes is not None:
        output["notes"] = notes[:1000]
    return output


def _outputs(state: InterviewReviewGraphState) -> dict[str, Any]:
    raw_outputs = state.get("outputs")
    return dict(raw_outputs) if isinstance(raw_outputs, dict) else {}


def _merged_outputs(state: InterviewReviewGraphState, updates: dict[str, Any]) -> dict[str, Any]:
    output = _outputs(state)
    output.update(updates)
    return output


def _known_refs_with(state: InterviewReviewGraphState, updates: dict[str, Any]) -> dict[str, Any]:
    output = dict(state.get("known_refs") or {})
    output.update({key: value for key, value in updates.items() if value is not None})
    return output


def _note_id(state: InterviewReviewGraphState) -> str:
    suffix = str(state["workflow_instance_id"]).removeprefix("wf_").replace("-", "_")
    return f"note_{suffix}"


def _context_pack_query(state: InterviewReviewGraphState) -> str:
    supplement = _string(state.get("user_supplement"))
    if supplement:
        return f"{state.get('user_goal', '')}\n\n用户补充：{supplement}"
    return _non_empty(state.get("user_goal"), "面试复盘 更新求职项目")


def _context_pack_source_types(state: InterviewReviewGraphState) -> list[str]:
    selected = state.get("selected_source_refs") or []
    source_types: list[str] = []
    for ref in selected:
        if not isinstance(ref, dict):
            continue
        source_type = _string(ref.get("source_type"))
        if source_type in {
            "career_application",
            "job_fit_report",
            "resume_profile",
            "jd_analysis",
            "career_profile",
            "resume_version",
        }:
            source_types.append("career")
        elif source_type == "note":
            source_types.append("notes")
        elif source_type == "learning_task":
            source_types.append("learning")
        elif source_type == "session_artifact":
            source_types.append("artifacts")
        elif source_type:
            source_types.append(source_type)
    if not source_types:
        return ["career", "notes", "knowledge", "learning", "artifacts"]
    return _dedupe_strings(source_types)


def _normalize_note_draft(value: Any, state: InterviewReviewGraphState) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    fallback = _fallback_review_draft(state)["note_draft"]
    title = _string(raw.get("title")) or str(fallback["title"])
    body = _string(raw.get("body_markdown")) or str(fallback["body_markdown"])
    summary = _string(raw.get("summary")) or str(fallback["summary"])
    raw_tags = raw.get("tags")
    tags = raw_tags if isinstance(raw_tags, list) else fallback["tags"]
    return {
        "title": title[:120],
        "body_markdown": body,
        "summary": summary[:500],
        "tags": [str(item).strip() for item in tags if isinstance(item, str) and item.strip()][:12],
    }


def _normalize_application_update_preview(value: Any, state: InterviewReviewGraphState) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    fallback = _fallback_review_draft(state)["application_update_preview"]
    stage = _string(raw.get("stage")) or str(fallback["stage"])
    summary = _string(raw.get("summary")) or str(fallback["summary"])
    notes = _string(raw.get("notes")) or str(fallback["notes"])
    next_actions = _string_list(raw.get("next_actions")) or list(fallback["next_actions"])
    risks = _string_list(raw.get("risks")) or list(fallback["risks"])
    update_fields = set(state.get("update_fields") or _DEFAULT_UPDATE_FIELDS)
    preview: dict[str, Any] = {}
    if "stage" in update_fields:
        preview["stage"] = stage
    if "summary" in update_fields:
        preview["summary"] = summary[:500]
    if "next_actions" in update_fields:
        preview["next_actions"] = next_actions[:8]
    if "risks" in update_fields:
        preview["risks"] = risks[:8]
    if "notes" in update_fields:
        preview["notes"] = notes[:1000]
    return preview


def _parse_confirmation_answer(
    answer: Any,
    *,
    note_draft: dict[str, Any],
    application_update_preview: dict[str, Any],
    state: InterviewReviewGraphState,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if not isinstance(answer, dict):
        raise ValidationError("interview review confirmation resume payload must be an object.")
    action = (_string(answer.get("action")) or "approve").lower()
    if action not in {"approve", "edit", "regenerate", "cancel"}:
        raise ValidationError("interview review confirmation action must be approve/edit/regenerate/cancel.")
    if action == "cancel":
        return action, note_draft, application_update_preview
    edited_note = answer.get("edited_note_draft")
    edited_update = answer.get("edited_application_updates")
    merged_note = dict(note_draft)
    if isinstance(edited_note, dict):
        merged_note.update(edited_note)
    merged_update = dict(application_update_preview)
    if isinstance(edited_update, dict):
        merged_update.update({key: value for key, value in edited_update.items() if key in _ALLOWED_UPDATE_FIELDS})
    return (
        action,
        _normalize_note_draft(merged_note, state),
        _normalize_application_update_preview(merged_update, state),
    )


def _fallback_review_draft(state: InterviewReviewGraphState) -> dict[str, Any]:
    application_id = _string(state.get("selected_application_id")) or "当前求职项目"
    supplement = _string(state.get("user_supplement"))
    source_lines = []
    for ref in state.get("selected_source_refs") or []:
        if not isinstance(ref, dict):
            continue
        title = _string(ref.get("title")) or _string(ref.get("source_id")) or "来源"
        quote = _string(ref.get("quote"))
        source_lines.append(f"- {title}" + (f"：{quote}" if quote else ""))
    body_parts = ["# 面试复盘", "", f"关联项目：{application_id}", ""]
    if source_lines:
        body_parts.extend(["## 依据", *source_lines, ""])
    if supplement:
        body_parts.extend(["## 用户补充", supplement, ""])
    body_parts.extend(["## 复盘", "已根据召回上下文整理，写入前可继续编辑。"])
    return {
        "note_draft": {
            "title": "面试复盘",
            "body_markdown": "\n".join(body_parts).strip(),
            "summary": "面试复盘草稿，等待用户确认后写入。",
            "tags": ["面试复盘", "interview"],
        },
        "application_update_preview": {
            "stage": "interviewing",
            "summary": "面试已完成，复盘内容等待写入求职项目。",
            "next_actions": ["根据面试复盘补强薄弱问题并准备下一轮面试。"],
            "risks": ["面试复盘中暴露的问题仍需补强。"],
            "notes": "面试复盘草稿已生成，等待用户确认后更新项目。",
        },
    }


def _langgraph_llm_usage_payload(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    content: str,
    reasoning_content: str,
    usage: TokenUsage | None,
    model: str | None,
    model_client: ChatModelClient,
) -> dict[str, Any]:
    estimated_prompt = estimate_tokens_from_text(system_prompt) + estimate_tokens_from_object(messages)
    estimated_completion = estimate_tokens_from_text(content) + estimate_tokens_from_text(reasoning_content)
    prompt_tokens = _usage_int(usage.prompt_tokens if usage is not None else None) or estimated_prompt
    completion_tokens = _usage_int(usage.completion_tokens if usage is not None else None) or estimated_completion
    total_tokens = _usage_int(usage.total_tokens if usage is not None else None) or (prompt_tokens + completion_tokens)
    return {
        "api": "POST /v1/chat/completions",
        "operation": "model.generate",
        "mode": "sync",
        "phase": "langgraph_interview_review_draft",
        "round_index": None,
        "model": model or _model_client_name(model_client),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated": usage.estimated if usage is not None else True,
        "usage_source": usage.source if usage is not None else "estimated",
        "message_count": len(messages) + 1,
        "tool_schema_count": 0,
        "returned_tool_call_count": 0,
        "content_chars": len(content or ""),
        "reasoning_chars": len(reasoning_content or ""),
        "system_prompt_estimate_tokens": estimate_tokens_from_text(system_prompt),
        "message_estimate_tokens": estimate_tokens_from_object(messages),
        "tool_schema_estimate_tokens": 0,
    }


def _usage_int(value: int | None) -> int | None:
    if value is None or value < 0:
        return None
    return int(value)


def _model_client_name(model_client: ChatModelClient) -> str:
    for attr in ("model", "_model"):
        value = getattr(model_client, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown"


def _answer_for_interrupt(payload: dict[str, Any]) -> str:
    kind = _string(payload.get("type"))
    if kind == "interview_review_scope":
        return "需要你确认要更新的面试复盘范围。"
    if kind == "interview_review_confirmation":
        return "面试复盘草稿和项目更新预览已生成，需要你确认、编辑或取消。"
    if kind == WRITE_RETRY_INTERRUPT_TYPE:
        operation_label = _string(payload.get("operation_label")) or "写入"
        return f"{operation_label}失败，需要你选择重试或取消。"
    return "workflow 已暂停，等待你的输入。"


def _route_after_review_note_write(state: InterviewReviewGraphState) -> str:
    return "retry" if state.get("phase") == _PHASE_WRITE_RETRY else "next"


def _route_after_application_merge(state: InterviewReviewGraphState) -> str:
    return "retry" if state.get("phase") == _PHASE_WRITE_RETRY else "final"


def _route_after_write_retry(state: InterviewReviewGraphState) -> str:
    if state.get("phase") == _PHASE_CANCELLED:
        return "final"
    failed_node = failed_write_node(dict(state))
    if failed_node == "write_review_note":
        return "note"
    if failed_node == "merge_career_application":
        return "application"
    return "final"


def _runtime_plan_for_tool(
    *,
    state: InterviewReviewGraphState,
    tool_name: str,
    missing_output: str,
) -> dict[str, Any]:
    return {
        "phase": "interview_review_update",
        "contract_id": INTERVIEW_REVIEW_ACTION_CONTRACT_ID,
        "next_action": f"LangGraph workflow 正在执行 {tool_name}。",
        "current_allowed_tools": [tool_name],
        "next_allowed_tools": [tool_name],
        "required_tools": [tool_name],
        "upcoming_required_tools": [],
        "known_refs": state.get("known_refs") or {},
        "missing_outputs": [missing_output],
        "final_answer_ready": False,
        "discouraged_tools": [tool for tool in _FORBIDDEN_WRITE_TOOLS if tool != tool_name],
    }


def _append_tool_call(
    state: InterviewReviewGraphState,
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
        if name is None or not isinstance(arguments, dict):
            continue
        output.append(ToolCall(name=name, arguments=arguments))
    return output


def _interrupt_payload(state: dict[str, Any]) -> dict[str, Any] | None:
    raw = state.get("__interrupt__")
    if not isinstance(raw, list) or not raw:
        return None
    first = raw[0]
    value = getattr(first, "value", None)
    return value if isinstance(value, dict) else None


def _pending_interrupt_payload_from_state(state: dict[str, Any]) -> dict[str, Any] | None:
    pending = state.get("pending_question")
    if isinstance(pending, dict):
        return pending
    return _interrupt_payload(state)


def _snapshot_for_persistence(
    state: dict[str, Any],
    *,
    pending_interrupt_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = _clean_state_snapshot(state)
    if pending_interrupt_payload is not None:
        snapshot["pending_question"] = _json_safe(pending_interrupt_payload)
    return snapshot


def _clean_state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _json_safe(value)
        for key, value in state.items()
        if key != "__interrupt__"
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _persisted_terminal_status(state: dict[str, Any]) -> str:
    phase = _string(state.get("phase"))
    if phase == _PHASE_CANCELLED:
        return WORKFLOW_STATUS_CANCELLED
    if phase == _PHASE_FAILED:
        return WORKFLOW_STATUS_FAILED
    return WORKFLOW_STATUS_COMPLETED


def _terminal_result_status(state: dict[str, Any]) -> str:
    phase = _string(state.get("phase"))
    if phase == _PHASE_FAILED:
        return "failed"
    if phase == _PHASE_CANCELLED:
        return "cancelled"
    return "completed"


def _non_empty(value: Any, fallback: str) -> str:
    text = _string(value)
    return text if text is not None else fallback


def _string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = _string(item)
        if text is not None:
            output.append(text)
    return output


def _dedupe_strings(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output


def _is_evidence_ref(value: str) -> bool:
    return value.startswith(
        (
            "application_",
            "fit_",
            "resume_profile_",
            "career_profile_",
            "jd_",
            "resume_version_",
            "note_",
            "artifact_",
            "resource_",
            "question_",
            "learning_task_",
        )
    )


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        key = (_string(ref.get("source_type")) or "", _string(ref.get("source_id")) or "")
        if key in seen or not key[0] or not key[1]:
            continue
        output.append(ref)
        seen.add(key)
    return output


def _dedupe_source_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str | None, str | None, str | None]] = set()
    for ref in refs:
        source_type = _string(ref.get("source_type"))
        if source_type is None:
            continue
        key = (
            source_type,
            _string(ref.get("source_id")),
            _string(ref.get("source_session_id")),
            _string(ref.get("title")),
            _string(ref.get("quote")),
        )
        if key in seen:
            continue
        output.append(ref)
        seen.add(key)
    return output
