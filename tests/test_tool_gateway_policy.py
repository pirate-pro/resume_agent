"""Tests for the tool gateway policy boundary."""

from __future__ import annotations

import json
from typing import Any

from app.domain.models import RunContext, ToolCall, ToolExecutionResult
from app.runtime.agent.tool_gateway_policy import (
    gateway_state_block_result,
    resolve_tool_gateway_policy,
    workflow_event_payload_from_result,
)


def _context() -> RunContext:
    return RunContext(
        session_id="sess_gateway_policy",
        run_id="run_gateway_policy",
        agent_id="agent_main",
        turn_id="turn_gateway_policy",
        entry_agent_id="agent_main",
    )


def test_gateway_policy_combines_business_idempotency_and_execution_kind() -> None:
    policy = resolve_tool_gateway_policy(
        ToolCall(
            name="career_jd_analysis_save",
            arguments={"source_artifact_id": "artifact_jd_alpha"},
        ),
        _context(),
    )

    assert policy.kind == "idempotent_write"
    assert policy.idempotent is True
    assert policy.idempotency_key == (
        "career_jd_analysis_save:sess_gateway_policy:source_artifact_id=artifact_jd_alpha"
    )


def test_gateway_policy_marks_read_only_tools_cacheable() -> None:
    policy = resolve_tool_gateway_policy(
        ToolCall(name="session_read_artifact", arguments={"artifact_id": "artifact_resume_alpha"}),
        _context(),
    )

    assert policy.kind == "read_only"
    assert policy.cacheable is True
    assert policy.input_hash is not None


def test_gateway_state_block_result_blocks_final_answer_ready_tools() -> None:
    result = gateway_state_block_result(
        ToolCall(name="tool_search", arguments={"query": "继续搜索"}),
        pending_runtime_plan={"final_answer_ready": True},
    )

    assert result is not None
    payload = json.loads(result.content)
    assert payload["reason"] == "final_answer_ready_no_more_tools"
    assert payload["terminal"] is True


def test_gateway_state_block_result_blocks_discouraged_non_completion_tool() -> None:
    plan: dict[str, Any] = {
        "next_allowed_tools": ["career_resume_version_create"],
        "required_tools": ["career_resume_version_create"],
        "discouraged_tools": ["tool_search"],
        "missing_outputs": ["resume_version"],
    }

    result = gateway_state_block_result(
        ToolCall(name="tool_search", arguments={"query": "定制简历"}),
        pending_runtime_plan=plan,
    )

    assert result is not None
    payload = json.loads(result.content)
    assert payload["reason"] == "tool_blocked_by_runtime_state"
    assert payload["required_tools"] == ["career_resume_version_create"]


def test_workflow_event_payload_from_result_projects_runtime_payload() -> None:
    payload = {
        "workflow_runtime_result": True,
        "policy": "block",
        "reason": "tool_blocked_by_runtime_state",
        "terminal": False,
        "next_allowed_tools": ["career_resume_version_create"],
        "blocked_tools": ["tool_search"],
    }

    event_payload = workflow_event_payload_from_result(
        ToolExecutionResult(tool_name="tool_search", success=True, content=json.dumps(payload))
    )

    assert event_payload == {
        "workflow_runtime_result": True,
        "policy": "block",
        "tool_name": "tool_search",
        "reason": "tool_blocked_by_runtime_state",
        "terminal": False,
        "next_allowed_tools": ["career_resume_version_create"],
        "blocked_tools": ["tool_search"],
    }
