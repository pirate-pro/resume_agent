"""Tool interface definition."""

from __future__ import annotations

from typing import Any, Protocol

from app.domain.models import RunContext, ToolDefinition, ToolExecutionResult

__all__ = ["Tool"]


class Tool(Protocol):
    def definition(self) -> ToolDefinition: ...

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult: ...
