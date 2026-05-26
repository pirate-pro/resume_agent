"""JSONL-backed durable tool call ledger."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import SessionNotFoundError, StorageError, ValidationError
from app.domain.tool_calls import (
    TOOL_CALL_STATUS_BLOCKED,
    TOOL_CALL_STATUS_FAILED,
    TOOL_CALL_STATUS_REUSED,
    TOOL_CALL_STATUS_RUNNING,
    TOOL_CALL_STATUS_SUCCEEDED,
    ToolCallRecord,
)
from app.infra.storage.session_io import utc_now
from app.infra.storage.tool_call_serializers import tool_call_from_payload, tool_call_to_payload

__all__ = ["JsonlToolCallLedger"]


class JsonlToolCallLedger:
    """Store session-scoped tool call accounting records."""

    def __init__(self, data_dir: Path) -> None:
        if not isinstance(data_dir, Path):
            raise ValidationError("data_dir must be a pathlib.Path.")
        self._data_dir = data_dir
        self._sessions_dir = self._data_dir / "sessions"
        self._lock = threading.RLock()

    def create_running(
        self,
        *,
        session_id: str,
        run_id: str,
        agent_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        task_id: str | None = None,
        tool_call_id: str | None = None,
        input_hash: str | None = None,
        idempotency_key: str | None = None,
    ) -> ToolCallRecord:
        session_id = self._require_non_empty("session_id", session_id)
        run_id = self._require_non_empty("run_id", run_id)
        agent_id = self._require_non_empty("agent_id", agent_id)
        tool_name = self._require_non_empty("tool_name", tool_name)
        if not isinstance(arguments, dict):
            raise ValidationError("tool call arguments must be a dictionary.")
        now = utc_now()
        record = ToolCallRecord(
            tool_call_record_id=f"tool_call_{uuid4().hex[:12]}",
            session_id=session_id,
            run_id=run_id,
            agent_id=agent_id,
            task_id=task_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            input_hash=input_hash,
            idempotency_key=idempotency_key,
            status=TOOL_CALL_STATUS_RUNNING,
            arguments=dict(arguments),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._ensure_session_dir(session_id)
            records = self._read_records(session_id)
            records.append(record)
            self._write_records(session_id, records)
        return record.copy()

    def find_latest_by_idempotency_key(
        self,
        *,
        session_id: str,
        tool_name: str,
        idempotency_key: str,
    ) -> ToolCallRecord | None:
        session_id = self._require_non_empty("session_id", session_id)
        tool_name = self._require_non_empty("tool_name", tool_name)
        idempotency_key = self._require_non_empty("idempotency_key", idempotency_key)
        with self._lock:
            self._ensure_session_dir(session_id)
            matches = [
                record
                for record in self._read_records(session_id)
                if record.tool_name == tool_name and record.idempotency_key == idempotency_key
            ]
        if not matches:
            return None
        return max(matches, key=_record_updated_at).copy()

    def find_latest_success_by_input_hash(
        self,
        *,
        session_id: str,
        run_id: str,
        agent_id: str,
        tool_name: str,
        input_hash: str,
        task_id: str | None = None,
    ) -> ToolCallRecord | None:
        session_id = self._require_non_empty("session_id", session_id)
        run_id = self._require_non_empty("run_id", run_id)
        agent_id = self._require_non_empty("agent_id", agent_id)
        tool_name = self._require_non_empty("tool_name", tool_name)
        input_hash = self._require_non_empty("input_hash", input_hash)
        if task_id is not None:
            task_id = self._require_non_empty("task_id", task_id)
        with self._lock:
            self._ensure_session_dir(session_id)
            records = self._read_records(session_id)
            if task_id is not None:
                matches = [
                    record
                    for record in records
                    if record.task_id == task_id
                    and record.tool_name == tool_name
                    and record.input_hash == input_hash
                    and record.status in {TOOL_CALL_STATUS_SUCCEEDED, TOOL_CALL_STATUS_REUSED}
                    and record.result_content is not None
                ]
            else:
                matches = [
                    record
                    for record in records
                    if record.run_id == run_id
                    and record.agent_id == agent_id
                    and record.tool_name == tool_name
                    and record.input_hash == input_hash
                    and record.status in {TOOL_CALL_STATUS_SUCCEEDED, TOOL_CALL_STATUS_REUSED}
                    and record.result_content is not None
                ]
        if not matches:
            return None
        return max(matches, key=_record_updated_at).copy()

    def mark_succeeded(
        self,
        session_id: str,
        tool_call_record_id: str,
        *,
        result_content: str,
        result_refs: dict[str, Any] | None = None,
    ) -> ToolCallRecord:
        return self._update_record(
            session_id,
            tool_call_record_id,
            status=TOOL_CALL_STATUS_SUCCEEDED,
            result_content=result_content,
            result_refs=result_refs,
            completed=True,
            clear_error=True,
        )

    def mark_failed(self, session_id: str, tool_call_record_id: str, *, error: str) -> ToolCallRecord:
        return self._update_record(
            session_id,
            tool_call_record_id,
            status=TOOL_CALL_STATUS_FAILED,
            error=error,
            completed=True,
        )

    def mark_reused(
        self,
        session_id: str,
        tool_call_record_id: str,
        *,
        result_content: str,
        result_refs: dict[str, Any] | None = None,
    ) -> ToolCallRecord:
        return self._update_record(
            session_id,
            tool_call_record_id,
            status=TOOL_CALL_STATUS_REUSED,
            result_content=result_content,
            result_refs=result_refs,
            completed=True,
            clear_error=True,
        )

    def mark_blocked(
        self,
        session_id: str,
        tool_call_record_id: str,
        *,
        result_content: str,
        result_refs: dict[str, Any] | None = None,
    ) -> ToolCallRecord:
        return self._update_record(
            session_id,
            tool_call_record_id,
            status=TOOL_CALL_STATUS_BLOCKED,
            result_content=result_content,
            result_refs=result_refs,
            completed=True,
            clear_error=True,
        )

    def _update_record(
        self,
        session_id: str,
        tool_call_record_id: str,
        *,
        status: str,
        result_content: str | None = None,
        result_refs: dict[str, Any] | None = None,
        error: str | None = None,
        completed: bool = False,
        clear_error: bool = False,
    ) -> ToolCallRecord:
        session_id = self._require_non_empty("session_id", session_id)
        tool_call_record_id = self._require_non_empty("tool_call_record_id", tool_call_record_id)
        now = utc_now()
        with self._lock:
            self._ensure_session_dir(session_id)
            records = self._read_records(session_id)
            updated: ToolCallRecord | None = None
            output: list[ToolCallRecord] = []
            for record in records:
                if record.tool_call_record_id != tool_call_record_id:
                    output.append(record)
                    continue
                updated = ToolCallRecord(
                    tool_call_record_id=record.tool_call_record_id,
                    session_id=record.session_id,
                    run_id=record.run_id,
                    agent_id=record.agent_id,
                    task_id=record.task_id,
                    tool_name=record.tool_name,
                    tool_call_id=record.tool_call_id,
                    input_hash=record.input_hash,
                    idempotency_key=record.idempotency_key,
                    status=status,
                    arguments=record.arguments,
                    result_content=result_content if result_content is not None else record.result_content,
                    result_refs=result_refs if result_refs is not None else record.result_refs,
                    error=None if clear_error else (error if error is not None else record.error),
                    created_at=record.created_at,
                    updated_at=now,
                    completed_at=now if completed else record.completed_at,
                )
                output.append(updated)
            if updated is None:
                raise ValidationError(f"Unknown tool_call_record_id: {tool_call_record_id}")
            self._write_records(session_id, output)
            return updated.copy()

    def _read_records(self, session_id: str) -> list[ToolCallRecord]:
        return [tool_call_from_payload(row) for row in self._read_jsonl(self._records_path(session_id))]

    def _write_records(self, session_id: str, records: list[ToolCallRecord]) -> None:
        self._write_jsonl(self._records_path(session_id), [tool_call_to_payload(record) for record in records])

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    payload = json.loads(stripped)
                    if not isinstance(payload, dict):
                        raise StorageError(f"Invalid JSONL row in '{path}': row must be object.")
                    rows.append(payload)
        except (json.JSONDecodeError, OSError) as exc:
            raise StorageError(f"Failed to read tool call ledger file '{path}': {exc}") from exc
        return rows

    def _write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> None:
        temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with temp_path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            temp_path.replace(path)
        except OSError as exc:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            raise StorageError(f"Failed to write tool call ledger file '{path}': {exc}") from exc

    def _ensure_session_dir(self, session_id: str) -> None:
        path = self._session_dir(session_id)
        if not path.exists() or not path.is_dir():
            raise SessionNotFoundError(f"Session not found: {session_id}")
        self._tool_call_dir(session_id).mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        return self._sessions_dir / session_id

    def _tool_call_dir(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "tool_calls"

    def _records_path(self, session_id: str) -> Path:
        return self._tool_call_dir(session_id) / "tool_calls.jsonl"

    def _require_non_empty(self, name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{name} must be a non-empty string.")
        return value.strip()


def _record_updated_at(record: ToolCallRecord) -> datetime:
    if record.updated_at is None:
        raise ValidationError("tool call updated_at is required.")
    return record.updated_at
