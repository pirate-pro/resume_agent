"""Serialization helpers for current-schema memory records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.errors import ValidationError
from app.memory.models import MemoryRecord, MemoryScope, MemoryStatus, MemoryType, make_content_hash

__all__ = [
    "memory_payload_to_record",
    "memory_record_to_payload",
]


def memory_record_to_payload(record: MemoryRecord) -> dict[str, Any]:
    return {
        "memory_id": record.memory_id,
        "scope": record.scope.value,
        "owner_agent_id": record.owner_agent_id,
        "session_id": record.session_id,
        "memory_type": record.memory_type.value,
        "content": record.content,
        "tags": record.tags,
        "importance": record.importance,
        "confidence": record.confidence,
        "status": record.status.value,
        "created_at": _to_iso(record.created_at),
        "updated_at": _to_iso(record.updated_at),
        "expires_at": None if record.expires_at is None else _to_iso(record.expires_at),
        "source_event_id": record.source_event_id,
        "source_agent_id": record.source_agent_id,
        "version": record.version,
        "parent_memory_id": record.parent_memory_id,
        "content_hash": record.content_hash or make_content_hash(record.content),
        "metadata": record.metadata,
    }


def memory_payload_to_record(payload: dict[str, Any]) -> MemoryRecord:
    _require_payload_keys(
        payload,
        [
            "memory_id",
            "scope",
            "owner_agent_id",
            "session_id",
            "memory_type",
            "content",
            "tags",
            "importance",
            "confidence",
            "status",
            "created_at",
            "updated_at",
            "expires_at",
            "source_event_id",
            "source_agent_id",
            "version",
            "parent_memory_id",
            "content_hash",
            "metadata",
        ],
    )
    try:
        return MemoryRecord(
            memory_id=str(payload["memory_id"]),
            scope=MemoryScope(str(payload["scope"])),
            owner_agent_id=None if payload["owner_agent_id"] is None else str(payload["owner_agent_id"]),
            session_id=None if payload["session_id"] is None else str(payload["session_id"]),
            memory_type=MemoryType(str(payload["memory_type"])),
            content=str(payload["content"]),
            tags=_normalize_payload_string_list(payload["tags"], "tags"),
            importance=float(payload["importance"]),
            confidence=float(payload["confidence"]),
            status=MemoryStatus(str(payload["status"])),
            created_at=_from_iso(str(payload["created_at"])),
            updated_at=_from_iso(str(payload["updated_at"])),
            expires_at=None if payload["expires_at"] is None else _from_iso(str(payload["expires_at"])),
            source_event_id=None if payload["source_event_id"] is None else str(payload["source_event_id"]),
            source_agent_id=None if payload["source_agent_id"] is None else str(payload["source_agent_id"]),
            version=int(payload["version"]),
            parent_memory_id=None if payload["parent_memory_id"] is None else str(payload["parent_memory_id"]),
            content_hash=str(payload["content_hash"]),
            metadata=_normalize_payload_metadata(payload["metadata"]),
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid memory record payload: {exc}") from exc


def _require_payload_keys(payload: dict[str, Any], keys: list[str]) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ValidationError(f"memory payload missing required fields: {', '.join(missing)}")


def _normalize_payload_metadata(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValidationError("metadata must be a dictionary.")
    return {str(key): str(item) for key, item in value.items()}


def _normalize_payload_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list.")
    return [str(item) for item in value]


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _from_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(UTC)
