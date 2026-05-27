"""Policy boundary for tool gateway execution."""

from __future__ import annotations

import json
from typing import Any

from app.domain.models import RunContext, ToolCall, ToolExecutionResult
from app.runtime.workflow.tool_idempotency import tool_idempotency_key
from app.runtime.workflow.tool_plan import (
    runtime_plan_completion_tools,
    runtime_plan_discouraged_tools,
    runtime_plan_next_allowed_tools,
)
from app.runtime.workflow.tool_policy import ToolExecutionPolicy, resolve_tool_execution_policy

__all__ = [
    "gateway_state_block_result",
    "resolve_tool_gateway_policy",
    "workflow_event_payload_from_result",
]


def resolve_tool_gateway_policy(
    tool_call: ToolCall,
    context: RunContext,
    *,
    pending_runtime_plan: dict[str, Any] | None = None,
) -> ToolExecutionPolicy:
    idempotency_key = tool_idempotency_key(
        tool_call,
        context,
        pending_runtime_plan=pending_runtime_plan,
    )
    return resolve_tool_execution_policy(tool_call, context, idempotency_key=idempotency_key)


def gateway_state_block_result(
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


def workflow_event_payload_from_result(result: ToolExecutionResult) -> dict[str, Any] | None:
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


def _json_object(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None
