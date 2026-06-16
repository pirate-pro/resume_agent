"""Tests for runtime-plan tool schema routing."""

from __future__ import annotations

from app.domain.models import ToolDefinition
from app.runtime.agent.tool_reveal import ToolRevealState
from app.runtime.agent_runtime import _visible_tool_definitions_for_runtime_plan

__all__ = []


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} description",
        parameters_schema={"type": "object", "properties": {}},
    )


def test_runtime_plan_next_allowed_tools_are_the_only_visible_schemas() -> None:
    state = ToolRevealState.create(
        mode="search",
        available_definitions=[
            _definition("tool_search"),
            _definition("memory_write"),
            _definition("career_application_get"),
            _definition("career_application_list"),
        ],
        always_visible_tool_names=[
            "tool_search",
            "memory_write",
            "career_application_get",
            "career_application_list",
        ],
    )

    visible = _visible_tool_definitions_for_runtime_plan(
        tool_reveal_state=state,
        pending_runtime_plan={
            "phase": "resume_version",
            "next_allowed_tools": ["career_application_get"],
            "required_tools": ["career_application_get"],
            "missing_outputs": ["career_application_read"],
            "discouraged_tools": ["tool_search", "memory_write", "career_application_list"],
        },
    )

    assert [definition.name for definition in visible] == ["career_application_get"]
