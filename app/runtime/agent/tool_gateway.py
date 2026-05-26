"""Unified tool gateway with ledger-backed dedupe and guard compatibility."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from app.domain.models import RunContext, ToolCall, ToolExecutionResult
from app.domain.protocols import ToolExecutor
from app.domain.tool_call_protocols import ToolCallLedger
from app.domain.tool_calls import (
    TOOL_CALL_STATUS_BLOCKED,
    TOOL_CALL_STATUS_REUSED,
    TOOL_CALL_STATUS_RUNNING,
    TOOL_CALL_STATUS_SUCCEEDED,
    ToolCallRecord,
)
from app.runtime.agent.tool_runner import ToolExecutionRunner
from app.runtime.workflow import WorkflowRuntimeGuard
from app.runtime.workflow.tool_idempotency import tool_idempotency_key
from app.runtime.workflow.tool_plan import (
    runtime_plan_completion_tools,
    runtime_plan_discouraged_tools,
    runtime_plan_next_allowed_tools,
)
from app.runtime.workflow.tool_policy import resolve_tool_execution_policy

__all__ = ["ToolGateway", "ToolGatewayResult"]


@dataclass(frozen=True, slots=True)
class ToolGatewayResult:
    tool_call: ToolCall
    result: ToolExecutionResult
    event_payload: dict[str, Any] | None = None


class ToolGateway:
    """Execute tools through workflow state checks, ledger reuse, guard, then runner."""

    def __init__(
        self,
        *,
        tool_executor: ToolExecutor,
        ledger: ToolCallLedger,
        workflow_guard: WorkflowRuntimeGuard | None = None,
    ) -> None:
        self._runner = ToolExecutionRunner(tool_executor=tool_executor)
        self._ledger = ledger
        self._workflow_guard = workflow_guard

    def execute(
        self,
        tool_call: ToolCall,
        context: RunContext,
        *,
        pending_runtime_plan: dict[str, Any] | None = None,
    ) -> ToolGatewayResult:
        idempotency_key = tool_idempotency_key(
            tool_call,
            context,
            pending_runtime_plan=pending_runtime_plan,
        )
        policy = resolve_tool_execution_policy(tool_call, context, idempotency_key=idempotency_key)

        state_block = _state_block_result(tool_call, pending_runtime_plan=pending_runtime_plan)
        if state_block is not None:
            record = self._ledger.create_running(
                session_id=context.session_id,
                run_id=context.run_id,
                agent_id=context.agent_id,
                task_id=_task_id_from_context(context),
                tool_name=tool_call.name,
                tool_call_id=tool_call.tool_call_id,
                arguments=tool_call.arguments,
                input_hash=policy.input_hash,
                idempotency_key=policy.idempotency_key,
            )
            self._ledger.mark_blocked(
                context.session_id,
                record.tool_call_record_id,
                result_content=state_block.content,
                result_refs=_extract_result_refs(state_block.content),
            )
            return ToolGatewayResult(
                tool_call=tool_call,
                result=state_block,
                event_payload=_workflow_event_payload_from_result(state_block),
            )

        execution_call = tool_call
        guard_payload: dict[str, Any] | None = None
        if self._workflow_guard is not None:
            guard_decision = self._workflow_guard.inspect(tool_call, context)
            execution_call = guard_decision.tool_call
            guard_payload = guard_decision.event_payload
            if guard_decision.result is not None:
                record = self._ledger.create_running(
                    session_id=context.session_id,
                    run_id=context.run_id,
                    agent_id=context.agent_id,
                    task_id=_task_id_from_context(context),
                    tool_name=tool_call.name,
                    tool_call_id=tool_call.tool_call_id,
                    arguments=tool_call.arguments,
                    input_hash=policy.input_hash,
                    idempotency_key=policy.idempotency_key,
                )
                self._mark_record_from_guard_result(context, record, guard_decision.result)
                return ToolGatewayResult(
                    tool_call=execution_call,
                    result=guard_decision.result,
                    event_payload=guard_payload,
                )
        if execution_call != tool_call:
            idempotency_key = tool_idempotency_key(
                execution_call,
                context,
                pending_runtime_plan=pending_runtime_plan,
            )
            policy = resolve_tool_execution_policy(execution_call, context, idempotency_key=idempotency_key)

        existing = self._find_existing_record(policy=policy, context=context)
        if existing is not None:
            result = _reuse_result_from_record(execution_call.name, existing)
            return ToolGatewayResult(
                tool_call=execution_call,
                result=result,
                event_payload={
                    "workflow_runtime_result": True,
                    "policy": "reuse" if existing.status != TOOL_CALL_STATUS_BLOCKED else "block",
                    "tool_name": execution_call.name,
                    "reason": "read_ledger_reuse" if policy.cacheable else "tool_call_ledger_reuse",
                    "ledger_record_id": existing.tool_call_record_id,
                    "idempotency_key": existing.idempotency_key,
                    "input_hash": existing.input_hash,
                    "ledger_status": existing.status,
                },
            )

        if self._is_running_duplicate(policy=policy, context=context):
            result = _already_running_result(tool_call.name, policy.idempotency_key)
            return ToolGatewayResult(
                tool_call=tool_call,
                result=result,
                event_payload=_workflow_event_payload_from_result(result),
            )

        record = self._ledger.create_running(
            session_id=context.session_id,
            run_id=context.run_id,
            agent_id=context.agent_id,
            task_id=_task_id_from_context(context),
            tool_name=execution_call.name,
            tool_call_id=execution_call.tool_call_id,
            arguments=execution_call.arguments,
            input_hash=policy.input_hash,
            idempotency_key=policy.idempotency_key,
        )

        result = self._runner.execute_safely(execution_call, context)
        if result.success:
            self._ledger.mark_succeeded(
                context.session_id,
                record.tool_call_record_id,
                result_content=result.content,
                result_refs=_extract_result_refs(result.content),
            )
        else:
            self._ledger.mark_failed(context.session_id, record.tool_call_record_id, error=result.content)
        return ToolGatewayResult(tool_call=execution_call, result=result, event_payload=guard_payload)

    async def execute_async(
        self,
        tool_call: ToolCall,
        context: RunContext,
        *,
        pending_runtime_plan: dict[str, Any] | None = None,
    ) -> ToolGatewayResult:
        return await asyncio.to_thread(
            self.execute,
            tool_call,
            context,
            pending_runtime_plan=pending_runtime_plan,
        )

    def _find_existing_record(
        self,
        *,
        policy: Any,
        context: RunContext,
    ) -> ToolCallRecord | None:
        if policy.idempotency_key is not None:
            existing = self._ledger.find_latest_by_idempotency_key(
                session_id=context.session_id,
                tool_name=policy.tool_name,
                idempotency_key=policy.idempotency_key,
            )
            if existing is not None and _record_can_reuse(existing):
                return existing
        if policy.cacheable and policy.input_hash is not None:
            return self._ledger.find_latest_success_by_input_hash(
                session_id=context.session_id,
                run_id=context.run_id,
                agent_id=context.agent_id,
                tool_name=policy.tool_name,
                input_hash=policy.input_hash,
                task_id=_task_id_from_context(context),
            )
        return None

    def _is_running_duplicate(self, *, policy: Any, context: RunContext) -> bool:
        if policy.idempotency_key is None:
            return False
        existing = self._ledger.find_latest_by_idempotency_key(
            session_id=context.session_id,
            tool_name=policy.tool_name,
            idempotency_key=policy.idempotency_key,
        )
        return existing is not None and existing.status == TOOL_CALL_STATUS_RUNNING

    def _mark_record_from_guard_result(
        self,
        context: RunContext,
        record: ToolCallRecord,
        result: ToolExecutionResult,
    ) -> None:
        payload = _json_object(result.content)
        policy = payload.get("policy") if payload is not None else None
        refs = _extract_result_refs(result.content)
        if policy == "reuse":
            self._ledger.mark_reused(
                context.session_id,
                record.tool_call_record_id,
                result_content=result.content,
                result_refs=refs,
            )
            return
        self._ledger.mark_blocked(
            context.session_id,
            record.tool_call_record_id,
            result_content=result.content,
            result_refs=refs,
        )


def _state_block_result(
    tool_call: ToolCall,
    *,
    pending_runtime_plan: dict[str, Any] | None,
) -> ToolExecutionResult | None:
    if pending_runtime_plan is None:
        return None
    if tool_call.name == "memory_write":
        return None
    if pending_runtime_plan.get("final_answer_ready") is True:
        payload = {
            "workflow_runtime_result": True,
            "policy": "block",
            "recoverable": True,
            "terminal": True,
            "tool_executed": False,
            "result_created": False,
            "reason": "final_answer_ready_no_more_tools",
            "tool": tool_call.name,
            "next_action": "当前 workflow 关键产物已完成；不要继续调用工具，直接最终答复。",
            "missing_outputs": [],
            "next_allowed_tools": [],
            "required_tools": [],
            "blocked_tools": [tool_call.name],
        }
        return ToolExecutionResult(tool_name=tool_call.name, success=True, content=json.dumps(payload, ensure_ascii=False))

    completion_tools = set(runtime_plan_completion_tools(pending_runtime_plan))
    discouraged_tools = set(runtime_plan_discouraged_tools(pending_runtime_plan))
    if completion_tools and tool_call.name in discouraged_tools and tool_call.name not in completion_tools:
        next_allowed_tools = runtime_plan_next_allowed_tools(pending_runtime_plan)
        payload = {
            "workflow_runtime_result": True,
            "policy": "block",
            "recoverable": True,
            "terminal": False,
            "tool_executed": False,
            "result_created": False,
            "reason": "tool_blocked_by_runtime_state",
            "tool": tool_call.name,
            "next_action": pending_runtime_plan.get("next_action"),
            "missing_outputs": pending_runtime_plan.get("missing_outputs") or [],
            "next_allowed_tools": next_allowed_tools,
            "required_tools": list(completion_tools),
            "blocked_tools": [tool_call.name],
            "known_refs": pending_runtime_plan.get("known_refs")
            if isinstance(pending_runtime_plan.get("known_refs"), dict)
            else {},
        }
        return ToolExecutionResult(tool_name=tool_call.name, success=True, content=json.dumps(payload, ensure_ascii=False))
    return None


def _record_can_reuse(record: ToolCallRecord) -> bool:
    if record.result_content is None:
        return False
    return record.status in {
        TOOL_CALL_STATUS_SUCCEEDED,
        TOOL_CALL_STATUS_REUSED,
    }


def _reuse_result_from_record(tool_name: str, record: ToolCallRecord) -> ToolExecutionResult:
    content = record.result_content or "{}"
    payload = _json_object(content)
    if payload is not None:
        payload = dict(payload)
        payload.update(
            {
                "workflow_runtime_result": payload.get("workflow_runtime_result", True),
                "policy": payload.get("policy", "reuse"),
                "idempotent_reused": True,
                "tool": tool_name,
                "reason": payload.get("reason", "tool_call_ledger_reuse"),
                "ledger_record_id": record.tool_call_record_id,
            }
        )
        content = json.dumps(payload, ensure_ascii=False)
    return ToolExecutionResult(tool_name=tool_name, success=True, content=content)


def _already_running_result(tool_name: str, idempotency_key: str | None) -> ToolExecutionResult:
    payload = {
        "workflow_runtime_result": True,
        "policy": "block",
        "recoverable": True,
        "terminal": False,
        "tool_executed": False,
        "result_created": False,
        "reason": "tool_call_already_running",
        "tool": tool_name,
        "idempotency_key": idempotency_key,
        "next_action": "同一幂等工具调用正在执行；不要并发重复调用，等待已有调用结果或基于当前状态继续。",
        "missing_outputs": [],
        "blocked_tools": [tool_name],
    }
    return ToolExecutionResult(tool_name=tool_name, success=True, content=json.dumps(payload, ensure_ascii=False))


def _workflow_event_payload_from_result(result: ToolExecutionResult) -> dict[str, Any] | None:
    payload = _json_object(result.content)
    if payload is None or payload.get("workflow_runtime_result") is not True:
        return None
    return {
        "workflow_runtime_result": True,
        "policy": payload.get("policy"),
        "tool_name": result.tool_name,
        "reason": payload.get("reason"),
        "terminal": payload.get("terminal"),
        "next_allowed_tools": payload.get("next_allowed_tools") if isinstance(payload.get("next_allowed_tools"), list) else [],
        "blocked_tools": payload.get("blocked_tools") if isinstance(payload.get("blocked_tools"), list) else [],
    }


def _extract_result_refs(content: str) -> dict[str, Any]:
    payload = _json_object(content)
    if payload is None:
        return {}
    refs: dict[str, Any] = {}
    for source in (payload, payload.get("record"), payload.get("ids")):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if not isinstance(key, str) or value is None:
                continue
            if key in {"record_id", "artifact_id"} or key.endswith("_id") or key.endswith("_ids"):
                refs.setdefault(key, value)
    for key in ("product_refs", "artifact_refs", "output_artifact_refs"):
        value = payload.get(key)
        if isinstance(value, list):
            refs.setdefault(key, [item for item in value if isinstance(item, str)])
    return refs


def _json_object(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _task_id_from_context(context: RunContext) -> str | None:
    if context.task_id is not None:
        return context.task_id
    return context.run_id if context.parent_run_id is not None else None
