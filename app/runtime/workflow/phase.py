"""Read-only workflow phase snapshot models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.errors import ValidationError

__all__ = [
    "WorkflowPhaseSnapshot",
    "WorkflowRequiredOutput",
    "format_workflow_phase_lines",
]


@dataclass(slots=True)
class WorkflowRequiredOutput:
    """One product output required by the current workflow phase."""

    name: str
    ref_key: str
    status: str
    ref_value: str | None = None

    def __post_init__(self) -> None:
        self.name = _normalize_non_empty("required output name", self.name)
        self.ref_key = _normalize_non_empty("required output ref_key", self.ref_key)
        self.status = _normalize_status(self.status)
        if self.ref_value is not None:
            self.ref_value = _normalize_non_empty("required output ref_value", self.ref_value)

    @property
    def completed(self) -> bool:
        return self.status == "completed"


@dataclass(slots=True)
class WorkflowPhaseSnapshot:
    """Deterministic phase view for main-agent orchestration."""

    phase_name: str | None = None
    confidence: str = "none"
    input_refs: list[str] = field(default_factory=list)
    required_outputs: list[WorkflowRequiredOutput] = field(default_factory=list)
    allowed_tool_groups: list[str] = field(default_factory=list)
    blocked_tool_names: list[str] = field(default_factory=list)
    next_action_hint: str | None = None
    final_answer_ready: bool = False

    def __post_init__(self) -> None:
        if self.phase_name is not None:
            self.phase_name = _normalize_non_empty("phase_name", self.phase_name)
        self.confidence = _normalize_confidence(self.confidence)
        self.input_refs = _normalize_string_list("input_refs", self.input_refs)
        if not isinstance(self.required_outputs, list):
            raise ValidationError("required_outputs must be a list.")
        self.required_outputs = [
            item if isinstance(item, WorkflowRequiredOutput) else WorkflowRequiredOutput(**_as_dict(item))
            for item in self.required_outputs
        ]
        self.allowed_tool_groups = _normalize_string_list("allowed_tool_groups", self.allowed_tool_groups)
        self.blocked_tool_names = _normalize_string_list("blocked_tool_names", self.blocked_tool_names)
        if self.next_action_hint is not None:
            self.next_action_hint = _normalize_non_empty("next_action_hint", self.next_action_hint)
        if not isinstance(self.final_answer_ready, bool):
            raise ValidationError("final_answer_ready must be a boolean.")

    @property
    def missing_outputs(self) -> list[WorkflowRequiredOutput]:
        return [item for item in self.required_outputs if not item.completed]

    @property
    def completed_outputs(self) -> list[WorkflowRequiredOutput]:
        return [item for item in self.required_outputs if item.completed]

    def is_empty(self) -> bool:
        return self.phase_name is None and not self.required_outputs and not self.input_refs


def format_workflow_phase_lines(snapshot: WorkflowPhaseSnapshot) -> list[str]:
    """Render a compact model-facing phase section."""

    if snapshot.is_empty():
        return []
    lines = [
        f"- phase={snapshot.phase_name}",
        f"- confidence={snapshot.confidence}",
    ]
    if snapshot.input_refs:
        lines.append(f"- input_refs={','.join(snapshot.input_refs)}")
    if snapshot.completed_outputs:
        lines.append(
            "- completed_outputs="
            + ",".join(
                f"{item.name}:{item.ref_value}" if item.ref_value else item.name
                for item in snapshot.completed_outputs
            )
        )
    if snapshot.missing_outputs:
        lines.append("- missing_outputs=" + ",".join(item.name for item in snapshot.missing_outputs))
    if snapshot.allowed_tool_groups:
        lines.append("- allowed_tool_groups=" + ",".join(snapshot.allowed_tool_groups))
    if snapshot.blocked_tool_names:
        lines.append("- blocked_tool_names=" + ",".join(snapshot.blocked_tool_names))
    lines.append(f"- final_answer_ready={str(snapshot.final_answer_ready).lower()}")
    if snapshot.next_action_hint:
        lines.append(f"- next_action={snapshot.next_action_hint}")
    return lines


def _normalize_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _normalize_string_list(name: str, values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(f"{name} must be a list.")
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = _normalize_non_empty(name, str(raw))
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _normalize_status(value: str) -> str:
    normalized = _normalize_non_empty("required output status", value).lower()
    if normalized not in {"completed", "missing"}:
        raise ValidationError("required output status must be completed or missing.")
    return normalized


def _normalize_confidence(value: str) -> str:
    normalized = _normalize_non_empty("confidence", value).lower()
    if normalized not in {"none", "low", "medium", "high"}:
        raise ValidationError("confidence must be one of none/low/medium/high.")
    return normalized


def _as_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("required output item must be WorkflowRequiredOutput or dict.")
    return value
