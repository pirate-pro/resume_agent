"""Domain models for durable tool call accounting."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from app.core.errors import ValidationError

__all__ = [
    "TOOL_CALL_STATUS_BLOCKED",
    "TOOL_CALL_STATUS_FAILED",
    "TOOL_CALL_STATUS_REUSED",
    "TOOL_CALL_STATUS_RUNNING",
    "TOOL_CALL_STATUS_SKIPPED",
    "TOOL_CALL_STATUS_SUCCEEDED",
    "ToolCallRecord",
]

TOOL_CALL_STATUS_RUNNING = "running"
TOOL_CALL_STATUS_SUCCEEDED = "succeeded"
TOOL_CALL_STATUS_FAILED = "failed"
TOOL_CALL_STATUS_REUSED = "reused"
TOOL_CALL_STATUS_SKIPPED = "skipped"
TOOL_CALL_STATUS_BLOCKED = "blocked"

_TOOL_CALL_STATUSES = {
    TOOL_CALL_STATUS_RUNNING,
    TOOL_CALL_STATUS_SUCCEEDED,
    TOOL_CALL_STATUS_FAILED,
    TOOL_CALL_STATUS_REUSED,
    TOOL_CALL_STATUS_SKIPPED,
    TOOL_CALL_STATUS_BLOCKED,
}


@dataclass(slots=True)
class ToolCallRecord:
    """Durable record for one attempted tool call."""

    tool_call_record_id: str
    session_id: str
    run_id: str
    agent_id: str
    tool_name: str
    status: str
    arguments: dict[str, Any] = field(default_factory=dict)
    task_id: str | None = None
    tool_call_id: str | None = None
    input_hash: str | None = None
    idempotency_key: str | None = None
    result_content: str | None = None
    result_refs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        self.tool_call_record_id = _require_non_empty("tool_call_record_id", self.tool_call_record_id)
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.run_id = _require_non_empty("run_id", self.run_id)
        self.agent_id = _require_non_empty("agent_id", self.agent_id)
        self.tool_name = _require_non_empty("tool_name", self.tool_name)
        self.status = _normalize_status(self.status)
        if not isinstance(self.arguments, dict):
            raise ValidationError("tool call arguments must be a dictionary.")
        self.task_id = _normalize_optional_string("task_id", self.task_id)
        self.tool_call_id = _normalize_optional_string("tool_call_id", self.tool_call_id)
        self.input_hash = _normalize_optional_string("input_hash", self.input_hash)
        self.idempotency_key = _normalize_optional_string("idempotency_key", self.idempotency_key)
        self.result_content = _normalize_optional_string("result_content", self.result_content)
        if not isinstance(self.result_refs, dict):
            raise ValidationError("tool call result_refs must be a dictionary.")
        self.error = _normalize_optional_string("error", self.error)
        if self.created_at is None:
            raise ValidationError("tool call created_at is required.")
        if self.updated_at is None:
            raise ValidationError("tool call updated_at is required.")
        if self.updated_at < self.created_at:
            raise ValidationError("tool call updated_at cannot be earlier than created_at.")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValidationError("tool call completed_at cannot be earlier than created_at.")

    def copy(self) -> Self:
        return type(self)(
            tool_call_record_id=self.tool_call_record_id,
            session_id=self.session_id,
            run_id=self.run_id,
            agent_id=self.agent_id,
            tool_name=self.tool_name,
            status=self.status,
            arguments=dict(self.arguments),
            task_id=self.task_id,
            tool_call_id=self.tool_call_id,
            input_hash=self.input_hash,
            idempotency_key=self.idempotency_key,
            result_content=self.result_content,
            result_refs=dict(self.result_refs),
            error=self.error,
            created_at=self.created_at,
            updated_at=self.updated_at,
            completed_at=self.completed_at,
        )


def _normalize_status(status: str) -> str:
    normalized = _require_non_empty("tool call status", status).lower()
    if normalized not in _TOOL_CALL_STATUSES:
        raise ValidationError(f"tool call status is invalid: {normalized}")
    return normalized


def _require_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _normalize_optional_string(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_non_empty(name, value)
