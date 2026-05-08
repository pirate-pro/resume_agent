"""Safe tool execution wrapper for agent runtime."""

from __future__ import annotations

import asyncio
import json
import logging

from app.core.errors import AppError, ToolExecutionError
from app.domain.models import RunContext, ToolCall, ToolExecutionResult
from app.domain.protocols import ToolExecutor

__all__ = ["ToolExecutionRunner"]

_logger = logging.getLogger(__name__)


class ToolExecutionRunner:
    """Execute tools and normalize failures into tool result messages."""

    def __init__(self, tool_executor: ToolExecutor) -> None:
        self._tool_executor = tool_executor

    def execute_safely(self, call: ToolCall, context: RunContext) -> ToolExecutionResult:
        try:
            return self._tool_executor.execute(call, context)
        except ToolExecutionError as exc:
            if _is_direct_child_agent_tool_call(call.name, exc):
                _logger.warning(
                    "模型误将 child-agent 当作工具调用: session_id=%s agent_id=%s tool=%s",
                    context.session_id,
                    context.agent_id,
                    call.name,
                )
                return _direct_child_agent_tool_result(call.name)
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

    async def execute_safely_async(self, call: ToolCall, context: RunContext) -> ToolExecutionResult:
        return await asyncio.to_thread(self.execute_safely, call, context)


def _is_direct_child_agent_tool_call(tool_name: str, exc: ToolExecutionError) -> bool:
    return tool_name.endswith("_agent") and str(exc) == f"Tool not found: {tool_name}"


def _direct_child_agent_tool_result(tool_name: str) -> ToolExecutionResult:
    content = json.dumps(
        {
            "handled": True,
            "recoverable": True,
            "error_type": "direct_child_agent_tool_call",
            "tool_name": tool_name,
            "message": (
                "Child-agent ids are not callable tool names. Use delegate_agents with "
                "tasks[].target_agent_id, or reuse existing delegate_agents results/list tools "
                "when the child task is already complete."
            ),
        },
        ensure_ascii=False,
    )
    return ToolExecutionResult(tool_name=tool_name, success=True, content=content)
