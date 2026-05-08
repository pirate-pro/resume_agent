"""Tests for safe tool execution normalization."""

from __future__ import annotations

import json

from app.core.errors import ToolExecutionError
from app.domain.models import RunContext, ToolCall, ToolDefinition, ToolExecutionResult
from app.runtime.agent.tool_runner import ToolExecutionRunner

__all__ = []


class _FailingToolExecutor:
    def __init__(self, message_template: str) -> None:
        self._message_template = message_template

    def list_definitions(self) -> list[ToolDefinition]:
        return []

    def execute(self, call: ToolCall, context: RunContext) -> ToolExecutionResult:
        _ = context
        raise ToolExecutionError(self._message_template.format(tool=call.name))


def _context() -> RunContext:
    return RunContext(
        session_id="sess_tool_runner",
        run_id="run_tool_runner",
        agent_id="agent_main",
        turn_id="turn_tool_runner",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={},
    )


def test_execute_safely_recovers_direct_child_agent_tool_call() -> None:
    runner = ToolExecutionRunner(tool_executor=_FailingToolExecutor("Tool not found: {tool}"))

    result = runner.execute_safely(ToolCall(name="job_agent", arguments={}), _context())

    assert result.success is True
    assert result.tool_name == "job_agent"
    payload = json.loads(result.content)
    assert payload["recoverable"] is True
    assert payload["error_type"] == "direct_child_agent_tool_call"
    assert payload["tool_name"] == "job_agent"
    assert "delegate_agents" in payload["message"]
    assert "target_agent_id" in payload["message"]


def test_execute_safely_keeps_normal_missing_tool_as_failure() -> None:
    runner = ToolExecutionRunner(tool_executor=_FailingToolExecutor("Tool not found: {tool}"))

    result = runner.execute_safely(ToolCall(name="missing_tool", arguments={}), _context())

    assert result.success is False
    assert result.content == "Tool not found: missing_tool"


def test_execute_safely_does_not_mask_other_child_agent_tool_errors() -> None:
    runner = ToolExecutionRunner(tool_executor=_FailingToolExecutor("Tool not allowed: {tool}"))

    result = runner.execute_safely(ToolCall(name="job_agent", arguments={}), _context())

    assert result.success is False
    assert result.content == "Tool not allowed: job_agent"
