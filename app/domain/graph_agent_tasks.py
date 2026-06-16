"""Durable task-attempt models for LangGraph multi-agent execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.errors import ValidationError

__all__ = [
    "GRAPH_TASK_STATUS_COMPLETED",
    "GRAPH_TASK_STATUS_FAILED",
    "GRAPH_TASK_STATUS_QUEUED",
    "GRAPH_TASK_STATUS_RUNNING",
    "GraphAgentTaskAttemptRecord",
    "GraphAgentTaskAttemptSpec",
]

GRAPH_TASK_STATUS_QUEUED = "queued"
GRAPH_TASK_STATUS_RUNNING = "running"
GRAPH_TASK_STATUS_COMPLETED = "completed"
GRAPH_TASK_STATUS_FAILED = "failed"
_GRAPH_TASK_STATUSES = {
    GRAPH_TASK_STATUS_QUEUED,
    GRAPH_TASK_STATUS_RUNNING,
    GRAPH_TASK_STATUS_COMPLETED,
    GRAPH_TASK_STATUS_FAILED,
}


@dataclass(frozen=True, slots=True)
class GraphAgentTaskAttemptSpec:
    """Immutable inputs for one code-owned task execution."""

    session_id: str
    workflow_instance_id: str
    execution_key: str
    task_key: str
    target_agent_id: str
    instruction: str
    constraints: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    skill_names: tuple[str, ...] = ("base", "tools", "file-reader")
    max_tool_rounds: int = 24

    def __post_init__(self) -> None:
        _require_non_empty("session_id", self.session_id)
        _require_non_empty("workflow_instance_id", self.workflow_instance_id)
        _require_non_empty("execution_key", self.execution_key)
        _require_non_empty("task_key", self.task_key)
        _require_non_empty("target_agent_id", self.target_agent_id)
        _require_non_empty("instruction", self.instruction)
        _validate_string_tuple("constraints", self.constraints)
        _validate_string_tuple("artifact_refs", self.artifact_refs)
        _validate_string_tuple("skill_names", self.skill_names)
        if self.max_tool_rounds <= 0 or self.max_tool_rounds > 40:
            raise ValidationError("max_tool_rounds must be in range 1..40.")


@dataclass(frozen=True, slots=True)
class GraphAgentTaskAttemptRecord:
    """One persisted attempt for a stable graph task."""

    attempt_id: str
    session_id: str
    workflow_instance_id: str
    execution_key: str
    task_key: str
    attempt: int
    target_agent_id: str
    instruction: str
    constraints: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    skill_names: tuple[str, ...]
    max_tool_rounds: int
    status: str
    child_run_id: str | None = None
    summary: str | None = None
    error: str | None = None
    output_artifact_refs: tuple[str, ...] = field(default_factory=tuple)
    product_refs: tuple[str, ...] = field(default_factory=tuple)
    lease_owner_id: str | None = None
    lease_expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_empty("attempt_id", self.attempt_id)
        _require_non_empty("session_id", self.session_id)
        _require_non_empty("workflow_instance_id", self.workflow_instance_id)
        _require_non_empty("execution_key", self.execution_key)
        _require_non_empty("task_key", self.task_key)
        _require_non_empty("target_agent_id", self.target_agent_id)
        _require_non_empty("instruction", self.instruction)
        if self.attempt <= 0:
            raise ValidationError("attempt must be positive.")
        if self.max_tool_rounds <= 0 or self.max_tool_rounds > 40:
            raise ValidationError("max_tool_rounds must be in range 1..40.")
        if self.status not in _GRAPH_TASK_STATUSES:
            raise ValidationError(f"invalid graph task status: {self.status}")
        _validate_string_tuple("constraints", self.constraints)
        _validate_string_tuple("artifact_refs", self.artifact_refs)
        _validate_string_tuple("skill_names", self.skill_names)
        _validate_string_tuple("output_artifact_refs", self.output_artifact_refs)
        _validate_string_tuple("product_refs", self.product_refs)
        if self.created_at is None or self.updated_at is None:
            raise ValidationError("created_at and updated_at are required.")
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at cannot be earlier than created_at.")
        if self.status == GRAPH_TASK_STATUS_RUNNING:
            if self.lease_owner_id is None or self.lease_expires_at is None:
                raise ValidationError("running graph task attempts require an active lease.")


def _validate_string_tuple(name: str, values: tuple[str, ...]) -> None:
    if not isinstance(values, tuple):
        raise ValidationError(f"{name} must be a tuple.")
    for value in values:
        _require_non_empty(name, value)


def _require_non_empty(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()
