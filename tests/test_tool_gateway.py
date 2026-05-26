"""Tests for ledger-backed tool gateway."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domain.models import RunContext, ToolCall, ToolDefinition, ToolExecutionResult
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.jsonl_tool_call_ledger import JsonlToolCallLedger
from app.runtime.agent.tool_gateway import ToolGateway
from app.runtime.workflow import WorkflowGuardDecision


class _CountingExecutor:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def list_definitions(self) -> list[ToolDefinition]:
        return []

    def execute(self, call: ToolCall, context: RunContext) -> ToolExecutionResult:
        self.calls.append(call)
        payload = {
            "record_type": "jd_analysis",
            "record_id": "jd_a",
            "jd_analysis_id": "jd_a",
            "source_artifact_id": call.arguments.get("source_artifact_id"),
        }
        return ToolExecutionResult(tool_name=call.name, success=True, content=json.dumps(payload))


class _BlockingGuard:
    def inspect(self, call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        payload = {
            "workflow_runtime_result": True,
            "policy": "block",
            "recoverable": True,
            "tool_executed": False,
            "result_created": False,
            "reason": "guard_block_before_ledger_reuse",
            "next_allowed_tools": ["career_jd_analysis_save"],
            "required_tools": ["career_jd_analysis_save"],
            "missing_outputs": ["jd_analysis"],
        }
        return WorkflowGuardDecision(
            tool_call=call,
            result=ToolExecutionResult(tool_name=call.name, success=True, content=json.dumps(payload)),
            event_payload={"policy": "block", "reason": "guard_block_before_ledger_reuse"},
        )


def _context() -> RunContext:
    return RunContext(
        session_id="sess_gateway",
        run_id="run_gateway",
        agent_id="agent_main",
        turn_id="turn_gateway",
        entry_agent_id="agent_main",
    )


def _child_context(*, run_id: str, agent_id: str = "resume_agent", task_id: str = "task_gateway") -> RunContext:
    return RunContext(
        session_id="sess_gateway",
        run_id=run_id,
        agent_id=agent_id,
        turn_id=f"turn_{run_id}",
        entry_agent_id="agent_main",
        parent_run_id="run_parent",
        task_id=task_id,
    )


def _gateway(tmp_path: Path) -> tuple[ToolGateway, _CountingExecutor]:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_gateway")
    executor = _CountingExecutor()
    gateway = ToolGateway(
        tool_executor=executor,
        ledger=JsonlToolCallLedger(data_dir=tmp_path),
    )
    return gateway, executor


def test_tool_gateway_reuses_idempotent_success_without_reexecuting(tmp_path: Path) -> None:
    gateway, executor = _gateway(tmp_path)
    call = ToolCall(
        name="career_jd_analysis_save",
        arguments={"source_artifact_id": "artifact_jd_a"},
        tool_call_id="call_jd_1",
    )

    first = gateway.execute(call, _context())
    second = gateway.execute(call, _context())
    second_payload = json.loads(second.result.content)

    assert first.result.success is True
    assert second.result.success is True
    assert len(executor.calls) == 1
    assert second_payload["idempotent_reused"] is True
    assert second.event_payload is not None
    assert second.event_payload["reason"] == "tool_call_ledger_reuse"


def test_tool_gateway_reuses_read_only_success_within_same_task(tmp_path: Path) -> None:
    gateway, executor = _gateway(tmp_path)
    call = ToolCall(
        name="session_read_artifact",
        arguments={"artifact_id": "artifact_resume_a"},
        tool_call_id="call_read_1",
    )

    first = gateway.execute(call, _child_context(run_id="run_child_a"))
    second = gateway.execute(call, _child_context(run_id="run_child_b", agent_id="job_agent"))
    second_payload = json.loads(second.result.content)

    assert first.result.success is True
    assert second.result.success is True
    assert len(executor.calls) == 1
    assert second_payload["idempotent_reused"] is True
    assert second.event_payload is not None
    assert second.event_payload["reason"] == "read_ledger_reuse"


def test_tool_gateway_guard_runs_before_ledger_reuse(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_gateway")
    ledger = JsonlToolCallLedger(data_dir=tmp_path)
    executor = _CountingExecutor()
    call = ToolCall(
        name="career_jd_analysis_save",
        arguments={"source_artifact_id": "artifact_jd_a"},
        tool_call_id="call_jd_1",
    )
    ToolGateway(tool_executor=executor, ledger=ledger).execute(call, _context())

    guarded_gateway = ToolGateway(
        tool_executor=executor,
        ledger=ledger,
        workflow_guard=_BlockingGuard(),  # type: ignore[arg-type]
    )
    blocked = guarded_gateway.execute(call, _context())
    payload = json.loads(blocked.result.content)

    assert len(executor.calls) == 1
    assert payload["reason"] == "guard_block_before_ledger_reuse"
    assert blocked.event_payload is not None
    assert blocked.event_payload["reason"] == "guard_block_before_ledger_reuse"


def test_tool_gateway_blocks_discouraged_tool_from_runtime_plan(tmp_path: Path) -> None:
    gateway, executor = _gateway(tmp_path)
    plan: dict[str, Any] = {
        "phase": "resume_version",
        "next_allowed_tools": ["career_resume_version_create"],
        "required_tools": ["career_resume_version_create"],
        "discouraged_tools": ["tool_search", "delegate_agents"],
        "missing_outputs": ["resume_version"],
    }

    result = gateway.execute(
        ToolCall(name="tool_search", arguments={"query": "定制简历"}, tool_call_id="call_search"),
        _context(),
        pending_runtime_plan=plan,
    )
    payload = json.loads(result.result.content)

    assert len(executor.calls) == 0
    assert payload["reason"] == "tool_blocked_by_runtime_state"
    assert payload["required_tools"] == ["career_resume_version_create"]
    assert result.event_payload is not None
    assert result.event_payload["policy"] == "block"


def test_tool_gateway_does_not_reuse_recoverable_blocked_record(tmp_path: Path) -> None:
    gateway, executor = _gateway(tmp_path)
    context = _context()
    ledger = JsonlToolCallLedger(data_dir=tmp_path)
    blocked = ledger.create_running(
        session_id=context.session_id,
        run_id=context.run_id,
        agent_id=context.agent_id,
        tool_name="career_jd_analysis_save",
        arguments={"source_artifact_id": "artifact_jd_blocked"},
        idempotency_key="career_jd_analysis_save:sess_gateway:source_artifact_id=artifact_jd_blocked",
    )
    ledger.mark_blocked(
        context.session_id,
        blocked.tool_call_record_id,
        result_content='{"workflow_runtime_result":true,"policy":"block","reason":"recoverable"}',
    )

    result = gateway.execute(
        ToolCall(name="career_jd_analysis_save", arguments={"source_artifact_id": "artifact_jd_blocked"}),
        context,
    )

    assert result.result.success is True
    assert len(executor.calls) == 1
    assert json.loads(result.result.content)["record_type"] == "jd_analysis"
