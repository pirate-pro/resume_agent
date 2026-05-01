"""Payload serializers for JSONL session storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.errors import StorageError, ValidationError
from app.domain.models import EventRecord, SessionFile, SessionMeta
from app.infra.storage.session_io import from_iso, to_iso

__all__ = [
    "event_from_payload",
    "event_to_payload",
    "file_from_payload",
    "file_to_payload",
    "is_activatable_file_status",
    "read_optional_text",
    "session_meta_from_payload",
    "session_meta_to_payload",
    "validate_file_id",
]


def session_meta_to_payload(meta: SessionMeta) -> dict[str, Any]:
    return {
        "session_id": meta.session_id,
        "title": meta.title,
        "created_at": to_iso(meta.created_at),
        "updated_at": to_iso(meta.updated_at),
        "is_pinned": meta.is_pinned,
        "pinned_at": to_iso(meta.pinned_at) if meta.pinned_at is not None else None,
        "participants": meta.participants,
        "entry_agent_id": meta.entry_agent_id,
    }


def session_meta_from_payload(data: dict[str, Any]) -> SessionMeta:
    return SessionMeta(
        session_id=str(data["session_id"]),
        title=str(data["title"]),
        created_at=from_iso(str(data["created_at"])),
        updated_at=from_iso(str(data["updated_at"])),
        is_pinned=_read_bool_payload(data.get("is_pinned")),
        pinned_at=_read_optional_datetime(data.get("pinned_at")),
        participants=_read_participants_payload(data.get("participants")),
        entry_agent_id=read_optional_text(data.get("entry_agent_id")),
    )


def event_to_payload(event: EventRecord) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "session_id": event.session_id,
        "agent_id": event.agent_id,
        "run_id": event.run_id,
        "parent_run_id": event.parent_run_id,
        "event_version": event.event_version,
        "type": event.type,
        "payload": event.payload,
        "created_at": to_iso(event.created_at),
    }


def event_from_payload(payload: dict[str, Any]) -> EventRecord:
    return EventRecord(
        event_id=str(payload["event_id"]),
        session_id=str(payload["session_id"]),
        type=str(payload["type"]),
        payload=dict(payload["payload"]),
        created_at=from_iso(str(payload["created_at"])),
        agent_id=read_optional_text(payload.get("agent_id")) or "agent_main",
        run_id=read_optional_text(payload.get("run_id")) or f"run_legacy_{str(payload['session_id'])}",
        parent_run_id=read_optional_text(payload.get("parent_run_id")),
        event_version=_read_event_version(payload.get("event_version")),
    )


def file_to_payload(item: SessionFile) -> dict[str, Any]:
    return {
        "file_id": item.file_id,
        "filename": item.filename,
        "media_type": item.media_type,
        "size_bytes": item.size_bytes,
        "status": item.status,
        "uploaded_at": to_iso(item.uploaded_at),
        "storage_relpath": item.storage_relpath,
        "text_relpath": item.text_relpath,
        "error": item.error,
        "parsed_char_count": item.parsed_char_count,
        "parsed_token_estimate": item.parsed_token_estimate,
        "parsed_at": None if item.parsed_at is None else to_iso(item.parsed_at),
    }


def file_from_payload(session_id: str, payload: dict[str, Any]) -> SessionFile:
    try:
        return SessionFile(
            file_id=str(payload["file_id"]),
            session_id=session_id,
            filename=str(payload["filename"]),
            media_type=str(payload["media_type"]),
            size_bytes=int(payload["size_bytes"]),
            status=str(payload["status"]),
            uploaded_at=from_iso(str(payload["uploaded_at"])),
            storage_relpath=str(payload["storage_relpath"]),
            text_relpath=None if payload.get("text_relpath") is None else str(payload["text_relpath"]),
            error=None if payload.get("error") is None else str(payload["error"]),
            parsed_char_count=None
            if payload.get("parsed_char_count") is None
            else int(payload["parsed_char_count"]),
            parsed_token_estimate=None
            if payload.get("parsed_token_estimate") is None
            else int(payload["parsed_token_estimate"]),
            parsed_at=None if payload.get("parsed_at") is None else from_iso(str(payload["parsed_at"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError(f"Invalid session file payload for '{session_id}': {exc}") from exc


def read_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def validate_file_id(file_id: str) -> str:
    if not isinstance(file_id, str) or not file_id.strip():
        raise ValidationError("file_id must be a non-empty string.")
    return file_id.strip()


def is_activatable_file_status(status: str) -> bool:
    return status in {"uploaded", "ready"}


def _read_optional_datetime(value: Any) -> datetime | None:
    text = read_optional_text(value)
    if text is None:
        return None
    return from_iso(text)


def _read_bool_payload(value: Any) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise StorageError("Invalid session metadata: is_pinned must be bool.")
    return value


def _read_participants_payload(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str):
            continue
        participant = raw.strip()
        if not participant or participant in seen:
            continue
        normalized.append(participant)
        seen.add(participant)
    return normalized


def _read_event_version(value: Any) -> int:
    if value is None:
        return 2
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 2
    return parsed if parsed > 0 else 2
