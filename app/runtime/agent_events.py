"""Event payload schemas reserved for future multi-agent coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Self

from app.core.errors import ValidationError

__all__ = [
    "AGENT_TASK_COMPLETED_EVENT",
    "AGENT_TASK_FAILED_EVENT",
    "AGENT_TASK_GROUP_COMPLETED_EVENT",
    "AGENT_TASK_GROUP_CREATED_EVENT",
    "AGENT_TASK_PROGRESS_EVENT",
    "AGENT_TASK_STARTED_EVENT",
    "AGENT_RESULT_SUMMARY_EVENT",
    "AGENT_TASK_ASSIGNED_EVENT",
    "AgentResultSummaryPayload",
    "AgentTaskAssignedPayload",
]

AGENT_TASK_ASSIGNED_EVENT = "agent_task_assigned"
AGENT_RESULT_SUMMARY_EVENT = "agent_result_summary"
AGENT_TASK_GROUP_CREATED_EVENT = "agent_task_group_created"
AGENT_TASK_STARTED_EVENT = "agent_task_started"
AGENT_TASK_PROGRESS_EVENT = "agent_task_progress"
AGENT_TASK_COMPLETED_EVENT = "agent_task_completed"
AGENT_TASK_FAILED_EVENT = "agent_task_failed"
AGENT_TASK_GROUP_COMPLETED_EVENT = "agent_task_group_completed"


@dataclass(slots=True)
class AgentTaskAssignedPayload:
    """Task handoff payload from an orchestrator agent to a target agent."""

    task_id: str
    source_agent_id: str
    target_agent_id: str
    instruction: str
    constraints: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    task_context: dict[str, Any] = field(default_factory=dict)
    parent_run_id: str | None = None
    child_run_id: str | None = None

    def __post_init__(self) -> None:
        self.task_id = _require_non_empty("task_id", self.task_id)
        self.source_agent_id = _require_non_empty("source_agent_id", self.source_agent_id)
        self.target_agent_id = _require_non_empty("target_agent_id", self.target_agent_id)
        self.instruction = _require_non_empty("instruction", self.instruction)
        self.constraints = _normalize_string_list("constraints", self.constraints)
        self.artifact_refs = _normalize_string_list("artifact_refs", self.artifact_refs)
        if not isinstance(self.task_context, dict):
            raise ValidationError("task_context must be a dictionary.")
        self.task_context = dict(self.task_context)
        self.parent_run_id = _normalize_optional("parent_run_id", self.parent_run_id)
        self.child_run_id = _normalize_optional("child_run_id", self.child_run_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source_agent_id": self.source_agent_id,
            "target_agent_id": self.target_agent_id,
            "instruction": self.instruction,
            "constraints": self.constraints,
            "artifact_refs": self.artifact_refs,
            "task_context": self.task_context,
            "parent_run_id": self.parent_run_id,
            "child_run_id": self.child_run_id,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        if not isinstance(payload, dict):
            raise ValidationError("agent task payload must be a dictionary.")
        return cls(
            task_id=str(payload.get("task_id", "")),
            source_agent_id=str(payload.get("source_agent_id", "")),
            target_agent_id=str(payload.get("target_agent_id", "")),
            instruction=str(payload.get("instruction", "")),
            constraints=_payload_string_list(payload.get("constraints")),
            artifact_refs=_payload_string_list(payload.get("artifact_refs")),
            task_context=_payload_dict(payload.get("task_context")),
            parent_run_id=_payload_optional_string(payload.get("parent_run_id")),
            child_run_id=_payload_optional_string(payload.get("child_run_id")),
        )


@dataclass(slots=True)
class AgentResultSummaryPayload:
    """Result summary payload from a worker agent back to an orchestrator agent."""

    task_id: str
    source_agent_id: str
    target_agent_id: str
    status: str
    summary: str
    next_steps: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    output_artifact_refs: list[str] = field(default_factory=list)
    product_refs: list[str] = field(default_factory=list)
    parent_run_id: str | None = None

    def __post_init__(self) -> None:
        self.task_id = _require_non_empty("task_id", self.task_id)
        self.source_agent_id = _require_non_empty("source_agent_id", self.source_agent_id)
        self.target_agent_id = _require_non_empty("target_agent_id", self.target_agent_id)
        self.status = _require_non_empty("status", self.status)
        self.summary = _require_non_empty("summary", self.summary)
        self.next_steps = _normalize_string_list("next_steps", self.next_steps)
        self.artifact_refs = _normalize_string_list("artifact_refs", self.artifact_refs)
        self.output_artifact_refs = _normalize_string_list("output_artifact_refs", self.output_artifact_refs)
        self.product_refs = _normalize_string_list("product_refs", self.product_refs)
        self.parent_run_id = _normalize_optional("parent_run_id", self.parent_run_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source_agent_id": self.source_agent_id,
            "target_agent_id": self.target_agent_id,
            "status": self.status,
            "summary": self.summary,
            "next_steps": self.next_steps,
            "artifact_refs": self.artifact_refs,
            "output_artifact_refs": self.output_artifact_refs,
            "product_refs": self.product_refs,
            "parent_run_id": self.parent_run_id,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        if not isinstance(payload, dict):
            raise ValidationError("agent result summary payload must be a dictionary.")
        return cls(
            task_id=str(payload.get("task_id", "")),
            source_agent_id=str(payload.get("source_agent_id", "")),
            target_agent_id=str(payload.get("target_agent_id", "")),
            status=str(payload.get("status", "")),
            summary=str(payload.get("summary", "")),
            next_steps=_payload_string_list(payload.get("next_steps")),
            artifact_refs=_payload_string_list(payload.get("artifact_refs")),
            output_artifact_refs=_payload_string_list(payload.get("output_artifact_refs")),
            product_refs=_payload_string_list(payload.get("product_refs")),
            parent_run_id=_payload_optional_string(payload.get("parent_run_id")),
        )


def _require_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _normalize_optional(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_non_empty(field_name, value)


def _normalize_string_list(field_name: str, values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(f"{field_name} must be a list.")
    output: list[str] = []
    for raw in values:
        output.append(_require_non_empty(field_name, raw))
    return output


def _payload_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError("payload list field must be a list.")
    return [str(item) for item in value if str(item).strip()]


def _payload_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _payload_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError("payload dict field must be a dictionary.")
    return dict(value)
