"""Runtime state for progressive tool schema disclosure."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import ToolDefinition, ToolExecutionResult

__all__ = [
    "ToolRevealState",
    "hidden_tool_result",
    "normalize_always_visible_tool_names",
    "normalize_tool_schema_disclosure_mode",
]

TOOL_SEARCH_NAME = "tool_search"
_DEFAULT_ALWAYS_VISIBLE = (TOOL_SEARCH_NAME, "memory_write")


@dataclass(slots=True)
class ToolRevealState:
    """Per-run visible tool schema state."""

    mode: str
    available_definitions: list[ToolDefinition]
    always_visible_tool_names: set[str] = field(default_factory=set)
    revealed_tool_names: set[str] = field(default_factory=set)

    @classmethod
    def create(
        cls,
        *,
        mode: str,
        available_definitions: list[ToolDefinition],
        always_visible_tool_names: list[str] | None = None,
    ) -> "ToolRevealState":
        normalized_mode = normalize_tool_schema_disclosure_mode(mode)
        available_names = {definition.name for definition in available_definitions}
        always_visible = set(always_visible_tool_names or _DEFAULT_ALWAYS_VISIBLE)
        always_visible &= available_names
        return cls(
            mode=normalized_mode,
            available_definitions=list(available_definitions),
            always_visible_tool_names=always_visible,
            revealed_tool_names=set(),
        )

    def visible_definitions(self) -> list[ToolDefinition]:
        if self.mode == "full":
            return list(self.available_definitions)
        visible_names = self.always_visible_tool_names | self.revealed_tool_names
        return [definition for definition in self.available_definitions if definition.name in visible_names]

    def is_visible(self, tool_name: str) -> bool:
        if self.mode == "full":
            return True
        return tool_name in {definition.name for definition in self.visible_definitions()}

    def apply_tool_search_result(self, content: str) -> None:
        if self.mode != "search":
            return
        available_names = {definition.name for definition in self.available_definitions}
        for name in _extract_revealed_tool_names(content):
            if name in available_names:
                self.revealed_tool_names.add(name)

    def reveal_tool_names(self, tool_names: list[str]) -> None:
        if self.mode != "search":
            return
        available_names = {definition.name for definition in self.available_definitions}
        for name in tool_names:
            if name in available_names:
                self.revealed_tool_names.add(name)

    def usage_payload(self, *, visible_definitions: list[ToolDefinition]) -> dict[str, Any]:
        visible_names = [definition.name for definition in visible_definitions]
        return {
            "tool_disclosure_mode": self.mode,
            "tool_reveal_strategy": "cumulative_search" if self.mode == "search" else "full",
            "available_tool_count": len(self.available_definitions),
            "visible_tool_count": len(visible_definitions),
            "revealed_tool_count": len(self.revealed_tool_names),
            "visible_tool_names": visible_names,
            "revealed_tool_names": sorted(self.revealed_tool_names),
        }


def normalize_tool_schema_disclosure_mode(value: str) -> str:
    normalized = value.strip().lower()
    return normalized if normalized in {"full", "search"} else "full"


def normalize_always_visible_tool_names(value: str | list[str] | None) -> list[str]:
    if value is None:
        return list(_DEFAULT_ALWAYS_VISIBLE)
    if isinstance(value, str):
        raw_items = value.split(",")
    else:
        raw_items = value
    output: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, str):
            continue
        item = raw.strip()
        if not item or item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output or list(_DEFAULT_ALWAYS_VISIBLE)


def hidden_tool_result(tool_name: str, *, runtime_plan: dict[str, Any] | None = None) -> ToolExecutionResult:
    payload: dict[str, Any] = {
        "recoverable": True,
        "event_type": "tool_schema_not_revealed",
        "tool_name": tool_name,
        "message": "该工具本轮尚未揭示。请先调用 tool_search 搜索相关能力。",
    }
    if runtime_plan is not None:
        next_allowed_tools = _string_list(runtime_plan.get("next_allowed_tools"))
        required_tools = _string_list(runtime_plan.get("required_tools")) or next_allowed_tools
        payload.update(
            {
                "workflow_runtime_result": True,
                "policy": "block",
                "reason": "tool_hidden_by_runtime_plan",
                "message": "该工具本轮未揭示，因为当前 workflow 已收敛到确定下一步；不要继续调用隐藏工具。",
                "next_action": runtime_plan.get("next_action"),
                "next_allowed_tools": next_allowed_tools,
                "required_tools": required_tools,
                "known_refs": runtime_plan.get("known_refs") if isinstance(runtime_plan.get("known_refs"), dict) else {},
                "missing_outputs": _string_list(runtime_plan.get("missing_outputs")),
                "blocked_tools": [tool_name],
            }
        )
    content = json.dumps(payload, ensure_ascii=False)
    return ToolExecutionResult(tool_name=tool_name, success=True, content=content)


def _extract_revealed_tool_names(content: str) -> list[str]:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    output: list[str] = []
    revealed = payload.get("revealed_tools")
    if isinstance(revealed, list):
        for item in revealed:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    output.append(name.strip())
            elif isinstance(item, str) and item.strip():
                output.append(item.strip())
    names = payload.get("revealed_tool_names")
    if isinstance(names, list):
        output.extend(item.strip() for item in names if isinstance(item, str) and item.strip())
    return _dedupe(output)


def _dedupe(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
