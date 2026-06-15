"""Domain models for durable workflow instance tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from app.core.errors import ValidationError

__all__ = [
    "WORKFLOW_STATUS_CANCELLED",
    "WORKFLOW_STATUS_COMPLETED",
    "WORKFLOW_STATUS_FAILED",
    "WORKFLOW_STATUS_RUNNING",
    "WORKFLOW_STATUS_WAITING",
    "WorkflowInstanceRecord",
]

WORKFLOW_STATUS_RUNNING = "running"
WORKFLOW_STATUS_WAITING = "waiting"
WORKFLOW_STATUS_COMPLETED = "completed"
WORKFLOW_STATUS_FAILED = "failed"
WORKFLOW_STATUS_CANCELLED = "cancelled"

_WORKFLOW_STATUSES = {
    WORKFLOW_STATUS_RUNNING,
    WORKFLOW_STATUS_WAITING,
    WORKFLOW_STATUS_COMPLETED,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_CANCELLED,
}


@dataclass(slots=True)
class WorkflowInstanceRecord:
    """Durable snapshot for one workflow instance."""

    workflow_instance_id: str
    workflow_id: str
    session_id: str
    thread_id: str
    status: str
    phase: str
    run_id: str | None = None
    pending_interrupt_payload: dict[str, Any] | None = None
    output_refs: dict[str, Any] = field(default_factory=dict)
    last_error: dict[str, Any] | None = None
    state_snapshot: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        self.workflow_instance_id = _require_non_empty("workflow_instance_id", self.workflow_instance_id)
        self.workflow_id = _require_non_empty("workflow_id", self.workflow_id)
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.thread_id = _require_non_empty("thread_id", self.thread_id)
        self.status = _normalize_status(self.status)
        self.phase = _require_non_empty("phase", self.phase)
        self.run_id = _normalize_optional_string("run_id", self.run_id)
        if self.pending_interrupt_payload is not None and not isinstance(self.pending_interrupt_payload, dict):
            raise ValidationError("pending_interrupt_payload must be a dictionary.")
        if not isinstance(self.output_refs, dict):
            raise ValidationError("output_refs must be a dictionary.")
        if self.last_error is not None and not isinstance(self.last_error, dict):
            raise ValidationError("last_error must be a dictionary.")
        if not isinstance(self.state_snapshot, dict):
            raise ValidationError("state_snapshot must be a dictionary.")
        if self.created_at is None:
            raise ValidationError("workflow instance created_at is required.")
        if self.updated_at is None:
            raise ValidationError("workflow instance updated_at is required.")
        if self.updated_at < self.created_at:
            raise ValidationError("workflow instance updated_at cannot be earlier than created_at.")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValidationError("workflow instance completed_at cannot be earlier than created_at.")
        if self.version <= 0:
            raise ValidationError("workflow instance version must be positive.")

    def copy(self) -> Self:
        return type(self)(
            workflow_instance_id=self.workflow_instance_id,
            workflow_id=self.workflow_id,
            session_id=self.session_id,
            thread_id=self.thread_id,
            status=self.status,
            phase=self.phase,
            run_id=self.run_id,
            pending_interrupt_payload=dict(self.pending_interrupt_payload)
            if self.pending_interrupt_payload is not None
            else None,
            output_refs=dict(self.output_refs),
            last_error=dict(self.last_error) if self.last_error is not None else None,
            state_snapshot=dict(self.state_snapshot),
            created_at=self.created_at,
            updated_at=self.updated_at,
            completed_at=self.completed_at,
            version=self.version,
        )


def _normalize_status(status: str) -> str:
    normalized = _require_non_empty("workflow instance status", status).lower()
    if normalized not in _WORKFLOW_STATUSES:
        raise ValidationError(f"workflow instance status is invalid: {normalized}")
    return normalized


def _require_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _normalize_optional_string(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_non_empty(name, value)
