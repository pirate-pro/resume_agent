"""JSONL-backed storage for state records."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.errors import StorageError, ValidationError
from app.state.models import StateRecord, StateScope, StateStatus

__all__ = ["JsonlFileStateStore"]
_logger = logging.getLogger(__name__)


class JsonlFileStateStore:
    """Persist state records in per-agent and shared JSONL files."""

    def __init__(self, root_dir: Path) -> None:
        if not isinstance(root_dir, Path):
            raise ValidationError("root_dir must be pathlib.Path.")
        self._root_dir = root_dir
        self._agents_dir = self._root_dir / "agents"
        self._shared_dir = self._root_dir / "shared"
        self._agents_dir.mkdir(parents=True, exist_ok=True)
        self._shared_dir.mkdir(parents=True, exist_ok=True)

    def upsert_record(self, record: StateRecord) -> None:
        if not isinstance(record, StateRecord):
            raise ValidationError("record must be StateRecord.")
        path = self._record_file_for(record.scope, session_id=record.session_id, agent_id=record.owner_agent_id)
        rows = _read_jsonl_rows(path)
        record_payload = _record_to_payload(record)
        output: list[dict[str, Any]] = []
        replaced = False
        for row in rows:
            if str(row.get("key", "")).strip() == record.key:
                output.append(record_payload)
                replaced = True
            else:
                output.append(row)
        if not replaced:
            output.append(record_payload)
        _write_jsonl_rows(path, output)

    def get_record(
        self,
        *,
        scope: StateScope,
        session_id: str,
        key: str,
        agent_id: str | None = None,
        include_archived: bool = False,
    ) -> StateRecord | None:
        normalized_key = _require_non_empty("key", key)
        for record in self.list_records(
            scope=scope,
            session_id=session_id,
            agent_id=agent_id,
            include_archived=include_archived,
        ):
            if record.key == normalized_key:
                return record
        return None

    def list_records(
        self,
        *,
        scope: StateScope,
        session_id: str,
        agent_id: str | None = None,
        include_archived: bool = False,
    ) -> list[StateRecord]:
        path = self._record_file_for(scope, session_id=session_id, agent_id=agent_id)
        records: list[StateRecord] = []
        for row in _read_jsonl_rows(path):
            try:
                record = _payload_to_record(row)
            except ValidationError as exc:
                _logger.warning("state record 不合法，已跳过: path=%s error=%s row=%s", path, exc, row)
                continue
            if not include_archived and record.status != StateStatus.ACTIVE:
                continue
            records.append(record)
        records.sort(key=lambda item: (item.updated_at, item.created_at, item.key), reverse=True)
        return records

    def archive_records(
        self,
        *,
        scope: StateScope,
        session_id: str,
        keys: list[str] | None,
        now: datetime,
        agent_id: str | None = None,
    ) -> int:
        path = self._record_file_for(scope, session_id=session_id, agent_id=agent_id)
        rows = _read_jsonl_rows(path)
        if not rows:
            return 0
        target_keys = {item for item in keys} if keys is not None else None
        touched = 0
        output: list[dict[str, Any]] = []
        for row in rows:
            try:
                record = _payload_to_record(row)
            except ValidationError:
                output.append(row)
                continue
            if record.status == StateStatus.ARCHIVED:
                output.append(row)
                continue
            if target_keys is not None and record.key not in target_keys:
                output.append(row)
                continue
            updated = StateRecord(
                state_id=record.state_id,
                scope=record.scope,
                owner_agent_id=record.owner_agent_id,
                session_id=record.session_id,
                key=record.key,
                value=record.value,
                status=StateStatus.ARCHIVED,
                created_at=record.created_at,
                updated_at=now,
                version=record.version + 1,
                source_run_id=record.source_run_id,
                metadata=record.metadata,
            )
            output.append(_record_to_payload(updated))
            touched += 1
        if touched > 0:
            _write_jsonl_rows(path, output)
        return touched

    def _record_file_for(self, scope: StateScope, *, session_id: str, agent_id: str | None) -> Path:
        normalized_session_id = _require_non_empty("session_id", session_id)
        if scope == StateScope.AGENT_SESSION:
            normalized_agent_id = _require_non_empty("agent_id", agent_id or "")
            return self._agents_dir / normalized_agent_id / "sessions" / f"{normalized_session_id}.jsonl"
        return self._shared_dir / "sessions" / f"{normalized_session_id}.jsonl"


def _record_to_payload(record: StateRecord) -> dict[str, Any]:
    return {
        "state_id": record.state_id,
        "scope": record.scope.value,
        "owner_agent_id": record.owner_agent_id,
        "session_id": record.session_id,
        "key": record.key,
        "value": record.value,
        "status": record.status.value,
        "created_at": _to_iso(record.created_at),
        "updated_at": _to_iso(record.updated_at),
        "version": record.version,
        "source_run_id": record.source_run_id,
        "metadata": record.metadata,
    }


def _payload_to_record(payload: dict[str, Any]) -> StateRecord:
    return StateRecord(
        state_id=str(payload["state_id"]),
        scope=StateScope(str(payload["scope"])),
        owner_agent_id=str(payload["owner_agent_id"]),
        session_id=str(payload["session_id"]),
        key=str(payload["key"]),
        value=str(payload["value"]),
        status=StateStatus(str(payload.get("status", StateStatus.ACTIVE.value))),
        created_at=_from_iso(str(payload["created_at"])),
        updated_at=_from_iso(str(payload["updated_at"])),
        version=int(payload.get("version", 1)),
        source_run_id=None if payload.get("source_run_id") is None else str(payload["source_run_id"]),
        metadata={str(key): str(value) for key, value in dict(payload.get("metadata", {})).items()},
    )


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                stripped = raw.strip()
                if not stripped:
                    continue
                payload = json.loads(stripped)
                if isinstance(payload, dict):
                    rows.append(payload)
    except OSError as exc:
        raise StorageError(f"Failed to read state jsonl '{path}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise StorageError(f"Invalid state JSONL format '{path}': {exc}") from exc
    return rows


def _write_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp_path.replace(path)
    except OSError as exc:
        raise StorageError(f"Failed to rewrite state jsonl '{path}': {exc}") from exc


def _require_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _from_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(UTC)
