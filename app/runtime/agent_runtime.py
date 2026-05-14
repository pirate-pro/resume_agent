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
    ToolExecutionRunner,
    build_assistant_tool_call_message,
    build_tool_result_message,
    ensure_tool_call_ids,
    to_model_tool_schema,
)
from app.runtime.context_assembler import ContextAssembler
from app.runtime.context_compaction.text_utils import estimate_tokens_from_object
from app.runtime.context_compactor import ContextCompactor
from app.runtime.event_channel import EventChannel
from app.runtime.event_recorder import EventRecorder
from app.runtime.mid_term_flusher import MidTermFlusher
from app.runtime.session_manager import SessionManager
from app.services.answer_normalizer import AnswerNormalizer

__all__ = ["AgentRuntime"]
_logger = logging.getLogger(__name__)


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

        tools_payload = [to_model_tool_schema(tool) for tool in context.tool_definitions]
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

            resolved_tool_calls = ensure_tool_call_ids(model_response.tool_calls)
            self._record_llm_usage(
                run_context=run_context,
                system_prompt=context.system_prompt,
                messages=messages,
                tools=tools_payload,
                model_response=model_response,
                tool_calls=resolved_tool_calls,
                mode="sync",
                phase="tool_loop",
                round_index=round_index,
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
            messages.append(
                build_assistant_tool_call_message(
                    model_response.content,
                    resolved_tool_calls,
                    reasoning_content=model_response.reasoning_content,
                )
            )

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
                messages.append(build_tool_result_message(tool_call_id=tool_call.tool_call_id, content=result.content))

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

        tools_payload = [to_model_tool_schema(tool) for tool in context.tool_definitions]
        messages = list(context.messages)
        used_tool_calls: list[ToolCall] = []
        answer = ""

        for round_index in range(run_input.max_tool_rounds + 1):
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

            messages.append(
                build_assistant_tool_call_message(
                    round_content,
                    resolved_tool_calls,
                    reasoning_content=round_reasoning,
                )
            )

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
                messages.append(build_tool_result_message(tool_call_id=tool_call.tool_call_id, content=result.content))

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
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model_response: ModelResponse,
        tool_calls: list[ToolCall],
        mode: str,
        phase: str,
        round_index: int | None,
    ) -> None:
        payload = _build_llm_usage_payload(
            system_prompt=system_prompt,
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
    ) -> None:
        payload = _build_llm_usage_payload(
            system_prompt=system_prompt,
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


def _build_llm_usage_payload(
    *,
    system_prompt: str,
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
    return payload


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
