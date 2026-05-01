"""JSONL-backed session repository."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import SessionNotFoundError, StorageError, ValidationError
from app.domain.models import EventRecord, SessionFile, SessionMeta
from app.infra.storage.session_io import utc_now, write_json_atomically
from app.infra.storage.session_serializers import (
    event_from_payload,
    event_to_payload,
    file_from_payload,
    file_to_payload,
    is_activatable_file_status,
    session_meta_from_payload,
    session_meta_to_payload,
    validate_file_id,
)

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
        files_path = session_dir / "files.json"
        workspace_path = session_dir / "workspace"

        if metadata_path.exists():
            loaded = self.get_session(session_id)
            if loaded is None:
                raise StorageError(f"Session metadata exists but cannot be read: {session_id}")
            return loaded

        now = utc_now()
        meta = SessionMeta(
            session_id=session_id,
            title="New Session",
            created_at=now,
            updated_at=now,
            is_pinned=False,
            pinned_at=None,
            participants=[],
            entry_agent_id=None,
        )
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            workspace_path.mkdir(parents=True, exist_ok=True)
            events_path.touch(exist_ok=True)
            write_json_atomically(
                files_path,
                {"files": [], "active_file_ids": []},
                error_prefix=f"Failed to initialize files manifest for '{session_id}'",
            )
            write_json_atomically(
                metadata_path,
                session_meta_to_payload(meta),
                error_prefix=f"Failed to initialize metadata for '{session_id}'",
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
            if not isinstance(data, dict):
                raise StorageError(f"Invalid session metadata for '{session_id}': root must be object.")
            return session_meta_from_payload(data)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
            raise StorageError(f"Failed to read session metadata for '{session_id}': {exc}") from exc

    def update_session_title(self, session_id: str, title: str) -> SessionMeta:
        session_id = self._validate_session_id(session_id)
        normalized_title = str(title).strip()
        if not normalized_title:
            raise ValidationError("title must be a non-empty string.")
        return self._update_session_metadata(session_id, title=normalized_title)

    def update_session_pin(self, session_id: str, is_pinned: bool) -> SessionMeta:
        if not isinstance(is_pinned, bool):
            raise ValidationError("is_pinned must be bool.")
        session_id = self._validate_session_id(session_id)
        return self._update_session_metadata(session_id, is_pinned=is_pinned)

    def _update_session_metadata(
        self,
        session_id: str,
        *,
        title: str | None = None,
        is_pinned: bool | None = None,
    ) -> SessionMeta:
        meta = self.get_session(session_id)
        if meta is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        normalized_title = meta.title if title is None else str(title).strip()
        if not normalized_title:
            raise ValidationError("title must be a non-empty string.")
        resolved_is_pinned = meta.is_pinned if is_pinned is None else is_pinned
        resolved_pinned_at = meta.pinned_at
        if is_pinned is not None:
            resolved_pinned_at = utc_now() if is_pinned else None
        updated = SessionMeta(
            session_id=meta.session_id,
            title=normalized_title,
            created_at=meta.created_at,
            updated_at=utc_now(),
            is_pinned=resolved_is_pinned,
            pinned_at=resolved_pinned_at,
            participants=meta.participants,
            entry_agent_id=meta.entry_agent_id,
        )
        self._write_session_metadata(session_id, updated)
        _logger.info(
            "会话元数据更新完成: session_id=%s title=%s is_pinned=%s",
            session_id,
            normalized_title,
            resolved_is_pinned,
        )
        return updated

    def list_sessions(self) -> list[SessionMeta]:
        """List all sessions sorted by updated_at descending."""
        sessions: list[SessionMeta] = []
        if not self._sessions_dir.exists():
            return sessions
        for entry in sorted(self._sessions_dir.iterdir(), key=lambda p: p.name, reverse=True):
            if not entry.is_dir():
                continue
            meta = self.get_session(entry.name)
            if meta is not None:
                sessions.append(meta)
        sessions.sort(
            key=lambda s: (
                1 if s.is_pinned else 0,
                s.pinned_at or s.updated_at,
                s.updated_at,
            ),
            reverse=True,
        )
        return sessions

    def list_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Reconstruct chat messages from session events."""
        session_id = self._validate_session_id(session_id)
        events_path = self._session_dir(session_id) / "events.jsonl"
        if not events_path.exists():
            raise SessionNotFoundError(f"Session not found: {session_id}")
        messages: list[dict[str, Any]] = []
        try:
            with events_path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    event: dict[str, Any] = json.loads(stripped)
                    etype = event.get("type", "")
                    payload = event.get("payload", {})
                    if etype == "user_message":
                        messages.append({
                            "role": "user",
                            "content": payload.get("content", ""),
                            "created_at": event.get("created_at"),
                        })
                    elif etype == "assistant_message":
                        messages.append({
                            "role": "assistant",
                            "content": payload.get("content", ""),
                            "created_at": event.get("created_at"),
                        })
        except (json.JSONDecodeError, OSError) as exc:
            raise StorageError(f"Failed to read events for '{session_id}': {exc}") from exc
        return messages

    def delete_session(self, session_id: str) -> None:
        session_id = self._validate_session_id(session_id)
        session_dir = self._session_dir(session_id)
        if not session_dir.exists() or not session_dir.is_dir():
            raise SessionNotFoundError(f"Session not found: {session_id}")
        try:
            shutil.rmtree(session_dir)
        except OSError as exc:
            raise StorageError(f"Failed to delete session '{session_id}': {exc}") from exc
        _logger.info("会话删除完成: session_id=%s", session_id)

    def append_event(self, session_id: str, event: EventRecord) -> None:
        session_id = self._validate_session_id(session_id)
        if event.session_id != session_id:
            raise ValidationError("event.session_id must match append target session_id.")
        if self.get_session(session_id) is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        line = event_to_payload(event)
        events_path = self._session_dir(session_id) / "events.jsonl"
        try:
            with events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
            self._touch_updated_at(
                session_id,
                participant=event.agent_id,
                entry_agent_id=event.agent_id if event.type == "run_started" else None,
            )
        except OSError as exc:
            raise StorageError(f"Failed to append event for '{session_id}': {exc}") from exc
        _logger.debug("事件已写入: session_id=%s event_id=%s event_type=%s", session_id, event.event_id, event.type)

    def replace_events(self, session_id: str, events: list[EventRecord]) -> None:
        session_id = self._validate_session_id(session_id)
        self._replace_events_validated(session_id=session_id, events=events)
        _logger.info("会话事件已重写: session_id=%s event_count=%s", session_id, len(events))

    def replace_events_if_unchanged(
        self,
        session_id: str,
        events: list[EventRecord],
        *,
        expected_last_event_id: str,
    ) -> bool:
        session_id = self._validate_session_id(session_id)
        normalized_expected = self._validate_event_id(expected_last_event_id)
        current_events = self.list_events(session_id)
        current_last_event_id = current_events[-1].event_id if current_events else None
        if current_last_event_id != normalized_expected:
            _logger.info(
                "会话事件重写跳过，events 已变化: session_id=%s expected_last=%s current_last=%s",
                session_id,
                normalized_expected,
                current_last_event_id,
            )
            return False
        self._replace_events_validated(session_id=session_id, events=events)
        _logger.info("会话事件已条件重写: session_id=%s event_count=%s", session_id, len(events))
        return True

    def _replace_events_validated(self, *, session_id: str, events: list[EventRecord]) -> None:
        if self.get_session(session_id) is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        if not isinstance(events, list):
            raise ValidationError("events must be a list.")
        lines: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for event in events:
            if not isinstance(event, EventRecord):
                raise ValidationError("events entries must be EventRecord.")
            if event.session_id != session_id:
                raise ValidationError("event.session_id must match replace target session_id.")
            if event.event_id in seen_ids:
                raise ValidationError("event.event_id values must be unique.")
            seen_ids.add(event.event_id)
            lines.append(event_to_payload(event))

        events_path = self._session_dir(session_id) / "events.jsonl"
        tmp_path = events_path.with_name(f".{events_path.name}.{uuid4().hex}.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(json.dumps(line, ensure_ascii=False) + "\n")
            tmp_path.replace(events_path)
            self._touch_updated_at(session_id)
        except OSError as exc:
            raise StorageError(f"Failed to replace events for '{session_id}': {exc}") from exc

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
                    records.append(event_from_payload(payload))
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

    def get_session_root_path(self, session_id: str) -> Path:
        session_id = self._validate_session_id(session_id)
        if self.get_session(session_id) is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        return self._session_dir(session_id)

    def add_or_update_session_file(self, file_record: SessionFile) -> None:
        if not isinstance(file_record, SessionFile):
            raise ValidationError("file_record must be SessionFile.")
        session_id = self._validate_session_id(file_record.session_id)
        if self.get_session(session_id) is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        payload = self._read_files_state(session_id)
        files_payload = payload.get("files")
        if not isinstance(files_payload, list):
            raise StorageError(f"Invalid files manifest for '{session_id}': files must be a list.")

        file_row = file_to_payload(file_record)
        updated_rows: list[dict[str, Any]] = []
        replaced = False
        for row in files_payload:
            if not isinstance(row, dict):
                continue
            if str(row.get("file_id", "")) == file_record.file_id:
                updated_rows.append(file_row)
                replaced = True
            else:
                updated_rows.append(dict(row))
        if not replaced:
            updated_rows.append(file_row)
        payload["files"] = updated_rows
        self._write_files_state(session_id, payload)
        self._touch_updated_at(session_id)

    def list_session_files(self, session_id: str) -> list[SessionFile]:
        session_id = self._validate_session_id(session_id)
        if self.get_session(session_id) is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        payload = self._read_files_state(session_id)
        files_payload = payload.get("files")
        if not isinstance(files_payload, list):
            raise StorageError(f"Invalid files manifest for '{session_id}': files must be a list.")
        output: list[SessionFile] = []
        for row in files_payload:
            if not isinstance(row, dict):
                continue
            output.append(file_from_payload(session_id, row))
        return output

    def get_session_file(self, session_id: str, file_id: str) -> SessionFile | None:
        session_id = self._validate_session_id(session_id)
        normalized_file_id = validate_file_id(file_id)
        for item in self.list_session_files(session_id):
            if item.file_id == normalized_file_id:
                return item
        return None

    def set_active_file_ids(self, session_id: str, file_ids: list[str]) -> list[str]:
        session_id = self._validate_session_id(session_id)
        if not isinstance(file_ids, list):
            raise ValidationError("file_ids must be a list.")
        existing_files = self.list_session_files(session_id)
        existing_ids = {item.file_id for item in existing_files}
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in file_ids:
            if not isinstance(raw, str) or not raw.strip():
                raise ValidationError("file_ids entries must be non-empty strings.")
            file_id = raw.strip()
            if file_id in seen:
                continue
            if file_id not in existing_ids:
                continue
            status = next((item.status for item in existing_files if item.file_id == file_id), "")
            if not is_activatable_file_status(status):
                continue
            normalized.append(file_id)
            seen.add(file_id)
        payload = self._read_files_state(session_id)
        payload["active_file_ids"] = normalized
        self._write_files_state(session_id, payload)
        self._touch_updated_at(session_id)
        return normalized

    def get_active_file_ids(self, session_id: str) -> list[str]:
        session_id = self._validate_session_id(session_id)
        payload = self._read_files_state(session_id)
        active_payload = payload.get("active_file_ids")
        if not isinstance(active_payload, list):
            return []
        existing = {item.file_id: item for item in self.list_session_files(session_id)}
        result: list[str] = []
        for raw in active_payload:
            if not isinstance(raw, str) or not raw.strip():
                continue
            file_id = raw.strip()
            item = existing.get(file_id)
            if item is None or not is_activatable_file_status(item.status):
                continue
            result.append(file_id)
        return result

    def read_session_file_text(self, session_id: str, file_id: str) -> str:
        session_id = self._validate_session_id(session_id)
        normalized_file_id = validate_file_id(file_id)
        file_record = self.get_session_file(session_id, normalized_file_id)
        if file_record is None:
            raise SessionNotFoundError(f"Session file not found: session_id={session_id} file_id={normalized_file_id}")
        if file_record.status != "ready" or file_record.text_relpath is None:
            raise StorageError(f"Session file has no parsed text: session_id={session_id} file_id={normalized_file_id}")
        root = self.get_session_root_path(session_id).resolve()
        text_path = (root / file_record.text_relpath).resolve()
        if not text_path.is_relative_to(root):
            raise StorageError(f"Invalid parsed text path for file_id={normalized_file_id}")
        try:
            return text_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"Failed to read parsed text for file_id={normalized_file_id}: {exc}") from exc

    def _session_dir(self, session_id: str) -> Path:
        return self._sessions_dir / session_id

    def _files_manifest_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "files.json"

    def _read_files_state(self, session_id: str) -> dict[str, Any]:
        path = self._files_manifest_path(session_id)
        if not path.exists():
            initial: dict[str, Any] = {"files": [], "active_file_ids": []}
            self._write_files_state(session_id, initial)
            return initial
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise StorageError(f"Failed to read files manifest for '{session_id}': {exc}") from exc
        if not isinstance(payload, dict):
            raise StorageError(f"Invalid files manifest for '{session_id}': root must be object.")
        payload.setdefault("files", [])
        payload.setdefault("active_file_ids", [])
        return payload

    def _write_files_state(self, session_id: str, payload: dict[str, Any]) -> None:
        path = self._files_manifest_path(session_id)
        write_json_atomically(
            path,
            payload,
            error_prefix=f"Failed to write files manifest for '{session_id}'",
        )

    def _touch_updated_at(
        self,
        session_id: str,
        *,
        participant: str | None = None,
        entry_agent_id: str | None = None,
    ) -> None:
        meta = self.get_session(session_id)
        if meta is None:
            return
        participants = list(meta.participants)
        if isinstance(participant, str) and participant.strip():
            normalized_participant = participant.strip()
            if normalized_participant not in participants:
                participants.append(normalized_participant)
        resolved_entry_agent_id = meta.entry_agent_id
        if isinstance(entry_agent_id, str) and entry_agent_id.strip():
            resolved_entry_agent_id = entry_agent_id.strip()
        updated = SessionMeta(
            session_id=meta.session_id,
            title=meta.title,
            created_at=meta.created_at,
            updated_at=utc_now(),
            is_pinned=meta.is_pinned,
            pinned_at=meta.pinned_at,
            participants=participants,
            entry_agent_id=resolved_entry_agent_id,
        )
        self._write_session_metadata(session_id, updated)

    def _validate_session_id(self, session_id: str) -> str:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        return session_id.strip()

    def _validate_event_id(self, event_id: str) -> str:
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValidationError("event_id must be a non-empty string.")
        return event_id.strip()

    def _write_session_metadata(self, session_id: str, meta: SessionMeta) -> None:
        metadata_path = self._session_dir(session_id) / "metadata.json"
        write_json_atomically(
            metadata_path,
            session_meta_to_payload(meta),
            error_prefix=f"Failed to update metadata for '{session_id}'",
        )
