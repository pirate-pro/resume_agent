"""Built-in tool for discovering available runtime tools."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from app.core.errors import ToolExecutionError
from app.domain.models import RunContext, ToolDefinition, ToolExecutionResult
from app.runtime.tool_catalog import ToolCatalog
from app.tools.builtin_tools.common import validate_context

__all__ = ["ToolSearchTool"]


class ToolSearchTool:
    """Search the current agent's allowed tool catalog without returning schemas."""

    def __init__(self, tool_definitions_provider: Callable[[str], Sequence[ToolDefinition]]) -> None:
        self._tool_definitions_provider = tool_definitions_provider

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="tool_search",
            description=(
                "Search the current agent's tool catalog when you need a capability but do not yet know "
                "which concrete tool schema is available. The result lists tool names and descriptions only; "
                "the runtime will reveal matching schemas on the next model round. Search for the final "
                "capability you need, not only the first small lookup step. After a tool name has been revealed, "
                "call that tool directly instead of searching for it again."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Describe the final capability you need, such as retrieving previous records, "
                            "creating a custom resume version, or saving a note."
                        ),
                    },
                    "groups": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional capability groups: artifact, retrieval, career, note, learning, memory, delegation.",
                    },
                    "top_k": {
                        "type": "integer",
                        "default": 8,
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        query = _required_string(arguments.get("query"), field_name="query")
        groups = _optional_string_list(arguments.get("groups"), field_name="groups")
        top_k = _optional_int(arguments.get("top_k"), field_name="top_k", default=8, minimum=1, maximum=20)
        definitions = list(self._tool_definitions_provider(run_context.agent_id))
        result = ToolCatalog(definitions).search(query=query, groups=groups, top_k=top_k)
        return ToolExecutionResult(
            tool_name="tool_search",
            success=True,
            content=json.dumps(result.to_payload(), ensure_ascii=False),
        )


def _required_string(raw: Any, *, field_name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ToolExecutionError(f"'{field_name}' must be a non-empty string.")
    return raw.strip()


def _optional_string_list(raw: Any, *, field_name: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ToolExecutionError(f"'{field_name}' must be a list of strings.")
    output: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ToolExecutionError(f"each '{field_name}' item must be a non-empty string.")
        output.append(item.strip())
    return output


def _optional_int(raw: Any, *, field_name: str, default: int, minimum: int, maximum: int) -> int:
    if raw is None:
        return default
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ToolExecutionError(f"'{field_name}' must be an integer.")
    if raw < minimum or raw > maximum:
        raise ToolExecutionError(f"'{field_name}' must be in range {minimum}..{maximum}.")
    return raw
