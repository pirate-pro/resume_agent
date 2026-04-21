"""Tool registry and execution dispatch."""

from __future__ import annotations

import logging

from app.core.errors import ToolExecutionError, ValidationError
from app.domain.models import ToolCall, ToolDefinition, ToolExecutionResult
from app.tools.base import Tool

__all__ = ["ToolRegistry"]
_logger = logging.getLogger(__name__)


class ToolRegistry:
    """Register tools and execute them by name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        definition = tool.definition()
        if definition.name in self._tools:
            raise ValidationError(f"Tool already registered: {definition.name}")
        self._tools[definition.name] = tool
        _logger.debug("注册工具成功: tool=%s", definition.name)

    def list_definitions(self) -> list[ToolDefinition]:
        return [tool.definition() for tool in self._tools.values()]

    def execute(self, call: ToolCall, session_id: str) -> ToolExecutionResult:
        if not isinstance(call, ToolCall):
            raise ValidationError("call must be a ToolCall instance.")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        tool = self._tools.get(call.name)
        if tool is None:
            raise ToolExecutionError(f"Tool not found: {call.name}")
        _logger.debug("开始执行工具: session_id=%s tool=%s", session_id, call.name)
        try:
            result = tool.execute(call.arguments, session_id=session_id.strip())
            _logger.debug("工具执行结束: session_id=%s tool=%s success=%s", session_id, call.name, result.success)
            return result
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"Tool '{call.name}' execution failed: {exc}") from exc
