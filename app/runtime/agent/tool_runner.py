"""Safe tool execution wrapper for agent runtime."""

from __future__ import annotations

import asyncio
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
