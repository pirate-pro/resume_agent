"""Tests for central runtime tool capability classification."""

from __future__ import annotations

from app.runtime.tool_capabilities import (
    ACTION_WRITE_TOOL_NAMES,
    READ_ONLY_TURN_WRITE_BLOCK_TOOL_NAMES,
    is_write_tool,
    tool_kind,
    tool_names_for_kind,
)
from app.runtime.workflow.action_plan import ACTION_WRITE_TOOLS
from app.runtime.workflow.tool_policy import resolve_tool_execution_policy
from app.domain.models import RunContext, ToolCall


def _context() -> RunContext:
    return RunContext(
        session_id="sess_tool_caps",
        run_id="run_tool_caps",
        agent_id="agent_main",
        turn_id="turn_tool_caps",
        entry_agent_id="agent_main",
    )


def test_tool_kind_comes_from_capability_registry() -> None:
    assert tool_kind("tool_search") == "schema"
    assert tool_kind("session_read_artifact") == "read_only"
    assert tool_kind("career_jd_analysis_save") == "idempotent_write"
    assert tool_kind("memory_write") == "volatile_write"
    assert tool_kind("unknown_tool") == "unknown"


def test_tool_policy_uses_capability_registry_kind() -> None:
    policy = resolve_tool_execution_policy(
        ToolCall(name="session_read_artifact", arguments={"artifact_id": "artifact_a"}),
        _context(),
    )

    assert policy.kind == tool_kind("session_read_artifact")
    assert policy.cacheable is True


def test_action_write_tools_are_backed_by_capability_registry() -> None:
    assert ACTION_WRITE_TOOLS == list(ACTION_WRITE_TOOL_NAMES)
    assert "career_profile_merge" in ACTION_WRITE_TOOLS
    assert "session_create_text_artifact" not in ACTION_WRITE_TOOLS


def test_read_only_turn_block_tools_are_registered_as_writes() -> None:
    assert "note_update" in READ_ONLY_TURN_WRITE_BLOCK_TOOL_NAMES
    assert "learning_task_update_state" in READ_ONLY_TURN_WRITE_BLOCK_TOOL_NAMES
    assert is_write_tool("note_update") is True
    assert is_write_tool("session_read_artifact") is False


def test_tool_names_for_kind_returns_stable_tuple() -> None:
    read_only = tool_names_for_kind("read_only")

    assert isinstance(read_only, tuple)
    assert "retrieval_search" in read_only
