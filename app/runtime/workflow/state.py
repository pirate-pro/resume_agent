"""Unified workflow state facade for runtime tool execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.errors import ValidationError
from app.runtime.workflow.tool_plan import (
    runtime_plan_completion_tools,
    runtime_plan_discouraged_tools,
    runtime_plan_next_allowed_tools,
)

__all__ = ["UnifiedWorkflowState", "unified_workflow_state_from_runtime_plan"]

WorkflowStatus = Literal["idle", "pending", "ready", "completed", "blocked"]


@dataclass(slots=True)
class UnifiedWorkflowState:
    """Narrow runtime state used by gateway/visibility policy."""

    phase: str | None = None
    status: WorkflowStatus = "idle"
    known_refs: dict[str, Any] = field(default_factory=dict)
    missing_outputs: list[str] = field(default_factory=list)
    next_required_tools: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    discouraged_tools: list[str] = field(default_factory=list)
    completed_tools: list[str] = field(default_factory=list)
    final_answer_ready: bool = False
    next_action: str | None = None
    source: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.phase = _optional_string("phase", self.phase)
        if self.status not in {"idle", "pending", "ready", "completed", "blocked"}:
            raise ValidationError(f"workflow state status is invalid: {self.status}")
        if not isinstance(self.known_refs, dict):
            raise ValidationError("workflow state known_refs must be a dictionary.")
        self.missing_outputs = _string_list("missing_outputs", self.missing_outputs)
        self.next_required_tools = _string_list("next_required_tools", self.next_required_tools)
        self.allowed_tools = _string_list("allowed_tools", self.allowed_tools)
        self.discouraged_tools = _string_list("discouraged_tools", self.discouraged_tools)
        self.completed_tools = _string_list("completed_tools", self.completed_tools)
        if not isinstance(self.final_answer_ready, bool):
            raise ValidationError("workflow state final_answer_ready must be bool.")
        self.next_action = _optional_string("next_action", self.next_action)
        if not isinstance(self.source, dict):
            raise ValidationError("workflow state source must be a dictionary.")

    def to_runtime_plan(self) -> dict[str, Any] | None:
        if self.status == "idle" and not self.phase:
            return None
        return {
            "phase": self.phase,
            "next_action": self.next_action,
            "next_allowed_tools": self.allowed_tools,
            "required_tools": self.next_required_tools,
            "known_refs": self.known_refs,
            "missing_outputs": self.missing_outputs,
            "discouraged_tools": self.discouraged_tools,
            "final_answer_ready": self.final_answer_ready,
        }


def unified_workflow_state_from_runtime_plan(plan: dict[str, Any] | None) -> UnifiedWorkflowState:
    if plan is None:
        return UnifiedWorkflowState(source={"kind": "none"})
    final_answer_ready = plan.get("final_answer_ready") is True
    next_required_tools = runtime_plan_completion_tools(plan)
    allowed_tools = runtime_plan_next_allowed_tools(plan)
    missing_outputs = _string_list_from_any(plan.get("missing_outputs"))
    raw_known_refs = plan.get("known_refs")
    status: WorkflowStatus
    if final_answer_ready:
        status = "completed"
    elif next_required_tools or missing_outputs:
        status = "pending"
    else:
        status = "ready"
    return UnifiedWorkflowState(
        phase=plan.get("phase") if isinstance(plan.get("phase"), str) else None,
        status=status,
        known_refs=raw_known_refs if isinstance(raw_known_refs, dict) else {},
        missing_outputs=missing_outputs,
        next_required_tools=next_required_tools,
        allowed_tools=allowed_tools,
        discouraged_tools=runtime_plan_discouraged_tools(plan),
        final_answer_ready=final_answer_ready,
        next_action=plan.get("next_action") if isinstance(plan.get("next_action"), str) else None,
        source={"kind": "runtime_tool_plan"},
    )


def _optional_string(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"workflow state {name} must be a non-empty string.")
    return value.strip()


def _string_list(name: str, values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(f"workflow state {name} must be a list.")
    return _string_list_from_any(values)


def _string_list_from_any(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            continue
        normalized = item.strip()
        if normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output
