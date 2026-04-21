"""JSONL-backed session repository."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.errors import SessionNotFoundError, StorageError, ValidationError
from app.domain.models import EventRecord, SessionMeta

__all__ = ["JsonlSessionRepository"]
_logger = logging.getLogger(__name__)


class JsonlSessionRepository:
    """Store session metadata/events in local JSON and JSONL files."""

    def __init__(self, data_dir: Path) -> None:
        if not isinstance(data_dir, Path):
            raise ValidationError("data_dir must be a pathlib.Path.")
        self._data_dir = data_dir
        self._sessions_dir = self._data_dir / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, session_id: str) -> SessionMeta:
        session_id = self._validate_session_id(session_id)
        session_dir = self._session_dir(session_id)
        metadata_path = session_dir / "metadata.json"
        events_path = session_dir / "events.jsonl"
        workspace_path = session_dir / "workspace"

        if metadata_path.exists():
            loaded = self.get_session(session_id)
            if loaded is None:
                raise StorageError(f"Session metadata exists but cannot be read: {session_id}")
            return loaded

        now = _utc_now()
        meta = SessionMeta(
            session_id=session_id,
            title="New Session",
            created_at=now,
            updated_at=now,
        )
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            workspace_path.mkdir(parents=True, exist_ok=True)
            events_path.touch(exist_ok=True)
            metadata_payload = {
                "session_id": meta.session_id,
                "title": meta.title,
                "created_at": _to_iso(meta.created_at),
                "updated_at": _to_iso(meta.updated_at),
            }
            metadata_path.write_text(
                json.dumps(metadata_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise StorageError(f"Failed to create session '{session_id}': {exc}") from exc
        _logger.info("创建会话目录成功: session_id=%s", session_id)
        return meta

    def get_session(self, session_id: str) -> SessionMeta | None:
        session_id = self._validate_session_id(session_id)
        metadata_path = self._session_dir(session_id) / "metadata.json"
        if not metadata_path.exists():
            return None
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            return SessionMeta(
                session_id=str(data["session_id"]),
                title=str(data["title"]),
                created_at=_from_iso(str(data["created_at"])),
                updated_at=_from_iso(str(data["updated_at"])),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
            raise StorageError(f"Failed to read session metadata for '{session_id}': {exc}") from exc

    def append_event(self, session_id: str, event: EventRecord) -> None:
        session_id = self._validate_session_id(session_id)
        if event.session_id != session_id:
            raise ValidationError("event.session_id must match append target session_id.")
        if self.get_session(session_id) is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        line = {
            "event_id": event.event_id,
            "session_id": event.session_id,
            "type": event.type,
            "payload": event.payload,
            "created_at": _to_iso(event.created_at),
        }
        events_path = self._session_dir(session_id) / "events.jsonl"
        try:
            with events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
            self._touch_updated_at(session_id)
        except OSError as exc:
            raise StorageError(f"Failed to append event for '{session_id}': {exc}") from exc
        _logger.debug("事件已写入: session_id=%s event_id=%s event_type=%s", session_id, event.event_id, event.type)

    def list_events(self, session_id: str) -> list[EventRecord]:
        session_id = self._validate_session_id(session_id)
        events_path = self._session_dir(session_id) / "events.jsonl"
        if not events_path.exists():
            raise SessionNotFoundError(f"Session not found: {session_id}")
        records: list[EventRecord] = []
        try:
            with events_path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    payload: dict[str, Any] = json.loads(stripped)
                    records.append(
                        EventRecord(
                            event_id=str(payload["event_id"]),
                            session_id=str(payload["session_id"]),
                            type=str(payload["type"]),
                            payload=dict(payload["payload"]),
                            created_at=_from_iso(str(payload["created_at"])),
                        )
                    )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
            raise StorageError(f"Failed to read events for '{session_id}': {exc}") from exc
        _logger.debug("读取会话事件完成: session_id=%s count=%s", session_id, len(records))
        return records

    def list_recent_events(self, session_id: str, limit: int) -> list[EventRecord]:
        session_id = self._validate_session_id(session_id)
        if limit <= 0:
            raise ValidationError("limit must be a positive integer.")
        all_events = self.list_events(session_id)
        return all_events[-limit:]

    def get_workspace_path(self, session_id: str) -> Path:
        session_id = self._validate_session_id(session_id)
        if self.get_session(session_id) is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        path = self._session_dir(session_id) / "workspace"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _session_dir(self, session_id: str) -> Path:
        return self._sessions_dir / session_id

    def _touch_updated_at(self, session_id: str) -> None:
        meta = self.get_session(session_id)
        if meta is None:
            return
        updated = SessionMeta(
            session_id=meta.session_id,
            title=meta.title,
            created_at=meta.created_at,
            updated_at=_utc_now(),
        )
        metadata_path = self._session_dir(session_id) / "metadata.json"
        payload = {
            "session_id": updated.session_id,
            "title": updated.title,
            "created_at": _to_iso(updated.created_at),
            "updated_at": _to_iso(updated.updated_at),
        }
        try:
            metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"Failed to update metadata for '{session_id}': {exc}") from exc

    def _validate_session_id(self, session_id: str) -> str:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        return session_id.strip()



def _utc_now() -> datetime:
    return datetime.now(UTC)



def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")



def _from_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(UTC)
