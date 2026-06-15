"""JSONL-backed durable workflow instance store."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import SessionNotFoundError, StorageError, ValidationError
from app.domain.workflow_instances import (
    WORKFLOW_STATUS_CANCELLED,
    WORKFLOW_STATUS_COMPLETED,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_WAITING,
    WorkflowInstanceRecord,
)
from app.infra.storage.session_io import utc_now, write_json_atomically
from app.infra.storage.workflow_instance_serializers import (
    workflow_instance_from_payload,
    workflow_instance_to_payload,
)

__all__ = ["JsonlWorkflowInstanceStore"]

_TERMINAL_STATUSES = {
    WORKFLOW_STATUS_CANCELLED,
    WORKFLOW_STATUS_COMPLETED,
    WORKFLOW_STATUS_FAILED,
}


class JsonlWorkflowInstanceStore:
    """Store session-scoped workflow instance snapshots."""

    def __init__(self, data_dir: Path) -> None:
        if not isinstance(data_dir, Path):
            raise ValidationError("data_dir must be a pathlib.Path.")
        self._data_dir = data_dir
        self._sessions_dir = self._data_dir / "sessions"
        self._lock = threading.RLock()

    def create_or_update(
        self,
        *,
        session_id: str,
        workflow_instance_id: str,
        workflow_id: str,
        thread_id: str,
        run_id: str | None,
        status: str,
        phase: str,
        state_snapshot: dict[str, Any],
        pending_interrupt_payload: dict[str, Any] | None = None,
        output_refs: dict[str, Any] | None = None,
        last_error: dict[str, Any] | None = None,
    ) -> WorkflowInstanceRecord:
        session_id = self._require_non_empty("session_id", session_id)
        workflow_instance_id = self._require_non_empty("workflow_instance_id", workflow_instance_id)
        workflow_id = self._require_non_empty("workflow_id", workflow_id)
        thread_id = self._require_non_empty("thread_id", thread_id)
        phase = self._require_non_empty("phase", phase)
        if not isinstance(state_snapshot, dict):
            raise ValidationError("state_snapshot must be a dictionary.")
        if pending_interrupt_payload is not None and not isinstance(pending_interrupt_payload, dict):
            raise ValidationError("pending_interrupt_payload must be a dictionary.")
        if output_refs is not None and not isinstance(output_refs, dict):
            raise ValidationError("output_refs must be a dictionary.")
        if last_error is not None and not isinstance(last_error, dict):
            raise ValidationError("last_error must be a dictionary.")

        now = utc_now()
        with self._lock:
            self._ensure_session_dir(session_id)
            records = self._read_records(session_id)
            output: list[WorkflowInstanceRecord] = []
            existing: WorkflowInstanceRecord | None = None
            for record in records:
                if record.workflow_instance_id == workflow_instance_id:
                    existing = record
                    continue
                output.append(record)
            created_at = existing.created_at if existing is not None else now
            completed_at = now if status in _TERMINAL_STATUSES else None
            if existing is not None and status in _TERMINAL_STATUSES and existing.completed_at is not None:
                completed_at = existing.completed_at
            version = (existing.version + 1) if existing is not None else 1
            normalized_pending_payload = (
                _with_workflow_version(pending_interrupt_payload, version) if pending_interrupt_payload is not None else None
            )
            normalized_snapshot = dict(state_snapshot)
            if normalized_pending_payload is not None:
                normalized_snapshot["pending_question"] = normalized_pending_payload
            record = WorkflowInstanceRecord(
                workflow_instance_id=workflow_instance_id,
                workflow_id=workflow_id,
                session_id=session_id,
                thread_id=thread_id,
                status=status,
                phase=phase,
                run_id=run_id,
                pending_interrupt_payload=normalized_pending_payload,
                output_refs=dict(output_refs or {}),
                last_error=last_error,
                state_snapshot=normalized_snapshot,
                created_at=created_at,
                updated_at=now,
                completed_at=completed_at,
                version=version,
            )
            output.append(record)
            output.sort(key=lambda item: (item.created_at, item.workflow_instance_id))
            self._write_records(session_id, output)
            self._write_instance_snapshot(record)
            return record.copy()

    def prepare_resume(
        self,
        *,
        session_id: str,
        workflow_instance_id: str,
        expected_version: int | None = None,
    ) -> WorkflowInstanceRecord:
        session_id = self._require_non_empty("session_id", session_id)
        workflow_instance_id = self._require_non_empty("workflow_instance_id", workflow_instance_id)
        if expected_version is not None and expected_version <= 0:
            raise ValidationError("expected workflow version must be positive.")
        with self._lock:
            self._ensure_session_dir(session_id)
            record = self._read_instance_snapshot(session_id, workflow_instance_id)
            if record is None:
                for candidate in self._read_records(session_id):
                    if candidate.workflow_instance_id == workflow_instance_id:
                        record = candidate
                        break
            if record is None:
                raise ValidationError("Unknown workflow_instance_id for workflow resume.")
            if record.session_id != session_id:
                raise ValidationError("workflow_instance_id does not belong to the requested session.")
            if record.status != WORKFLOW_STATUS_WAITING:
                raise ValidationError(f"workflow_instance_id is not waiting for input: status={record.status}.")
            if expected_version is None:
                raise ValidationError("expected_version is required when resuming a durable workflow.")
            if record.version != expected_version:
                raise ValidationError(
                    f"workflow resume version conflict: expected={expected_version} actual={record.version}."
                )
            return record.copy()

    def get(self, session_id: str, workflow_instance_id: str) -> WorkflowInstanceRecord | None:
        session_id = self._require_non_empty("session_id", session_id)
        workflow_instance_id = self._require_non_empty("workflow_instance_id", workflow_instance_id)
        with self._lock:
            self._ensure_session_dir(session_id)
            snapshot = self._read_instance_snapshot(session_id, workflow_instance_id)
            if snapshot is not None:
                return snapshot.copy()
            for record in self._read_records(session_id):
                if record.workflow_instance_id == workflow_instance_id:
                    return record.copy()
        return None

    def find_by_instance_id(self, workflow_instance_id: str) -> WorkflowInstanceRecord | None:
        workflow_instance_id = self._require_non_empty("workflow_instance_id", workflow_instance_id)
        with self._lock:
            if not self._sessions_dir.exists():
                return None
            for session_dir in self._sessions_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                session_id = session_dir.name
                snapshot = self._read_instance_snapshot(session_id, workflow_instance_id)
                if snapshot is not None:
                    return snapshot.copy()
                for record in self._read_records(session_id):
                    if record.workflow_instance_id == workflow_instance_id:
                        return record.copy()
        return None

    def list_session_instances(
        self,
        session_id: str,
        *,
        statuses: set[str] | None = None,
    ) -> list[WorkflowInstanceRecord]:
        session_id = self._require_non_empty("session_id", session_id)
        normalized_statuses = {item.strip().lower() for item in statuses} if statuses is not None else None
        with self._lock:
            self._ensure_session_dir(session_id)
            records = self._read_records(session_id)
        if normalized_statuses is not None:
            records = [record for record in records if record.status in normalized_statuses]
        records.sort(key=lambda item: (item.updated_at, item.created_at, item.workflow_instance_id), reverse=True)
        return [record.copy() for record in records]

    def _read_records(self, session_id: str) -> list[WorkflowInstanceRecord]:
        return [workflow_instance_from_payload(row) for row in self._read_jsonl(self._records_path(session_id))]

    def _write_records(self, session_id: str, records: list[WorkflowInstanceRecord]) -> None:
        self._write_jsonl(self._records_path(session_id), [workflow_instance_to_payload(record) for record in records])

    def _read_instance_snapshot(self, session_id: str, workflow_instance_id: str) -> WorkflowInstanceRecord | None:
        path = self._instance_state_path(session_id, workflow_instance_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise StorageError(f"Invalid workflow snapshot '{path}': root must be object.")
            return workflow_instance_from_payload(payload)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError) as exc:
            raise StorageError(f"Failed to read workflow snapshot '{path}': {exc}") from exc

    def _write_instance_snapshot(self, record: WorkflowInstanceRecord) -> None:
        path = self._instance_state_path(record.session_id, record.workflow_instance_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomically(
            path,
            workflow_instance_to_payload(record),
            error_prefix=f"Failed to write workflow snapshot '{record.workflow_instance_id}'",
        )

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
            raise StorageError(f"Failed to read workflow instance file '{path}': {exc}") from exc
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
            raise StorageError(f"Failed to write workflow instance file '{path}': {exc}") from exc

    def _ensure_session_dir(self, session_id: str) -> None:
        path = self._session_dir(session_id)
        if not path.exists() or not path.is_dir():
            raise SessionNotFoundError(f"Session not found: {session_id}")
        self._workflow_dir(session_id).mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        return self._sessions_dir / session_id

    def _workflow_dir(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "workflows"

    def _records_path(self, session_id: str) -> Path:
        return self._workflow_dir(session_id) / "instances.jsonl"

    def _instance_state_path(self, session_id: str, workflow_instance_id: str) -> Path:
        return self._workflow_dir(session_id) / workflow_instance_id / "state.json"

    def _require_non_empty(self, name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{name} must be a non-empty string.")
        return value.strip()


def _with_workflow_version(payload: dict[str, Any], version: int) -> dict[str, Any]:
    output = dict(payload)
    output["workflow_version"] = version
    return output
