"""Tests for progressive tool schema reveal state."""

from __future__ import annotations

import json

from app.domain.models import ToolDefinition
from app.runtime.agent.tool_reveal import ToolRevealState, hidden_tool_result

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


def test_hidden_tool_result_uses_runtime_plan_when_available() -> None:
    result = hidden_tool_result(
        "session_read_artifact",
        runtime_plan={
            "phase": "jd_fit",
            "next_action": "只保存匹配报告。",
            "next_allowed_tools": ["career_job_fit_report_save"],
            "required_tools": ["career_job_fit_report_save"],
            "known_refs": {"report_artifact_id": "artifact_fit_report"},
            "missing_outputs": ["job_fit_report"],
        },
    )

    payload = json.loads(result.content)
    assert payload["workflow_runtime_result"] is True
    assert payload["policy"] == "block"
    assert payload["reason"] == "tool_hidden_by_runtime_plan"
    assert payload["next_allowed_tools"] == ["career_job_fit_report_save"]
    assert payload["required_tools"] == ["career_job_fit_report_save"]
    assert payload["known_refs"] == {"report_artifact_id": "artifact_fit_report"}
    assert payload["blocked_tools"] == ["session_read_artifact"]
