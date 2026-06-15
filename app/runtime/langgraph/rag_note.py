"""Interactive RAG-to-Note workflow implemented with LangGraph."""

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
    RAG_NOTE_WORKFLOW_ID,
    WorkflowGraphRunResult,
    WorkflowGraphState,
    WorkflowResumeRequest,
)

__all__ = ["RagNoteWorkflowRunner"]

_PHASE_STARTED = "started"
_PHASE_SOURCE_SELECTION = "source_selection"
_PHASE_CONTEXT_PACK = "context_pack"
_PHASE_DRAFT = "draft"
_PHASE_REVIEW = "review"
_PHASE_WRITE = "write"
_PHASE_COMPLETED = "completed"
_PHASE_CANCELLED = "cancelled"
_PHASE_FAILED = "failed"

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


@dataclass(frozen=True, slots=True)
class _ExecutionBindings:
    context: RunContext
    channel: EventChannel | None


_CURRENT_BINDINGS: ContextVar[_ExecutionBindings | None] = ContextVar("rag_note_workflow_bindings", default=None)


class WorkflowTransientError(Exception):
    """Retryable workflow node failure."""


class RagNoteWorkflowRunner:
    """Run the interactive `rag.note.write.interactive.v1` graph."""

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
        node_retry_attempts: int = 3,
    ) -> None:
        normalized_backend = checkpoint_backend.strip().lower()
        if normalized_backend not in {"memory", "sqlite"}:
            raise ValidationError("checkpoint_backend must be memory/sqlite.")
        if node_timeout_seconds <= 0:
            raise ValidationError("node_timeout_seconds must be positive.")
        if node_retry_attempts <= 0:
            raise ValidationError("node_retry_attempts must be positive.")
        self._tool_gateway = tool_gateway
        self._model_client = model_client
        self._event_recorder = event_recorder
        self._workflow_store = workflow_store
        self._checkpoint_backend = normalized_backend
        self._checkpoint_path = checkpoint_path
        self._memory_checkpointer = InMemorySaver() if normalized_backend == "memory" else None
        self._node_timeout_seconds = node_timeout_seconds
        self._node_retry_attempts = node_retry_attempts

    async def run_stream(
        self,
        run_input: AgentRunInput,
        *,
        channel: EventChannel | None = None,
    ) -> WorkflowGraphRunResult:
        workflow_instance_id = f"wf_{uuid4().hex[:12]}"
        thread_id = _thread_id(run_input.session_id, workflow_instance_id)
        initial_state = WorkflowGraphState(
            session_id=run_input.session_id,
            run_id=run_input.context.run_id,
            workflow_instance_id=workflow_instance_id,
            thread_id=thread_id,
            contract_id=RAG_NOTE_WORKFLOW_ID,
            user_goal=run_input.user_message,
            phase=_PHASE_STARTED,
            known_refs={},
            retrieval_candidates=[],
            selected_source_refs=[],
            user_supplement=None,
            context_pack=None,
            draft_note=None,
            pending_question=None,
            retry_counters={},
            last_error=None,
            outputs={},
            tool_calls=[],
            answer="",
        )
        token = _CURRENT_BINDINGS.set(_ExecutionBindings(context=run_input.context, channel=channel))
        try:
            await self._persist_workflow_state(
                run_input.context,
                dict(initial_state),
                status=WORKFLOW_STATUS_RUNNING,
            )
            await self._emit_workflow_event(
                run_input.context,
                "workflow_started",
                {
                    "workflow_instance_id": workflow_instance_id,
                    "thread_id": thread_id,
                    "contract_id": RAG_NOTE_WORKFLOW_ID,
                },
                channel=channel,
            )
            async with self._checkpointer_handle() as checkpointer:
                graph = self._build_graph(checkpointer.checkpointer)
                result = await graph.ainvoke(
                    initial_state,
                    config={"configurable": {"thread_id": thread_id}},
                )
        finally:
            _CURRENT_BINDINGS.reset(token)
        return await self._result_from_graph_output(
            result,
            context=run_input.context,
            channel=channel,
        )

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
        return await self._result_from_graph_output(
            result,
            context=request.context,
            channel=channel,
        )

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
        builder = StateGraph(WorkflowGraphState)
        builder.add_node("init_request", self._init_request)
        builder.add_node("retrieval_search", self._retrieval_search, retry_policy=retry, timeout=timeout)
        builder.add_node("source_selection", self._source_selection)
        builder.add_node("retrieval_context_pack", self._retrieval_context_pack, retry_policy=retry, timeout=timeout)
        builder.add_node("draft_note", self._draft_note, retry_policy=retry, timeout=timeout)
        builder.add_node("note_review", self._note_review)
        builder.add_node("write_note", self._write_note, retry_policy=retry, timeout=timeout)
        builder.add_node("final_answer", self._final_answer)
        builder.add_edge(START, "init_request")
        builder.add_edge("init_request", "retrieval_search")
        builder.add_edge("retrieval_search", "source_selection")
        builder.add_edge("source_selection", "retrieval_context_pack")
        builder.add_edge("retrieval_context_pack", "draft_note")
        builder.add_edge("draft_note", "note_review")
        builder.add_edge("note_review", "write_note")
        builder.add_edge("write_note", "final_answer")
        builder.add_edge("final_answer", END)
        return builder.compile(checkpointer=checkpointer)

    async def _init_request(self, state: WorkflowGraphState) -> dict[str, Any]:
        await self._emit_node_event(state, "init_request", "workflow_node_succeeded")
        if state.get("phase") != _PHASE_STARTED:
            return {}
        return {"phase": _PHASE_STARTED}

    async def _retrieval_search(self, state: WorkflowGraphState) -> dict[str, Any]:
        if state.get("retrieval_candidates"):
            return {}
        await self._emit_node_event(state, "retrieval_search", "workflow_node_started")
        args = {
            "query": _non_empty(state.get("user_goal"), "生成笔记"),
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
        await self._emit_node_event(
            state,
            "retrieval_search",
            "workflow_node_succeeded",
            {"candidate_count": len(candidates)},
        )
        return {
            "phase": _PHASE_SOURCE_SELECTION,
            "retrieval_candidates": candidates,
            "tool_calls": _append_tool_call(state, "retrieval_search", args),
        }

    async def _source_selection(self, state: WorkflowGraphState) -> dict[str, Any]:
        if state.get("selected_source_refs") or state.get("user_supplement"):
            return {}
        payload = {
            "type": "source_selection",
            "workflow_instance_id": state["workflow_instance_id"],
            "thread_id": state["thread_id"],
            "question": "选择用于生成笔记的来源，也可以补充你想加入的内容。",
            "candidates": state.get("retrieval_candidates", []),
            "allow_extra_input": True,
            "allow_skip": not bool(state.get("retrieval_candidates")),
        }
        answer = interrupt(payload)
        selected_refs, supplement = _parse_source_selection_answer(answer, state.get("retrieval_candidates", []))
        return {
            "phase": _PHASE_CONTEXT_PACK,
            "selected_source_refs": selected_refs,
            "user_supplement": supplement,
            "pending_question": None,
        }

    async def _retrieval_context_pack(self, state: WorkflowGraphState) -> dict[str, Any]:
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

    async def _draft_note(self, state: WorkflowGraphState) -> dict[str, Any]:
        if state.get("draft_note") is not None:
            return {}
        await self._emit_node_event(state, "draft_note", "workflow_node_started")
        draft, llm_usage_payload = await asyncio.to_thread(self._generate_note_draft, state)
        await self._event_recorder.record_async(
            _bindings().context,
            "llm_usage",
            llm_usage_payload,
            channel=_bindings().channel,
        )
        draft = _normalize_draft_note(draft, state)
        await self._emit_node_event(state, "draft_note", "workflow_node_succeeded")
        return {
            "phase": _PHASE_REVIEW,
            "draft_note": draft,
        }

    async def _note_review(self, state: WorkflowGraphState) -> dict[str, Any]:
        if state.get("outputs", {}).get("reviewed") is True:
            return {}
        payload = {
            "type": "note_review",
            "workflow_instance_id": state["workflow_instance_id"],
            "thread_id": state["thread_id"],
            "question": "确认笔记草稿后我再保存。",
            "draft": state.get("draft_note") or {},
            "source_refs": state.get("selected_source_refs", []),
            "actions": ["approve", "edit", "regenerate", "cancel"],
        }
        answer = interrupt(payload)
        action, draft = _parse_note_review_answer(answer, state.get("draft_note") or {})
        if action == "cancel":
            return {
                "phase": _PHASE_CANCELLED,
                "outputs": {"reviewed": True, "cancelled": True},
                "answer": "已取消保存笔记。",
                "pending_question": None,
            }
        return {
            "phase": _PHASE_WRITE,
            "draft_note": _normalize_draft_note(draft, state),
            "outputs": {"reviewed": True},
            "pending_question": None,
        }

    async def _write_note(self, state: WorkflowGraphState) -> dict[str, Any]:
        if state.get("phase") == _PHASE_CANCELLED:
            return {}
        outputs = state.get("outputs") or {}
        if isinstance(outputs, dict) and isinstance(outputs.get("note_id"), str):
            return {}
        await self._emit_node_event(state, "write_note", "workflow_node_started")
        draft = _normalize_draft_note(state.get("draft_note") or {}, state)
        args = _note_create_args(state, draft)
        result = await self._execute_tool("note_create", args, state=state, missing_output="note")
        if not result.success:
            repaired_args = _repair_note_args(args, state)
            result = await self._execute_tool("note_create", repaired_args, state=state, missing_output="note")
            args = repaired_args
        if not result.success:
            await self._emit_node_failed(state, "write_note", result.content)
            return {
                "phase": _PHASE_FAILED,
                "last_error": {"node": "write_note", "error": result.content[:500]},
                "answer": "笔记保存失败，已停止本次 workflow。",
            }
        payload = _json_object(result.content)
        note_id = _string(payload.get("record_id")) or _string(payload.get("note_id")) or _note_id(state)
        await self._emit_node_event(
            state,
            "write_note",
            "workflow_node_succeeded",
            {"note_id": note_id},
        )
        return {
            "phase": _PHASE_COMPLETED,
            "outputs": {"reviewed": True, "note_id": note_id, "note_title": args.get("title")},
            "tool_calls": _append_tool_call(state, "note_create", args),
        }

    async def _final_answer(self, state: WorkflowGraphState) -> dict[str, Any]:
        raw_outputs = state.get("outputs")
        outputs = raw_outputs if isinstance(raw_outputs, dict) else {}
        if state.get("phase") == _PHASE_CANCELLED:
            answer = _non_empty(state.get("answer"), "已取消保存笔记。")
        elif state.get("phase") == _PHASE_FAILED:
            answer = _non_empty(state.get("answer"), "笔记保存失败，已停止本次 workflow。")
        else:
            note_id = _string(outputs.get("note_id")) or _note_id(state)
            raw_draft = state.get("draft_note")
            draft = raw_draft if isinstance(raw_draft, dict) else {}
            title = _string(outputs.get("note_title")) or _string(draft.get("title")) or "笔记"
            answer = f"已保存笔记：{title}\n\nnote_id: {note_id}"
            await self._emit_workflow_event(
                _bindings().context,
                "workflow_completed",
                {
                    "workflow_instance_id": state["workflow_instance_id"],
                    "thread_id": state["thread_id"],
                    "note_id": note_id,
                    "title": title,
                },
                channel=_bindings().channel,
            )
        return {"answer": answer}

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        state: WorkflowGraphState,
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

    def _generate_note_draft(self, state: WorkflowGraphState) -> tuple[dict[str, Any], dict[str, Any]]:
        system_prompt = (
            "你是笔记整理助手。只输出 JSON 对象，字段为 title, body_markdown, summary, tags。"
            "不要调用工具，不要输出 Markdown 代码块。"
        )
        messages = [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "goal": state.get("user_goal"),
                        "selected_sources": state.get("selected_source_refs", []),
                        "user_supplement": state.get("user_supplement"),
                        "context_pack": state.get("context_pack"),
                    },
                    ensure_ascii=False,
                ),
            }
        ]
        response = self._model_client.generate(
            system_prompt=system_prompt,
            messages=messages,
            tools=[],
        )
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
        return _fallback_draft(state), usage_payload

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
            await self._emit_workflow_event(
                context,
                "workflow_waiting_for_input",
                interrupt_payload,
                channel=channel,
            )
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
        answer = _non_empty(state.get("answer"), "workflow 已结束。")
        output = AgentRunOutput(
            session_id=context.session_id,
            answer=answer,
            tool_calls=_tool_calls_from_state(state),
            memory_hits=[],
        )
        status: Any = "failed" if state.get("phase") == _PHASE_FAILED else "completed"
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
            workflow_id=RAG_NOTE_WORKFLOW_ID,
            thread_id=thread_id,
            run_id=context.run_id,
            status=status,
            phase=phase,
            state_snapshot=_snapshot_for_persistence(state, pending_interrupt_payload=pending_interrupt_payload),
            pending_interrupt_payload=pending_interrupt_payload,
            output_refs=output_refs,
            last_error=last_error,
        )

    async def _emit_waiting_for_input(self, state: WorkflowGraphState, payload: dict[str, Any]) -> None:
        bindings = _bindings()
        await self._emit_workflow_event(
            bindings.context,
            "workflow_waiting_for_input",
            payload,
            channel=bindings.channel,
        )

    async def _emit_node_event(
        self,
        state: WorkflowGraphState,
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

    async def _emit_node_failed(self, state: WorkflowGraphState, node_name: str, error: str) -> None:
        await self._emit_node_event(
            state,
            node_name,
            "workflow_node_failed",
            {"error": error[:500]},
        )

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


def _bindings() -> _ExecutionBindings:
    bindings = _CURRENT_BINDINGS.get()
    if bindings is None:
        raise ValidationError("workflow execution bindings are missing.")
    return bindings


def _thread_id(session_id: str, workflow_instance_id: str) -> str:
    return f"{session_id}:{workflow_instance_id}"


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
    return {
        "source_ref": {
            "source_type": _string(source.get("source_type")) or "",
            "source_id": _string(source.get("source_id")) or "",
            "source_session_id": _string(source.get("source_session_id")),
            "artifact_id": _string(source.get("artifact_id")),
        },
        "title": _string(hit.get("title")) or "未命名来源",
        "snippet": _string(hit.get("snippet")) or _string(hit.get("summary")) or "",
        "summary": _string(hit.get("summary")) or "",
        "score": hit.get("score") if isinstance(hit.get("score"), (int, float)) else None,
        "evidence_refs": hit.get("evidence_refs") if isinstance(hit.get("evidence_refs"), list) else [],
    }


def _parse_source_selection_answer(answer: Any, candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(answer, dict):
        raise ValidationError("source selection resume payload must be an object.")
    raw_refs = answer.get("selected_source_refs")
    selected: list[dict[str, Any]] = []
    if isinstance(raw_refs, list):
        for item in raw_refs:
            ref = _source_ref_from_selection_item(item)
            if ref is not None:
                selected.append(ref)
    if not selected and candidates and answer.get("allow_default") is True:
        for candidate in candidates[:3]:
            ref = _source_ref_from_selection_item(candidate.get("source_ref"))
            if ref is not None:
                selected.append(ref)
    supplement = _string(answer.get("user_supplement"))
    if not selected and not supplement:
        raise ValidationError("source selection requires selected_source_refs or user_supplement.")
    return _dedupe_refs(selected), supplement


def _source_ref_from_selection_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    raw_source_ref = item.get("source_ref")
    raw = raw_source_ref if isinstance(raw_source_ref, dict) else item
    source_type = _string(raw.get("source_type"))
    source_id = _string(raw.get("source_id"))
    if source_type is None or source_id is None:
        return None
    return {
        "source_type": source_type,
        "source_id": source_id,
        "source_session_id": _string(raw.get("source_session_id")),
        "artifact_id": _string(raw.get("artifact_id")),
        "title": _string(item.get("title")),
        "quote": _string(item.get("snippet")) or _string(item.get("quote")),
    }


def _parse_note_review_answer(answer: Any, current_draft: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(answer, dict):
        raise ValidationError("note review resume payload must be an object.")
    action = (_string(answer.get("action")) or "approve").lower()
    if action not in {"approve", "edit", "regenerate", "cancel"}:
        raise ValidationError("note review action must be approve/edit/regenerate/cancel.")
    if action == "cancel":
        return action, current_draft
    edited = answer.get("edited_draft")
    if action in {"edit", "regenerate"} and isinstance(edited, dict):
        merged = dict(current_draft)
        merged.update(edited)
        return action, merged
    return action, current_draft


def _context_pack_query(state: WorkflowGraphState) -> str:
    supplement = _string(state.get("user_supplement"))
    if supplement:
        return f"{state.get('user_goal', '')}\n\n用户补充：{supplement}"
    return _non_empty(state.get("user_goal"), "生成笔记")


def _context_pack_source_types(state: WorkflowGraphState) -> list[str]:
    selected = state.get("selected_source_refs") or []
    source_types: list[str] = []
    for ref in selected:
        if not isinstance(ref, dict):
            continue
        source_type = _string(ref.get("source_type"))
        if source_type == "session_artifact":
            source_types.append("artifacts")
        elif source_type:
            source_types.append(source_type)
    if not source_types:
        return ["career", "notes", "knowledge", "learning", "artifacts"]
    return _dedupe_strings(source_types)


def _normalize_draft_note(raw: dict[str, Any], state: WorkflowGraphState) -> dict[str, Any]:
    fallback = _fallback_draft(state)
    title = _string(raw.get("title")) or fallback["title"]
    body = _string(raw.get("body_markdown")) or fallback["body_markdown"]
    summary = _string(raw.get("summary")) or fallback["summary"]
    raw_tags = raw.get("tags")
    tags = raw_tags if isinstance(raw_tags, list) else fallback["tags"]
    return {
        "title": title[:120],
        "body_markdown": body,
        "summary": summary[:500],
        "tags": [str(item).strip() for item in tags if isinstance(item, str) and item.strip()][:12],
    }


def _fallback_draft(state: WorkflowGraphState) -> dict[str, Any]:
    sources = state.get("selected_source_refs") or []
    source_lines = []
    for ref in sources:
        if not isinstance(ref, dict):
            continue
        title = _string(ref.get("title")) or _string(ref.get("source_id")) or "来源"
        quote = _string(ref.get("quote"))
        source_lines.append(f"- {title}" + (f"：{quote}" if quote else ""))
    supplement = _string(state.get("user_supplement"))
    body_parts = [f"# {_short_title(state.get('user_goal'))}", ""]
    if source_lines:
        body_parts.extend(["## 来源", *source_lines, ""])
    if supplement:
        body_parts.extend(["## 用户补充", supplement, ""])
    body_parts.extend(["## 整理", "基于已选择来源整理，后续可继续编辑完善。"])
    return {
        "title": _short_title(state.get("user_goal")),
        "body_markdown": "\n".join(body_parts).strip(),
        "summary": "基于已选择来源生成的交互式笔记。",
        "tags": ["agent-note", "rag"],
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
        "phase": "langgraph_draft_note",
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


def _note_create_args(state: WorkflowGraphState, draft: dict[str, Any]) -> dict[str, Any]:
    evidence_refs, source_refs = _note_refs_from_selected_sources(state)
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
        "title": _non_empty(draft.get("title"), "生成笔记"),
        "body_markdown": _non_empty(draft.get("body_markdown"), "基于已选择来源生成的笔记。"),
        "summary": _string(draft.get("summary")) or "",
        "tags": draft.get("tags") if isinstance(draft.get("tags"), list) else ["agent-note", "rag"],
        "source_refs": source_refs,
        "evidence_refs": evidence_refs,
        "note_type": "note",
    }


def _repair_note_args(args: dict[str, Any], state: WorkflowGraphState) -> dict[str, Any]:
    repaired = dict(args)
    repaired["title"] = _non_empty(repaired.get("title"), _short_title(state.get("user_goal")))
    repaired["body_markdown"] = _non_empty(repaired.get("body_markdown"), _fallback_draft(state)["body_markdown"])
    repaired["source_refs"] = [
        ref
        for ref in repaired.get("source_refs", [])
        if isinstance(ref, dict)
        and (_string(ref.get("source_type")) in _SUPPORTED_NOTE_SOURCE_TYPES or _string(ref.get("source_type")) == "manual")
    ]
    return repaired


def _note_refs_from_selected_sources(state: WorkflowGraphState) -> tuple[list[str], list[dict[str, Any]]]:
    evidence_refs: list[str] = []
    source_refs: list[dict[str, Any]] = []
    for ref in state.get("selected_source_refs") or []:
        if not isinstance(ref, dict):
            continue
        source_type = _string(ref.get("source_type"))
        source_id = _string(ref.get("source_id"))
        if source_id is not None:
            evidence_refs.append(source_id)
        note_source_type = _RETRIEVAL_TO_NOTE_SOURCE_TYPE.get(source_type or "")
        if note_source_type not in _SUPPORTED_NOTE_SOURCE_TYPES or source_id is None:
            continue
        if note_source_type == "artifact":
            source_id = _string(ref.get("artifact_id")) or source_id
        source_refs.append(
            {
                "source_type": note_source_type,
                "source_id": source_id,
                "source_session_id": _string(ref.get("source_session_id")) or state["session_id"],
                "title": _string(ref.get("title")) or "",
                "quote": _string(ref.get("quote")) or "",
            }
        )
    return _dedupe_strings(evidence_refs), source_refs


def _runtime_plan_for_tool(
    *,
    state: WorkflowGraphState,
    tool_name: str,
    missing_output: str,
) -> dict[str, Any]:
    return {
        "phase": "rag_note_write",
        "contract_id": "rag.note.write.v1",
        "next_action": f"LangGraph workflow 正在执行 {tool_name}。",
        "current_allowed_tools": [tool_name],
        "next_allowed_tools": [tool_name],
        "required_tools": [tool_name],
        "upcoming_required_tools": [],
        "known_refs": state.get("known_refs") or {},
        "missing_outputs": [missing_output],
        "final_answer_ready": False,
        "discouraged_tools": [],
    }


def _append_tool_call(state: WorkflowGraphState, tool_name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
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


def _answer_for_interrupt(payload: dict[str, Any]) -> str:
    kind = _string(payload.get("type"))
    if kind == "source_selection":
        return "需要你选择用于生成笔记的来源，或补充要写入的内容。"
    if kind == "note_review":
        return "笔记草稿已生成，需要你确认、编辑或取消。"
    return "workflow 已暂停，等待你的输入。"


def _note_id(state: WorkflowGraphState) -> str:
    suffix = str(state["workflow_instance_id"]).removeprefix("wf_").replace("-", "_")
    return f"note_{suffix}"


def _short_title(value: Any) -> str:
    text = _string(value) or "生成笔记"
    return text[:60]


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


def _dedupe_strings(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output
