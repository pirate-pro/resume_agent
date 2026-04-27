"""Domain models for agent/session state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from app.core.errors import ValidationError

__all__ = [
    "StateRecord",
    "StateScope",
    "StateStatus",
]


class StateScope(str, Enum):
    AGENT_SESSION = "agent_session"
    SHARED_SESSION = "shared_session"


class StateStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


@dataclass(slots=True)
class StateRecord:
    state_id: str
    scope: StateScope
    owner_agent_id: str
    session_id: str
    key: str
    value: str
    status: StateStatus
    created_at: datetime
    updated_at: datetime
    version: int = 1
    source_run_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.state_id = _require_non_empty("state_id", self.state_id)
        self.owner_agent_id = _require_non_empty("owner_agent_id", self.owner_agent_id)
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.key = _require_non_empty("key", self.key)
        self.value = _require_non_empty("value", self.value)
        self.created_at = _normalize_datetime("created_at", self.created_at)
        self.updated_at = _normalize_datetime("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at cannot be earlier than created_at.")
        if self.version <= 0:
            raise ValidationError("version must be positive.")
        self.source_run_id = _normalize_optional("source_run_id", self.source_run_id)
        self.metadata = _normalize_metadata(self.metadata)


def _require_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _normalize_optional(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_non_empty(field_name, value)


def _normalize_datetime(field_name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationError(f"{field_name} must be datetime.")
    return value.astimezone(UTC)


def _normalize_metadata(metadata: dict[str, str]) -> dict[str, str]:
    if not isinstance(metadata, dict):
        raise ValidationError("metadata must be a dictionary.")
    normalized: dict[str, str] = {}
    for raw_key, raw_value in metadata.items():
        key = _require_non_empty("metadata key", str(raw_key))
        value = _require_non_empty("metadata value", str(raw_value))
        normalized[key] = value
    return normalized
