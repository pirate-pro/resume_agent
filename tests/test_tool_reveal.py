"""Tests for progressive tool schema reveal state."""

from __future__ import annotations

import json

from app.domain.models import ToolDefinition
from app.runtime.agent.tool_reveal import ToolRevealState

__all__ = []


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} description",
        parameters_schema={"type": "object", "properties": {}},
    )


def test_tool_reveal_state_accumulates_successful_tool_search_results() -> None:
    state = ToolRevealState.create(
        mode="search",
        available_definitions=[
            _definition("tool_search"),
            _definition("memory_write"),
            _definition("session_read_artifact"),
            _definition("career_resume_version_create"),
        ],
    )

    state.apply_tool_search_result(json.dumps({"revealed_tool_names": ["session_read_artifact"]}))
    assert {item.name for item in state.visible_definitions()} == {
        "tool_search",
        "memory_write",
        "session_read_artifact",
    }

    state.apply_tool_search_result(json.dumps({"revealed_tool_names": ["career_resume_version_create"]}))
    assert {item.name for item in state.visible_definitions()} == {
        "tool_search",
        "memory_write",
        "session_read_artifact",
        "career_resume_version_create",
    }
    assert state.usage_payload(visible_definitions=state.visible_definitions())["tool_reveal_strategy"] == (
        "cumulative_search"
    )


def test_tool_reveal_state_keeps_previous_focus_when_search_returns_no_names() -> None:
    state = ToolRevealState.create(
        mode="search",
        available_definitions=[
            _definition("tool_search"),
            _definition("memory_write"),
            _definition("session_read_artifact"),
        ],
    )

    state.apply_tool_search_result(json.dumps({"revealed_tool_names": ["session_read_artifact"]}))
    state.apply_tool_search_result(json.dumps({"revealed_tool_names": []}))

    assert {item.name for item in state.visible_definitions()} == {
        "tool_search",
        "memory_write",
        "session_read_artifact",
    }
