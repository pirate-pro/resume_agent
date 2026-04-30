"""Single-agent run orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.core.errors import AppError, ToolExecutionError, ValidationError
from app.domain.models import AgentRunInput, AgentRunOutput, RunContext, ToolCall, ToolExecutionResult
from app.domain.protocols import ChatModelClient, ToolExecutor
from app.runtime.context_assembler import ContextAssembler
from app.runtime.context_compactor import ContextCompactor
from app.runtime.event_channel import EventChannel
from app.runtime.event_recorder import EventRecorder
from app.runtime.mid_term_flusher import MidTermFlusher
from app.runtime.session_manager import SessionManager
from app.services.answer_normalizer import AnswerNormalizer

__all__ = ["AgentRuntime"]
_logger = logging.getLogger(__name__)
_FINAL_ANSWER_RECOVERY_PROMPT = (
    "你已经拿到了前面对话和工具结果。现在请直接给用户最终答复。"
    "不要再调用任何工具。"
    "如果你已经创建、修改或读取了文件，要明确说明结果和相关文件路径。"
    "如果前文要求生成内容用于展示，就把最终内容直接回复给用户，而不是只写入文件。"
    "如果最终内容应为 Markdown 文档，不要再额外包一层 ```markdown 外层代码块；"
    "只有在用户明确要求查看 Markdown 源码时，才使用 ```markdown 代码块。"
    "如果只是普通回答，请使用自然段落，不要每句话都单独换行。"
    "可以克制地使用 **重点词**、*次级术语* 和 `命令或文件名` 做行内强调，但不要整段加粗。"
    "如果是在给多个可选方案、路线或建议，请拆成清晰的小节，并优先使用简短字段标签。"
    "如果是比较型信息或预算拆分，请优先使用紧凑的 Markdown 表格，并在表格后补一句简短结论。"
    "如果输出代码，必须把解释和代码块分开，并尽量提供语言标记。"
)


@dataclass(slots=True)
class _PostRunMaintenanceState:
    active: bool = False
    pending: bool = False
    latest_context: RunContext | None = None


class AgentRuntime:
    """Execute one complete agent run with optional tool loops."""

    def __init__(
        self,
        session_manager: SessionManager,
        event_recorder: EventRecorder,
        context_assembler: ContextAssembler,
        model_client: ChatModelClient,
        tool_executor: ToolExecutor,
        mid_term_flusher: MidTermFlusher | None = None,
        context_compactor: ContextCompactor | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._event_recorder = event_recorder
        self._context_assembler = context_assembler
        self._model_client = model_client
        self._tool_executor = tool_executor
        self._mid_term_flusher = mid_term_flusher
        self._context_compactor = context_compactor
        self._answer_normalizer = AnswerNormalizer()
        self._post_run_maintenance_lock = threading.Lock()
        self._post_run_maintenance_states: dict[tuple[str, str], _PostRunMaintenanceState] = {}

    def run(self, run_input: AgentRunInput) -> AgentRunOutput:
        if not isinstance(run_input, AgentRunInput):
            raise ValidationError("run_input must be an AgentRunInput.")

        _logger.info(
            "开始执行 agent run: session_id=%s message_len=%s skill_count=%s max_tool_rounds=%s",
            run_input.session_id,
            len(run_input.user_message),
            len(run_input.skill_names),
            run_input.max_tool_rounds,
        )
        session_meta = self._session_manager.get_or_create_session(run_input.session_id)
        session_id = session_meta.session_id
        run_context = self._resolve_run_context(session_id=session_id, run_input=run_input)

        self._event_recorder.record(
            context=run_context,
            event_type="run_started",
            payload={"max_tool_rounds": run_input.max_tool_rounds},
        )
        self._event_recorder.record(
            context=run_context,
            event_type="user_message",
            payload={"content": run_input.user_message},
        )

        context = self._context_assembler.assemble(
            context=run_context,
            user_message=run_input.user_message,
            skill_names=run_input.skill_names,
        )
        _logger.debug(
            "上下文组装完成: session_id=%s messages=%s memories=%s tools=%s",
            session_id,
            len(context.messages),
            len(context.memory_hits),
            len(context.tool_definitions),
        )
        self._event_recorder.record(
            context=run_context,
            event_type="memory_retrieval",
            payload=context.memory_summary,
        )

        tools_payload = [self._to_model_tool_schema(tool) for tool in context.tool_definitions]
        messages = list(context.messages)
        used_tool_calls: list[ToolCall] = []
        answer = ""

        # 轮次上限是 `max_tool_rounds + 1`：最后一轮用于拿到最终回答。
        for round_index in range(run_input.max_tool_rounds + 1):
            _logger.debug("模型调用开始: session_id=%s round=%s message_count=%s", session_id, round_index, len(messages))
            model_response = self._model_client.generate(
                system_prompt=context.system_prompt,
                messages=messages,
                tools=tools_payload,
            )
            _logger.debug(
                "模型调用完成: session_id=%s round=%s content_len=%s tool_call_count=%s",
                session_id,
                round_index,
                len(model_response.content),
                len(model_response.tool_calls),
            )

            resolved_tool_calls = self._ensure_tool_call_ids(model_response.tool_calls)

            if not resolved_tool_calls:
                answer = (model_response.content or "").strip()
                if not answer:
                    answer = self._recover_final_answer(
                        system_prompt=context.system_prompt,
                        messages=messages,
                        original_user_message=run_input.user_message,
                    )
                answer = answer or "(no answer)"
                break

            if round_index == run_input.max_tool_rounds:
                _logger.warning("达到工具调用上限: session_id=%s round=%s", session_id, round_index)
                answer = "Tool call limit reached before generating final answer."
                break

            if model_response.content.strip():
                # 一些模型会在 tool_call 前返回推理摘要，记录下来供前端“执行过程/思考”展示。
                self._event_recorder.record(
                    context=run_context,
                    event_type="assistant_thinking",
                    payload={"content": model_response.content},
                )

            # 遇到工具调用时，必须先把 assistant 的 tool_calls 消息回填到上下文，
            # 后续 tool 角色消息才是协议上合法的。
            messages.append(self._build_assistant_tool_call_message(model_response.content, resolved_tool_calls))

            for tool_call in resolved_tool_calls:
                used_tool_calls.append(tool_call)
                self._event_recorder.record(
                    context=run_context,
                    event_type="tool_call",
                    payload={
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "tool_call_id": tool_call.tool_call_id,
                    },
                )
                result = self._execute_tool_safely(tool_call, run_context)
                _logger.info(
                    "工具调用完成: session_id=%s tool=%s success=%s content_len=%s",
                    session_id,
                    tool_call.name,
                    result.success,
                    len(result.content),
                )
                self._event_recorder.record(
                    context=run_context,
                    event_type="tool_result",
                    payload={
                        "tool_name": result.tool_name,
                        "success": result.success,
                        "content": result.content,
                        "tool_call_id": tool_call.tool_call_id,
                    },
                )
                if tool_call.name == "memory_write" and result.success:
                    self._event_recorder.record(
                        context=run_context,
                        event_type="memory_write",
                        payload={
                            "arguments": tool_call.arguments,
                            "result": result.content,
                        },
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.tool_call_id,
                        "content": result.content,
                    }
                )

        if not answer:
            answer = "(no answer)"

        self._event_recorder.record(
            context=run_context,
            event_type="assistant_message",
            payload={"content": answer},
        )
        self._event_recorder.record(
            context=run_context,
            event_type="run_finished",
            payload={"answer_length": len(answer), "tool_calls": len(used_tool_calls)},
        )
        self._dispatch_post_run_maintenance_sync(run_context)
        _logger.info(
            "agent run 完成: session_id=%s answer_len=%s tool_calls=%s",
            session_id,
            len(answer),
            len(used_tool_calls),
        )

        return AgentRunOutput(
            session_id=session_id,
            answer=answer,
            tool_calls=used_tool_calls,
            memory_hits=context.memory_hits,
        )

    async def run_stream(self, run_input: AgentRunInput, channel: EventChannel) -> AgentRunOutput:
        if not isinstance(run_input, AgentRunInput):
            raise ValidationError("run_input must be an AgentRunInput.")
        if not isinstance(channel, EventChannel):
            raise ValidationError("channel must be an EventChannel.")

        _logger.info(
            "开始执行流式 agent run: session_id=%s message_len=%s skill_count=%s max_tool_rounds=%s",
            run_input.session_id,
            len(run_input.user_message),
            len(run_input.skill_names),
            run_input.max_tool_rounds,
        )
        session_meta = await asyncio.to_thread(self._session_manager.get_or_create_session, run_input.session_id)
        session_id = session_meta.session_id
        run_context = self._resolve_run_context(session_id=session_id, run_input=run_input)

        await self._event_recorder.record_async(
            context=run_context,
            event_type="run_started",
            payload={"max_tool_rounds": run_input.max_tool_rounds},
            channel=channel,
        )
        await self._event_recorder.record_async(
            context=run_context,
            event_type="user_message",
            payload={"content": run_input.user_message},
            channel=channel,
        )

        context = await asyncio.to_thread(
            self._context_assembler.assemble,
            context=run_context,
            user_message=run_input.user_message,
            skill_names=run_input.skill_names,
        )
        _logger.debug(
            "流式上下文组装完成: session_id=%s messages=%s memories=%s tools=%s",
            session_id,
            len(context.messages),
            len(context.memory_hits),
            len(context.tool_definitions),
        )
        await self._event_recorder.record_async(
            context=run_context,
            event_type="memory_retrieval",
            payload=context.memory_summary,
            channel=channel,
        )

        tools_payload = [self._to_model_tool_schema(tool) for tool in context.tool_definitions]
        messages = list(context.messages)
        used_tool_calls: list[ToolCall] = []
        answer = ""

        for round_index in range(run_input.max_tool_rounds + 1):
            _logger.debug("流式模型调用开始: session_id=%s round=%s message_count=%s", session_id, round_index, len(messages))
            round_content_parts: list[str] = []
            round_content_deltas: list[str] = []
            resolved_tool_calls: list[ToolCall] = []

            async for chunk in self._model_client.generate_stream(
                system_prompt=context.system_prompt,
                messages=messages,
                tools=tools_payload,
            ):
                if chunk.delta:
                    round_content_parts.append(chunk.delta)
                    round_content_deltas.append(chunk.delta)

                if chunk.finished:
                    resolved_tool_calls = self._ensure_tool_call_ids(chunk.tool_calls or [])

            round_content = "".join(round_content_parts).strip()
            _logger.debug(
                "流式模型调用完成: session_id=%s round=%s content_len=%s tool_call_count=%s",
                session_id,
                round_index,
                len(round_content),
                len(resolved_tool_calls),
            )

            if not resolved_tool_calls:
                answer = round_content
                if round_content_deltas:
                    emitted_answer_meta: tuple[str, str, str, str, str] | None = None
                    cumulative_parts: list[str] = []
                    for delta in round_content_deltas:
                        cumulative_parts.append(delta)
                        emitted_answer_meta = await self._emit_stream_answer_meta_if_changed(
                            channel=channel,
                            content="".join(cumulative_parts),
                            tool_calls=used_tool_calls,
                            previous_meta=emitted_answer_meta,
                        )
                        await channel.emit("answer_delta", {"delta": delta})
                if not answer:
                    answer = await self._recover_final_answer_stream(
                        system_prompt=context.system_prompt,
                        messages=messages,
                        original_user_message=run_input.user_message,
                        previous_tool_calls=used_tool_calls,
                        channel=channel,
                    )
                answer = answer or "(no answer)"
                break

            if round_index == run_input.max_tool_rounds:
                _logger.warning("达到工具调用上限(流式): session_id=%s round=%s", session_id, round_index)
                answer = "Tool call limit reached before generating final answer."
                break

            if round_content:
                await self._event_recorder.record_async(
                    context=run_context,
                    event_type="assistant_thinking",
                    payload={"content": round_content},
                    channel=channel,
                )

            messages.append(self._build_assistant_tool_call_message(round_content, resolved_tool_calls))

            for tool_call in resolved_tool_calls:
                used_tool_calls.append(tool_call)
                await self._event_recorder.record_async(
                    context=run_context,
                    event_type="tool_call",
                    payload={
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "tool_call_id": tool_call.tool_call_id,
                    },
                    channel=channel,
                )
                result = await self._execute_tool_safely_async(tool_call, run_context)
                _logger.info(
                    "流式工具调用完成: session_id=%s tool=%s success=%s content_len=%s",
                    session_id,
                    tool_call.name,
                    result.success,
                    len(result.content),
                )
                await self._event_recorder.record_async(
                    context=run_context,
                    event_type="tool_result",
                    payload={
                        "tool_name": result.tool_name,
                        "success": result.success,
                        "content": result.content,
                        "tool_call_id": tool_call.tool_call_id,
                    },
                    channel=channel,
                )
                if tool_call.name == "memory_write" and result.success:
                    await self._event_recorder.record_async(
                        context=run_context,
                        event_type="memory_write",
                        payload={
                            "arguments": tool_call.arguments,
                            "result": result.content,
                        },
                        channel=channel,
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.tool_call_id,
                        "content": result.content,
                    }
                )

        if not answer:
            answer = "(no answer)"

        await self._event_recorder.record_async(
            context=run_context,
            event_type="assistant_message",
            payload={"content": answer},
            channel=channel,
        )
        await self._event_recorder.record_async(
            context=run_context,
            event_type="run_finished",
            payload={"answer_length": len(answer), "tool_calls": len(used_tool_calls)},
            channel=channel,
        )
        self._dispatch_post_run_maintenance_async(run_context)
        _logger.info(
            "流式 agent run 完成: session_id=%s answer_len=%s tool_calls=%s",
            session_id,
            len(answer),
            len(used_tool_calls),
        )

        return AgentRunOutput(
            session_id=session_id,
            answer=answer,
            tool_calls=used_tool_calls,
            memory_hits=context.memory_hits,
        )

    def _execute_tool_safely(self, call: ToolCall, context: RunContext) -> ToolExecutionResult:
        try:
            return self._tool_executor.execute(call, context)
        except ToolExecutionError as exc:
            _logger.warning(
                "工具执行失败: session_id=%s agent_id=%s tool=%s error=%s",
                context.session_id,
                context.agent_id,
                call.name,
                exc,
            )
            return ToolExecutionResult(tool_name=call.name, success=False, content=str(exc))
        except AppError as exc:
            _logger.warning(
                "工具执行失败(应用错误): session_id=%s agent_id=%s tool=%s error=%s",
                context.session_id,
                context.agent_id,
                call.name,
                exc,
            )
            return ToolExecutionResult(tool_name=call.name, success=False, content=str(exc))
        except Exception as exc:
            _logger.exception(
                "工具执行异常: session_id=%s agent_id=%s tool=%s",
                context.session_id,
                context.agent_id,
                call.name,
            )
            return ToolExecutionResult(
                tool_name=call.name,
                success=False,
                content=f"Unexpected tool error: {exc}",
            )

    async def _execute_tool_safely_async(self, call: ToolCall, context: RunContext) -> ToolExecutionResult:
        return await asyncio.to_thread(self._execute_tool_safely, call, context)

    def _dispatch_post_run_maintenance_sync(self, context: RunContext) -> None:
        if self._mid_term_flusher is None and self._context_compactor is None:
            return
        if not self._schedule_post_run_maintenance(context):
            return
        thread = threading.Thread(
            target=self._run_post_run_maintenance_worker,
            args=(context,),
            daemon=True,
            name=f"post-run-maintenance:{context.session_id}:{context.agent_id}",
        )
        thread.start()

    def _dispatch_post_run_maintenance_async(self, context: RunContext) -> None:
        if self._mid_term_flusher is None and self._context_compactor is None:
            return
        if not self._schedule_post_run_maintenance(context):
            return
        try:
            asyncio.create_task(
                self._run_post_run_maintenance_async(context),
                name=f"post-run-maintenance:{context.session_id}:{context.agent_id}",
            )
        except RuntimeError:
            # 没有活动事件循环时回退到后台线程，避免丢失维护任务。
            thread = threading.Thread(
                target=self._run_post_run_maintenance_worker,
                args=(context,),
                daemon=True,
                name=f"post-run-maintenance:{context.session_id}:{context.agent_id}",
            )
            thread.start()

    def _schedule_post_run_maintenance(self, context: RunContext) -> bool:
        key = self._post_run_maintenance_key(context)
        with self._post_run_maintenance_lock:
            state = self._post_run_maintenance_states.get(key)
            if state is None:
                state = _PostRunMaintenanceState()
                self._post_run_maintenance_states[key] = state

            state.latest_context = context
            if state.active:
                state.pending = True
                return False

            state.active = True
            state.pending = False
            return True

    def _post_run_maintenance_key(self, context: RunContext) -> tuple[str, str]:
        return (context.session_id, context.agent_id)

    def _run_post_run_maintenance_worker(self, initial_context: RunContext) -> None:
        context = initial_context
        while True:
            try:
                self._run_post_run_maintenance_once(context)
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "post-run maintenance crashed: session_id=%s agent_id=%s",
                    context.session_id,
                    context.agent_id,
                )

            key = self._post_run_maintenance_key(context)
            with self._post_run_maintenance_lock:
                state = self._post_run_maintenance_states.get(key)
                if state is None:
                    return
                if state.pending and state.latest_context is not None:
                    context = state.latest_context
                    state.pending = False
                    continue
                del self._post_run_maintenance_states[key]
                return

    def _run_post_run_maintenance_once(self, context: RunContext) -> None:
        flush_allows_compaction = self._flush_mid_term_after_run_finished(context)
        if not flush_allows_compaction:
            _logger.debug(
                "context compaction skipped because mid-term flush is not complete: session_id=%s agent_id=%s",
                context.session_id,
                context.agent_id,
            )
            return
        self._compact_context_after_flush(context)

    async def _run_post_run_maintenance_async(self, context: RunContext) -> None:
        await asyncio.to_thread(self._run_post_run_maintenance_worker, context)

    def _flush_mid_term_after_run_finished(self, context: RunContext) -> bool:
        if self._mid_term_flusher is None:
            return True
        try:
            result = self._mid_term_flusher.flush_for_run_finished(context)
            _logger.debug(
                "mid-term flush: session_id=%s agent_id=%s flushed=%s reason=%s events=%s score=%s path=%s",
                context.session_id,
                context.agent_id,
                result.flushed,
                result.reason,
                result.event_count,
                result.signal_score,
                result.daily_path,
            )
            return result.flushed or result.reason in {
                "no_agent_events",
                "no_new_events",
                "threshold_not_met",
                "empty_semantic_units",
                "empty_event_batch",
            }
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "mid-term flush failed: session_id=%s agent_id=%s error=%s",
                context.session_id,
                context.agent_id,
                exc,
            )
            return False

    def _compact_context_after_flush(self, context: RunContext) -> None:
        if self._context_compactor is None:
            return
        try:
            result = self._context_compactor.compact_after_flush(context)
            _logger.debug(
                "context compaction: session_id=%s agent_id=%s compacted=%s reason=%s original_events=%s compressed=%s retained=%s summary=%s",
                context.session_id,
                context.agent_id,
                result.compacted,
                result.reason,
                result.original_event_count,
                result.compressed_event_count,
                result.retained_event_count,
                result.summary_event_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "context compaction failed: session_id=%s agent_id=%s error=%s",
                context.session_id,
                context.agent_id,
                exc,
            )

    def _to_model_tool_schema(self, definition: Any) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": definition.name,
                "description": definition.description,
                "parameters": definition.parameters_schema,
            },
        }

    def _ensure_tool_call_ids(self, tool_calls: list[ToolCall]) -> list[ToolCall]:
        resolved: list[ToolCall] = []
        for call in tool_calls:
            call_id = call.tool_call_id or f"call_{uuid4().hex[:12]}"
            resolved.append(ToolCall(name=call.name, arguments=call.arguments, tool_call_id=call_id))
        return resolved

    def _build_assistant_tool_call_message(self, content: str, tool_calls: list[ToolCall]) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": content or "",
            "tool_calls": [
                {
                    "id": call.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in tool_calls
            ],
        }

    def _recover_final_answer(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        original_user_message: str,
    ) -> str:
        _logger.warning("最终轮未返回正文，触发同步补答: user_message=%s", original_user_message[:120])
        recovery_messages = [
            *messages,
            {
                "role": "user",
                "content": _FINAL_ANSWER_RECOVERY_PROMPT,
            },
        ]
        model_response = self._model_client.generate(
            system_prompt=system_prompt,
            messages=recovery_messages,
            tools=[],
        )
        if model_response.tool_calls:
            _logger.warning("补答轮仍返回 tool_calls，已忽略: tool_call_count=%s", len(model_response.tool_calls))
        return (model_response.content or "").strip()

    async def _recover_final_answer_stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        original_user_message: str,
        previous_tool_calls: list[ToolCall],
        channel: EventChannel,
    ) -> str:
        _logger.warning("最终轮未返回正文，触发流式补答: user_message=%s", original_user_message[:120])
        recovery_messages = [
            *messages,
            {
                "role": "user",
                "content": _FINAL_ANSWER_RECOVERY_PROMPT,
            },
        ]
        parts: list[str] = []
        emitted_answer_meta: tuple[str, str, str, str, str] | None = None
        async for chunk in self._model_client.generate_stream(
            system_prompt=system_prompt,
            messages=recovery_messages,
            tools=[],
        ):
            if chunk.delta:
                parts.append(chunk.delta)
                emitted_answer_meta = await self._emit_stream_answer_meta_if_changed(
                    channel=channel,
                    content="".join(parts),
                    tool_calls=previous_tool_calls,
                    previous_meta=emitted_answer_meta,
                )
                await channel.emit("answer_delta", {"delta": chunk.delta})
        return "".join(parts).strip()

    async def _emit_stream_answer_meta_if_changed(
        self,
        *,
        channel: EventChannel,
        content: str,
        tool_calls: list[ToolCall],
        previous_meta: tuple[str, str, str, str, str] | None,
    ) -> tuple[str, str, str, str, str] | None:
        normalized = self._answer_normalizer.normalize_assistant_message(
            content,
            tool_calls=tool_calls,
        )
        artifact_signature = "|".join(
            f"{item.type}:{item.path}:{item.role}" for item in normalized.artifacts
        )
        current_meta = (
            normalized.answer_format,
            normalized.render_hint,
            normalized.layout_hint,
            normalized.source_kind,
            artifact_signature,
        )
        if current_meta == previous_meta:
            return previous_meta
        await channel.emit(
            "answer_meta",
            {
                "answer_format": normalized.answer_format,
                "render_hint": normalized.render_hint,
                "layout_hint": normalized.layout_hint,
                "source_kind": normalized.source_kind,
                "artifacts": [
                    {
                        "type": item.type,
                        "path": item.path,
                        "role": item.role,
                    }
                    for item in normalized.artifacts
                ],
            },
        )
        return current_meta

    def _resolve_run_context(self, session_id: str, run_input: AgentRunInput) -> RunContext:
        if run_input.context is None:
            raise ValidationError("run_input.context is required.")
        if run_input.context.session_id != session_id:
            raise ValidationError("run_input.context.session_id must match resolved session_id.")
        return run_input.context
