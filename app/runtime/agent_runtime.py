"""Single-agent run orchestration."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from app.core.errors import AppError, ToolExecutionError, ValidationError
from app.domain.models import AgentRunInput, AgentRunOutput, RunContext, ToolCall, ToolExecutionResult
from app.domain.protocols import ChatModelClient, ToolExecutor
from app.runtime.context_assembler import ContextAssembler
from app.runtime.event_recorder import EventRecorder
from app.runtime.session_manager import SessionManager

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
    ) -> None:
        self._session_manager = session_manager
        self._event_recorder = event_recorder
        self._context_assembler = context_assembler
        self._model_client = model_client
        self._tool_executor = tool_executor

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
            session_id=session_id,
            event_type="run_started",
            payload={"max_tool_rounds": run_input.max_tool_rounds},
            agent_id=run_context.agent_id,
            run_id=run_context.run_id,
            parent_run_id=run_context.parent_run_id,
        )
        self._event_recorder.record(
            session_id=session_id,
            event_type="user_message",
            payload={"content": run_input.user_message},
            agent_id=run_context.agent_id,
            run_id=run_context.run_id,
            parent_run_id=run_context.parent_run_id,
        )

        context = self._context_assembler.assemble(
            session_id=session_id,
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
                answer = (model_response.content or "").strip() or "(no answer)"
                break

            if round_index == run_input.max_tool_rounds:
                _logger.warning("达到工具调用上限: session_id=%s round=%s", session_id, round_index)
                answer = "Tool call limit reached before generating final answer."
                break

            if model_response.content.strip():
                # 一些模型会在 tool_call 前返回推理摘要，记录下来供前端“执行过程/思考”展示。
                self._event_recorder.record(
                    session_id=session_id,
                    event_type="assistant_thinking",
                    payload={"content": model_response.content},
                    agent_id=run_context.agent_id,
                    run_id=run_context.run_id,
                    parent_run_id=run_context.parent_run_id,
                )

            # 遇到工具调用时，必须先把 assistant 的 tool_calls 消息回填到上下文，
            # 后续 tool 角色消息才是协议上合法的。
            messages.append(self._build_assistant_tool_call_message(model_response.content, resolved_tool_calls))

            for tool_call in resolved_tool_calls:
                used_tool_calls.append(tool_call)
                self._event_recorder.record(
                    session_id=session_id,
                    event_type="tool_call",
                    payload={
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "tool_call_id": tool_call.tool_call_id,
                    },
                    agent_id=run_context.agent_id,
                    run_id=run_context.run_id,
                    parent_run_id=run_context.parent_run_id,
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
                    session_id=session_id,
                    event_type="tool_result",
                    payload={
                        "tool_name": result.tool_name,
                        "success": result.success,
                        "content": result.content,
                        "tool_call_id": tool_call.tool_call_id,
                    },
                    agent_id=run_context.agent_id,
                    run_id=run_context.run_id,
                    parent_run_id=run_context.parent_run_id,
                )
                if tool_call.name == "memory_write" and result.success:
                    self._event_recorder.record(
                        session_id=session_id,
                        event_type="memory_write",
                        payload={
                            "arguments": tool_call.arguments,
                            "result": result.content,
                        },
                        agent_id=run_context.agent_id,
                        run_id=run_context.run_id,
                        parent_run_id=run_context.parent_run_id,
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
            session_id=session_id,
            event_type="assistant_message",
            payload={"content": answer},
            agent_id=run_context.agent_id,
            run_id=run_context.run_id,
            parent_run_id=run_context.parent_run_id,
        )
        self._event_recorder.record(
            session_id=session_id,
            event_type="run_finished",
            payload={"answer_length": len(answer), "tool_calls": len(used_tool_calls)},
            agent_id=run_context.agent_id,
            run_id=run_context.run_id,
            parent_run_id=run_context.parent_run_id,
        )
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

    def _resolve_run_context(self, session_id: str, run_input: AgentRunInput) -> RunContext:
        if run_input.context is not None:
            if run_input.context.session_id != session_id:
                raise ValidationError("run_input.context.session_id must match resolved session_id.")
            return run_input.context
        return RunContext(
            session_id=session_id,
            run_id=f"run_{uuid4().hex[:12]}",
            agent_id="agent_main",
            turn_id=f"turn_{uuid4().hex[:12]}",
            entry_agent_id="agent_main",
            parent_run_id=None,
            trace_flags={},
        )
