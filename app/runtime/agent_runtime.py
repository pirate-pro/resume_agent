"""Single-agent run orchestration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.errors import ValidationError
from app.domain.models import AgentRunInput, AgentRunOutput, RunContext, ToolCall
from app.domain.protocols import ChatModelClient, ModelResponse, TokenUsage, ToolExecutor
from app.prompts.agent_runtime import FINAL_ANSWER_RECOVERY_PROMPT
from app.runtime.agent import (
    PostRunMaintenanceScheduler,
    ToolContextWindow,
    ToolExecutionRunner,
    build_assistant_tool_call_message,
    build_tool_result_message,
    build_tool_observation,
    compact_tool_result_for_model,
    ensure_tool_call_ids,
    normalize_tool_context_window_mode,
    to_model_tool_schema,
)
from app.runtime.agent.tool_reveal import (
    ToolRevealState,
    hidden_tool_result,
    normalize_always_visible_tool_names,
    normalize_tool_schema_disclosure_mode,
)
from app.runtime.context_assembler import ContextAssembler
from app.runtime.context_compaction.text_utils import estimate_tokens_from_object, estimate_tokens_from_text
from app.runtime.context_compactor import ContextCompactor
from app.runtime.event_channel import EventChannel
from app.runtime.event_recorder import EventRecorder
from app.runtime.mid_term_flusher import MidTermFlusher
from app.runtime.session_manager import SessionManager
from app.services.answer_normalizer import AnswerNormalizer

__all__ = ["AgentRuntime"]
_logger = logging.getLogger(__name__)
_SCHEMA_SEARCH_TOOL_NAME = "tool_search"
_MAX_SCHEMA_SEARCH_ROUNDS = 3


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
        tool_schema_disclosure_mode: str = "full",
        tool_schema_always_visible: str | list[str] | None = None,
        tool_context_window_mode: str = "off",
    ) -> None:
        self._session_manager = session_manager
        self._event_recorder = event_recorder
        self._context_assembler = context_assembler
        self._model_client = model_client
        self._tool_executor = tool_executor
        self._mid_term_flusher = mid_term_flusher
        self._context_compactor = context_compactor
        self._tool_schema_disclosure_mode = normalize_tool_schema_disclosure_mode(tool_schema_disclosure_mode)
        self._tool_schema_always_visible = normalize_always_visible_tool_names(tool_schema_always_visible)
        self._tool_context_window_mode = normalize_tool_context_window_mode(tool_context_window_mode)
        self._answer_normalizer = AnswerNormalizer()
        self._tool_runner = ToolExecutionRunner(tool_executor=tool_executor)
        self._post_run_maintenance = PostRunMaintenanceScheduler(
            mid_term_flusher_provider=lambda: self._mid_term_flusher,
            context_compactor_provider=lambda: self._context_compactor,
        )

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

        tool_reveal_state = ToolRevealState.create(
            mode=self._tool_schema_disclosure_mode_for_context(run_context),
            available_definitions=context.tool_definitions,
            always_visible_tool_names=self._tool_schema_always_visible,
        )
        tool_context_window = ToolContextWindow(
            base_messages=list(context.messages),
            mode=self._tool_context_window_mode,
        )
        used_tool_calls: list[ToolCall] = []
        answer = ""

        # `max_tool_rounds` 约束业务工具轮次；纯 tool_search 只是 schema 揭示，
        # 单独给少量额外轮次，避免 search 模式天然少一次业务动作。
        round_index = 0
        business_tool_rounds = 0
        schema_search_rounds = 0
        max_model_rounds = run_input.max_tool_rounds + _MAX_SCHEMA_SEARCH_ROUNDS + 1
        while round_index <= max_model_rounds:
            messages = tool_context_window.render_messages()
            visible_tool_definitions = tool_reveal_state.visible_definitions()
            tools_payload = [to_model_tool_schema(tool) for tool in visible_tool_definitions]
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

            resolved_tool_calls = ensure_tool_call_ids(model_response.tool_calls)
            self._record_llm_usage(
                run_context=run_context,
                system_prompt=context.system_prompt,
                system_prompt_sections=context.system_prompt_sections,
                messages=messages,
                tools=tools_payload,
                model_response=model_response,
                tool_calls=resolved_tool_calls,
                mode="sync",
                phase="tool_loop",
                round_index=round_index,
                tool_disclosure=tool_reveal_state.usage_payload(visible_definitions=visible_tool_definitions),
                tool_context=tool_context_window.usage_payload(),
            )

            if not resolved_tool_calls:
                answer = (model_response.content or "").strip()
                if not answer:
                    answer = self._recover_final_answer(
                        run_context=run_context,
                        system_prompt=context.system_prompt,
                        messages=messages,
                        original_user_message=run_input.user_message,
                    )
                answer = answer or "(no answer)"
                break

            schema_search_only = _is_schema_search_only(resolved_tool_calls)
            if schema_search_only:
                if schema_search_rounds >= _MAX_SCHEMA_SEARCH_ROUNDS:
                    _logger.warning("达到工具 schema 搜索轮次上限: session_id=%s round=%s", session_id, round_index)
                    answer = "Tool schema search limit reached before generating final answer."
                    break
                schema_search_rounds += 1
            elif business_tool_rounds >= run_input.max_tool_rounds:
                _logger.warning("达到工具调用上限: session_id=%s round=%s", session_id, round_index)
                answer = "Tool call limit reached before generating final answer."
                break
            else:
                business_tool_rounds += 1

            if model_response.content.strip():
                # 一些模型会在 tool_call 前返回推理摘要，记录下来供前端“执行过程/思考”展示。
                self._event_recorder.record(
                    context=run_context,
                    event_type="assistant_thinking",
                    payload={"content": model_response.content},
                )

            # 遇到工具调用时，必须先把 assistant 的 tool_calls 消息回填到上下文，
            # 后续 tool 角色消息才是协议上合法的。
            assistant_tool_call_message = build_assistant_tool_call_message(
                model_response.content,
                resolved_tool_calls,
                reasoning_content=model_response.reasoning_content,
            )
            tool_context_window.consume_pending_exchange()
            tool_messages: list[dict[str, Any]] = []
            tool_observations = []

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
                if not tool_reveal_state.is_visible(tool_call.name):
                    result = hidden_tool_result(tool_call.name)
                else:
                    result = self._tool_runner.execute_safely(tool_call, run_context)
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
                if tool_call.name == "tool_search" and result.success:
                    tool_reveal_state.apply_tool_search_result(result.content)
                model_visible_content = compact_tool_result_for_model(
                    tool_name=result.tool_name,
                    success=result.success,
                    content=result.content,
                )
                tool_message = (
                    build_tool_result_message(
                        tool_call_id=tool_call.tool_call_id,
                        content=model_visible_content,
                    )
                )
                tool_messages.append(tool_message)
                tool_observations.append(
                    build_tool_observation(
                        tool_call=tool_call,
                        result=result,
                        model_visible_content=model_visible_content,
                    )
                )

            tool_context_window.set_pending_exchange(
                assistant_message=assistant_tool_call_message,
                tool_messages=tool_messages,
                observations=tool_observations,
            )
            round_index += 1

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

        tool_reveal_state = ToolRevealState.create(
            mode=self._tool_schema_disclosure_mode_for_context(run_context),
            available_definitions=context.tool_definitions,
            always_visible_tool_names=self._tool_schema_always_visible,
        )
        tool_context_window = ToolContextWindow(
            base_messages=list(context.messages),
            mode=self._tool_context_window_mode,
        )
        used_tool_calls: list[ToolCall] = []
        answer = ""

        round_index = 0
        business_tool_rounds = 0
        schema_search_rounds = 0
        max_model_rounds = run_input.max_tool_rounds + _MAX_SCHEMA_SEARCH_ROUNDS + 1
        while round_index <= max_model_rounds:
            messages = tool_context_window.render_messages()
            visible_tool_definitions = tool_reveal_state.visible_definitions()
            tools_payload = [to_model_tool_schema(tool) for tool in visible_tool_definitions]
            _logger.debug("流式模型调用开始: session_id=%s round=%s message_count=%s", session_id, round_index, len(messages))
            round_content_parts: list[str] = []
            round_content_deltas: list[str] = []
            round_reasoning_parts: list[str] = []
            resolved_tool_calls: list[ToolCall] = []
            round_usage: TokenUsage | None = None
            round_model: str | None = None

            async for chunk in self._model_client.generate_stream(
                system_prompt=context.system_prompt,
                messages=messages,
                tools=tools_payload,
            ):
                if chunk.delta:
                    round_content_parts.append(chunk.delta)
                    round_content_deltas.append(chunk.delta)
                if chunk.reasoning_delta:
                    round_reasoning_parts.append(chunk.reasoning_delta)
                if chunk.usage is not None:
                    round_usage = chunk.usage
                if chunk.model:
                    round_model = chunk.model

                if chunk.finished:
                    resolved_tool_calls = ensure_tool_call_ids(chunk.tool_calls or [])

            round_content = "".join(round_content_parts).strip()
            round_reasoning = "".join(round_reasoning_parts).strip()
            _logger.debug(
                "流式模型调用完成: session_id=%s round=%s content_len=%s tool_call_count=%s",
                session_id,
                round_index,
                len(round_content),
                len(resolved_tool_calls),
            )
            await self._record_llm_usage_async(
                run_context=run_context,
                system_prompt=context.system_prompt,
                system_prompt_sections=context.system_prompt_sections,
                messages=messages,
                tools=tools_payload,
                content=round_content,
                reasoning_content=round_reasoning,
                tool_calls=resolved_tool_calls,
                usage=round_usage,
                model=round_model,
                mode="stream",
                phase="tool_loop",
                round_index=round_index,
                channel=channel,
                tool_disclosure=tool_reveal_state.usage_payload(visible_definitions=visible_tool_definitions),
                tool_context=tool_context_window.usage_payload(),
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
                        run_context=run_context,
                        system_prompt=context.system_prompt,
                        messages=messages,
                        original_user_message=run_input.user_message,
                        previous_tool_calls=used_tool_calls,
                        channel=channel,
                    )
                answer = answer or "(no answer)"
                break

            schema_search_only = _is_schema_search_only(resolved_tool_calls)
            if schema_search_only:
                if schema_search_rounds >= _MAX_SCHEMA_SEARCH_ROUNDS:
                    _logger.warning("达到工具 schema 搜索轮次上限(流式): session_id=%s round=%s", session_id, round_index)
                    answer = "Tool schema search limit reached before generating final answer."
                    break
                schema_search_rounds += 1
            elif business_tool_rounds >= run_input.max_tool_rounds:
                _logger.warning("达到工具调用上限(流式): session_id=%s round=%s", session_id, round_index)
                answer = "Tool call limit reached before generating final answer."
                break
            else:
                business_tool_rounds += 1

            if round_content:
                await self._event_recorder.record_async(
                    context=run_context,
                    event_type="assistant_thinking",
                    payload={"content": round_content},
                    channel=channel,
                )

            assistant_tool_call_message = build_assistant_tool_call_message(
                round_content,
                resolved_tool_calls,
                reasoning_content=round_reasoning,
            )
            tool_context_window.consume_pending_exchange()
            tool_messages: list[dict[str, Any]] = []
            tool_observations = []

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
                if not tool_reveal_state.is_visible(tool_call.name):
                    result = hidden_tool_result(tool_call.name)
                else:
                    result = await self._tool_runner.execute_safely_async(tool_call, run_context)
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
                if tool_call.name == "tool_search" and result.success:
                    tool_reveal_state.apply_tool_search_result(result.content)
                model_visible_content = compact_tool_result_for_model(
                    tool_name=result.tool_name,
                    success=result.success,
                    content=result.content,
                )
                tool_message = (
                    build_tool_result_message(
                        tool_call_id=tool_call.tool_call_id,
                        content=model_visible_content,
                    )
                )
                tool_messages.append(tool_message)
                tool_observations.append(
                    build_tool_observation(
                        tool_call=tool_call,
                        result=result,
                        model_visible_content=model_visible_content,
                    )
                )

            tool_context_window.set_pending_exchange(
                assistant_message=assistant_tool_call_message,
                tool_messages=tool_messages,
                observations=tool_observations,
            )
            round_index += 1

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

    def _dispatch_post_run_maintenance_sync(self, context: RunContext) -> None:
        self._post_run_maintenance.dispatch_sync(context)

    def _dispatch_post_run_maintenance_async(self, context: RunContext) -> None:
        self._post_run_maintenance.dispatch_async(context)

    def _recover_final_answer(
        self,
        *,
        run_context: RunContext,
        system_prompt: str,
        messages: list[dict[str, Any]],
        original_user_message: str,
    ) -> str:
        _logger.warning("最终轮未返回正文，触发同步补答: user_message=%s", original_user_message[:120])
        recovery_messages = [
            *messages,
            {
                "role": "user",
                "content": FINAL_ANSWER_RECOVERY_PROMPT,
            },
        ]
        model_response = self._model_client.generate(
            system_prompt=system_prompt,
            messages=recovery_messages,
            tools=[],
        )
        self._record_llm_usage(
            run_context=run_context,
            system_prompt=system_prompt,
            messages=recovery_messages,
            tools=[],
            model_response=model_response,
            tool_calls=ensure_tool_call_ids(model_response.tool_calls),
            mode="sync",
            phase="final_answer_recovery",
            round_index=None,
        )
        if model_response.tool_calls:
            _logger.warning("补答轮仍返回 tool_calls，已忽略: tool_call_count=%s", len(model_response.tool_calls))
        return (model_response.content or "").strip()

    async def _recover_final_answer_stream(
        self,
        *,
        run_context: RunContext,
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
                "content": FINAL_ANSWER_RECOVERY_PROMPT,
            },
        ]
        parts: list[str] = []
        reasoning_parts: list[str] = []
        usage: TokenUsage | None = None
        model: str | None = None
        resolved_tool_calls: list[ToolCall] = []
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
            if chunk.reasoning_delta:
                reasoning_parts.append(chunk.reasoning_delta)
            if chunk.usage is not None:
                usage = chunk.usage
            if chunk.model:
                model = chunk.model
            if chunk.finished:
                resolved_tool_calls = ensure_tool_call_ids(chunk.tool_calls or [])
        await self._record_llm_usage_async(
            run_context=run_context,
            system_prompt=system_prompt,
            messages=recovery_messages,
            tools=[],
            content="".join(parts).strip(),
            reasoning_content="".join(reasoning_parts).strip(),
            tool_calls=resolved_tool_calls,
            usage=usage,
            model=model,
            mode="stream",
            phase="final_answer_recovery",
            round_index=None,
            channel=channel,
        )
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

    def _record_llm_usage(
        self,
        *,
        run_context: RunContext,
        system_prompt: str,
        system_prompt_sections: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model_response: ModelResponse,
        tool_calls: list[ToolCall],
        mode: str,
        phase: str,
        round_index: int | None,
        tool_disclosure: dict[str, Any] | None = None,
        tool_context: dict[str, Any] | None = None,
    ) -> None:
        payload = _build_llm_usage_payload(
            system_prompt=system_prompt,
            system_prompt_sections=system_prompt_sections,
            messages=messages,
            tools=tools,
            content=model_response.content,
            reasoning_content=model_response.reasoning_content,
            tool_calls=tool_calls,
            usage=model_response.usage,
            model=model_response.model or _client_model_name(self._model_client),
            mode=mode,
            phase=phase,
            round_index=round_index,
            tool_disclosure=tool_disclosure,
            tool_context=tool_context,
        )
        self._event_recorder.record(
            context=run_context,
            event_type="llm_usage",
            payload=payload,
        )

    async def _record_llm_usage_async(
        self,
        *,
        run_context: RunContext,
        system_prompt: str,
        system_prompt_sections: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        content: str,
        reasoning_content: str,
        tool_calls: list[ToolCall],
        usage: TokenUsage | None,
        model: str | None,
        mode: str,
        phase: str,
        round_index: int | None,
        channel: EventChannel,
        tool_disclosure: dict[str, Any] | None = None,
        tool_context: dict[str, Any] | None = None,
    ) -> None:
        payload = _build_llm_usage_payload(
            system_prompt=system_prompt,
            system_prompt_sections=system_prompt_sections,
            messages=messages,
            tools=tools,
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            usage=usage,
            model=model or _client_model_name(self._model_client),
            mode=mode,
            phase=phase,
            round_index=round_index,
            tool_disclosure=tool_disclosure,
            tool_context=tool_context,
        )
        await self._event_recorder.record_async(
            context=run_context,
            event_type="llm_usage",
            payload=payload,
            channel=channel,
        )

    def _resolve_run_context(self, session_id: str, run_input: AgentRunInput) -> RunContext:
        if run_input.context is None:
            raise ValidationError("run_input.context is required.")
        if run_input.context.session_id != session_id:
            raise ValidationError("run_input.context.session_id must match resolved session_id.")
        return run_input.context

    def _tool_schema_disclosure_mode_for_context(self, context: RunContext) -> str:
        if self._tool_schema_disclosure_mode != "search":
            return "full"
        if context.agent_id == "agent_main" and context.agent_id == context.entry_agent_id:
            return "search"
        return "full"


def _is_schema_search_only(tool_calls: list[ToolCall]) -> bool:
    return bool(tool_calls) and all(tool_call.name == _SCHEMA_SEARCH_TOOL_NAME for tool_call in tool_calls)


def _build_llm_usage_payload(
    *,
    system_prompt: str,
    system_prompt_sections: list[dict[str, Any]] | None = None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    content: str,
    reasoning_content: str,
    tool_calls: list[ToolCall],
    usage: TokenUsage | None,
    model: str | None,
    mode: str,
    phase: str,
    round_index: int | None,
    tool_disclosure: dict[str, Any] | None = None,
    tool_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_usage = usage or _estimate_usage(
        system_prompt=system_prompt,
        messages=messages,
        tools=tools,
        content=content,
        reasoning_content=reasoning_content,
        tool_calls=tool_calls,
    )
    payload: dict[str, Any] = {
        "api": "POST /v1/chat/completions",
        "operation": "model.generate_stream" if mode == "stream" else "model.generate",
        "mode": mode,
        "phase": phase,
        "round_index": round_index,
        "model": model or "unknown",
        "prompt_tokens": normalized_usage.prompt_tokens,
        "completion_tokens": normalized_usage.completion_tokens,
        "total_tokens": normalized_usage.total_tokens,
        "estimated": normalized_usage.estimated,
        "usage_source": normalized_usage.source,
        "message_count": len(messages) + 1,
        "tool_schema_count": len(tools),
        "returned_tool_call_count": len(tool_calls),
        "content_chars": len(content or ""),
        "reasoning_chars": len(reasoning_content or ""),
    }
    payload.update(
        _estimate_prompt_breakdown(
            system_prompt=system_prompt,
            system_prompt_sections=system_prompt_sections,
            messages=messages,
            tools=tools,
        )
    )
    if tool_disclosure:
        payload.update(tool_disclosure)
    if tool_context:
        payload.update(tool_context)
    return payload


def _estimate_prompt_breakdown(
    *,
    system_prompt: str,
    system_prompt_sections: list[dict[str, Any]] | None = None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    message_tokens_by_role = {
        "assistant": 0,
        "other": 0,
        "tool": 0,
        "user": 0,
    }
    for message in messages:
        role = str(message.get("role") or "other")
        role_key = role if role in message_tokens_by_role else "other"
        message_tokens_by_role[role_key] += estimate_tokens_from_object(message)

    system_tokens = estimate_tokens_from_text(system_prompt)
    section_items = _normalize_system_prompt_sections(system_prompt_sections or [])
    workflow_rule_sections = [item for item in section_items if item.get("name") == "workflow_rules"]
    workflow_rule_pack_names: list[str] = []
    workflow_rule_selection_mode = "none"
    workflow_rules_tokens = 0
    for section in workflow_rule_sections:
        workflow_rules_tokens += _safe_int(section.get("tokens"))
        raw_mode = section.get("selection_mode")
        if isinstance(raw_mode, str) and raw_mode.strip():
            workflow_rule_selection_mode = raw_mode.strip()
        raw_pack_names = section.get("pack_names")
        if isinstance(raw_pack_names, list):
            for name in raw_pack_names:
                normalized_name = str(name).strip()
                if normalized_name and normalized_name not in workflow_rule_pack_names:
                    workflow_rule_pack_names.append(normalized_name)
    messages_tokens = estimate_tokens_from_object(messages)
    tools_tokens = estimate_tokens_from_object(tools) if tools else 0
    prompt_estimate_total = estimate_tokens_from_object(
        {
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "tools": tools,
        }
        if tools
        else {"messages": [{"role": "system", "content": system_prompt}, *messages]}
    )
    return {
        "prompt_estimate_total_tokens": prompt_estimate_total,
        "system_prompt_estimate_tokens": system_tokens,
        "system_prompt_section_count": len(section_items),
        "system_prompt_sections": section_items,
        "messages_estimate_tokens": messages_tokens,
        "tools_estimate_tokens": tools_tokens,
        "message_user_estimate_tokens": message_tokens_by_role["user"],
        "message_assistant_estimate_tokens": message_tokens_by_role["assistant"],
        "message_tool_estimate_tokens": message_tokens_by_role["tool"],
        "message_other_estimate_tokens": message_tokens_by_role["other"],
        "workflow_rule_selection_mode": workflow_rule_selection_mode,
        "workflow_rule_pack_names": workflow_rule_pack_names,
        "workflow_rules_estimate_tokens": workflow_rules_tokens,
    }


def _normalize_system_prompt_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in sections:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        section = {
            "name": name,
            "tokens": _safe_int(item.get("tokens")),
            "chars": _safe_int(item.get("chars")),
            "item_count": _safe_int(item.get("item_count")),
        }
        pack_names = item.get("pack_names")
        if isinstance(pack_names, list):
            section["pack_names"] = [str(pack_name) for pack_name in pack_names if str(pack_name).strip()]
        selection_mode = item.get("selection_mode")
        if isinstance(selection_mode, str) and selection_mode.strip():
            section["selection_mode"] = selection_mode.strip()
        normalized.append(section)
    return normalized


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _estimate_usage(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    content: str,
    reasoning_content: str,
    tool_calls: list[ToolCall],
) -> TokenUsage:
    prompt_payload: dict[str, Any] = {
        "messages": [{"role": "system", "content": system_prompt}, *messages],
    }
    if tools:
        prompt_payload["tools"] = tools
    completion_payload: dict[str, Any] = {
        "content": content,
        "reasoning_content": reasoning_content,
        "tool_calls": [
            {
                "id": item.tool_call_id,
                "name": item.name,
                "arguments": item.arguments,
            }
            for item in tool_calls
        ],
    }
    prompt_tokens = estimate_tokens_from_object(prompt_payload)
    completion_tokens = estimate_tokens_from_object(completion_payload)
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        estimated=True,
        source="estimate",
    )


def _client_model_name(client: ChatModelClient) -> str | None:
    raw = getattr(client, "model", None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    raw = getattr(client, "_model", None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None
