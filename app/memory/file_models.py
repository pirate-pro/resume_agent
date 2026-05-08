"""Models for the file-first memory layout."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.errors import ValidationError
from app.core.time import from_app_iso, normalize_app_datetime, to_app_iso

__all__ = [
    "MemoryFact",
    "MemorySource",
    "format_memory_time",
    "parse_memory_time",
]


@dataclass(slots=True)
class MemorySource:
    type: str
    session_id: str | None = None
    event_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.type = _require_non_empty("source.type", self.type)
        self.session_id = _normalize_optional("source.session_id", self.session_id)
        self.event_ids = _normalize_string_list(self.event_ids, field_name="source.event_ids")

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "sessionId": self.session_id,
            "eventIds": list(self.event_ids),
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "MemorySource":
        if not isinstance(payload, dict):
            raise ValidationError("memory source must be object.")
        return cls(
            type=str(payload.get("type", "")),
            session_id=_optional_str_from_payload(payload.get("sessionId")),
            event_ids=_string_list_from_payload(payload.get("eventIds")),
        )


@dataclass(slots=True)
class MemoryFact:
    id: str
    content: str
    category: str
    confidence: float
    scope: str
    owner_agent_id: str | None
    visibility: str
    status: str
    created_at: datetime
    updated_at: datetime
    source: MemorySource
    tags: list[str] = field(default_factory=list)
    inject_policy: str = "retrieval"
    promote_state: dict[str, str | None] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = _require_non_empty("id", self.id)
        self.content = _require_non_empty("content", self.content)
        self.category = _require_non_empty("category", self.category)
        self.scope = _normalize_scope(self.scope)
        self.owner_agent_id = _normalize_optional("owner_agent_id", self.owner_agent_id)
        if self.scope == "agent" and self.owner_agent_id is None:
            raise ValidationError("owner_agent_id is required for agent memory facts.")
        if self.scope == "shared" and self.owner_agent_id is not None:
            raise ValidationError("shared memory facts must not have owner_agent_id.")
        self.visibility = _require_non_empty("visibility", self.visibility)
        self.status = _require_non_empty("status", self.status)
        self.confidence = _normalize_confidence(self.confidence)
        self.created_at = _normalize_datetime(self.created_at)
        self.updated_at = _normalize_datetime(self.updated_at)
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at cannot be earlier than created_at.")
        if not isinstance(self.source, MemorySource):
            raise ValidationError("source must be MemorySource.")
        self.tags = _normalize_string_list(self.tags, field_name="tags", lower=True)
        self.inject_policy = _require_non_empty("inject_policy", self.inject_policy)
        self.promote_state = _normalize_optional_metadata(self.promote_state)
        self.metadata = _normalize_metadata(self.metadata)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "confidence": self.confidence,
            "scope": self.scope,
            "ownerAgentId": self.owner_agent_id,
            "visibility": self.visibility,
            "status": self.status,
            "createdAt": format_memory_time(self.created_at),
            "updatedAt": format_memory_time(self.updated_at),
            "source": self.source.to_payload(),
            "tags": list(self.tags),
            "injectPolicy": self.inject_policy,
            "promoteState": dict(self.promote_state),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "MemoryFact":
        if not isinstance(payload, dict):
            raise ValidationError("memory fact must be object.")
        return cls(
            id=str(payload.get("id", "")),
            content=str(payload.get("content", "")),
            category=str(payload.get("category", "fact")),
            confidence=_float_from_payload(payload.get("confidence"), default=0.7),
            scope=str(payload.get("scope", "")),
            owner_agent_id=_optional_str_from_payload(payload.get("ownerAgentId")),
            visibility=str(payload.get("visibility", "")),
            status=str(payload.get("status", "")),
            created_at=parse_memory_time(payload.get("createdAt")),
            updated_at=parse_memory_time(payload.get("updatedAt")),
            source=MemorySource.from_payload(payload.get("source", {})),
            tags=_string_list_from_payload(payload.get("tags")),
            inject_policy=str(payload.get("injectPolicy", "retrieval")),
            promote_state=_optional_metadata_from_payload(payload.get("promoteState")),
            metadata=_metadata_from_payload(payload.get("metadata")),
        )


def format_memory_time(value: datetime) -> str:
    return to_app_iso(value)


def parse_memory_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _normalize_datetime(value)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("datetime value must be a non-empty string.")
    try:
        parsed = from_app_iso(value)
    except ValueError as exc:
        raise ValidationError(f"invalid datetime value: {value}") from exc
    return _normalize_datetime(parsed)


def _normalize_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationError("datetime value must be datetime.")
    return normalize_app_datetime(value)


def _require_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _normalize_optional(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_non_empty(field_name, value)


def _optional_str_from_payload(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _normalize_scope(value: str) -> str:
    normalized = _require_non_empty("scope", value).lower()
    if normalized not in {"shared", "agent"}:
        raise ValidationError("scope must be shared or agent.")
    return normalized


def _normalize_confidence(value: float) -> float:
    if isinstance(value, int):
        value = float(value)
    if not isinstance(value, float):
        raise ValidationError("confidence must be float.")
    if value < 0.0 or value > 1.0:
        raise ValidationError("confidence must be in range [0, 1].")
    return value


def _float_from_payload(value: Any, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float):
        return value
    return default


def _string_list_from_payload(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _normalize_string_list(items: list[str], *, field_name: str, lower: bool = False) -> list[str]:
    if not isinstance(items, list):
        raise ValidationError(f"{field_name} must be list.")
    output: list[str] = []
    seen: set[str] = set()
    for raw in items:
        item = _require_non_empty(field_name, raw)
        if lower:
            item = item.lower()
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _metadata_from_payload(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(raw_value) for key, raw_value in value.items() if str(key).strip() and str(raw_value).strip()}


def _normalize_metadata(value: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValidationError("metadata must be object.")
    return {str(key).strip(): str(raw_value).strip() for key, raw_value in value.items() if str(key).strip()}


def _optional_metadata_from_payload(value: Any) -> dict[str, str | None]:
    if not isinstance(value, dict):
        return {
            "fromScope": None,
            "promotedBy": None,
            "promotedAt": None,
        }
    return {
        "fromScope": _optional_str_from_payload(value.get("fromScope")),
        "promotedBy": _optional_str_from_payload(value.get("promotedBy")),
        "promotedAt": _optional_str_from_payload(value.get("promotedAt")),
    }


def _normalize_optional_metadata(value: dict[str, str | None]) -> dict[str, str | None]:
    if not isinstance(value, dict):
        raise ValidationError("promote_state must be object.")
    return {
        "fromScope": _optional_str_from_payload(value.get("fromScope")),
        "promotedBy": _optional_str_from_payload(value.get("promotedBy")),
        "promotedAt": _optional_str_from_payload(value.get("promotedAt")),
    }
