"""Model/tool message protocol helpers for agent runtime."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.domain.models import ToolCall, ToolDefinition

__all__ = [
    "build_assistant_tool_call_message",
    "build_tool_result_message",
    "ensure_tool_call_ids",
    "to_model_tool_schema",
]


def to_model_tool_schema(definition: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": definition.name,
            "description": definition.description,
            "parameters": definition.parameters_schema,
        },
    }


def ensure_tool_call_ids(tool_calls: list[ToolCall]) -> list[ToolCall]:
    resolved: list[ToolCall] = []
    for call in tool_calls:
        call_id = call.tool_call_id or f"call_{uuid4().hex[:12]}"
        resolved.append(ToolCall(name=call.name, arguments=call.arguments, tool_call_id=call_id))
    return resolved


def build_assistant_tool_call_message(content: str, tool_calls: list[ToolCall]) -> dict[str, Any]:
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


def build_tool_result_message(*, tool_call_id: str | None, content: str) -> dict[str, str | None]:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": content,
    }
