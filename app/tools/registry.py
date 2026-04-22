"""Tool registry and execution dispatch."""

from __future__ import annotations

import logging

from app.core.errors import ToolExecutionError, ValidationError
from app.domain.models import RunContext, ToolCall, ToolDefinition, ToolExecutionResult
from app.runtime.agent_capability import AgentCapabilityRegistry
from app.tools.base import Tool

__all__ = ["ToolRegistry"]
_logger = logging.getLogger(__name__)


class ToolRegistry:
    """Register tools and execute them by name."""

    def __init__(self, capability_registry: AgentCapabilityRegistry) -> None:
        self._capability_registry = capability_registry
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        definition = tool.definition()
        if definition.name in self._tools:
            raise ValidationError(f"Tool already registered: {definition.name}")
        self._tools[definition.name] = tool
        _logger.debug("注册工具成功: tool=%s", definition.name)

    def list_definitions(self) -> list[ToolDefinition]:
        return [tool.definition() for tool in self._tools.values()]

    def execute(self, call: ToolCall, context: RunContext) -> ToolExecutionResult:
        if not isinstance(call, ToolCall):
            raise ValidationError("call must be a ToolCall instance.")
        if not isinstance(context, RunContext):
            raise ValidationError("context must be a RunContext instance.")
        tool = self._tools.get(call.name)
        if tool is None:
            raise ToolExecutionError(f"Tool not found: {call.name}")
        capability = self._capability_registry.require(context.agent_id)
        if not capability.allows_tool(call.name):
            raise ToolExecutionError(f"Tool not allowed for agent '{context.agent_id}': {call.name}")
        _logger.debug("开始执行工具: session_id=%s agent_id=%s tool=%s", context.session_id, context.agent_id, call.name)
        try:
            result = tool.execute(call.arguments, context=context)
            _logger.debug(
                "工具执行结束: session_id=%s agent_id=%s tool=%s success=%s",
                context.session_id,
                context.agent_id,
                call.name,
                result.success,
            )
            return result
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"Tool '{call.name}' execution failed: {exc}") from exc
