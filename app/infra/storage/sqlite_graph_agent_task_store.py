"""SQLite-backed task-attempt ledger for LangGraph child agents."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from app.core.errors import ValidationError
from app.core.time import app_now, from_app_iso, to_app_iso
from app.domain.graph_agent_tasks import (
    GRAPH_TASK_STATUS_COMPLETED,
    GRAPH_TASK_STATUS_FAILED,
    GRAPH_TASK_STATUS_QUEUED,
    GRAPH_TASK_STATUS_RUNNING,
    GraphAgentTaskAttemptRecord,
    GraphAgentTaskAttemptSpec,
)

__all__ = ["SqliteGraphAgentTaskStore"]


class SqliteGraphAgentTaskStore:
    """Persist graph task attempts and atomically claim cross-process leases."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise ValidationError("graph agent task store path must be a pathlib.Path.")
        self._path = path
        self._setup()

    def ensure_attempt(
        self,
        spec: GraphAgentTaskAttemptSpec,
        *,
        retry_failed: bool = False,
    ) -> GraphAgentTaskAttemptRecord:
        if not isinstance(spec, GraphAgentTaskAttemptSpec):
            raise ValidationError("spec must be GraphAgentTaskAttemptSpec.")
        now = app_now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            latest = conn.execute(
                """
                SELECT * FROM graph_agent_task_attempts
                WHERE session_id = ? AND workflow_instance_id = ? AND task_key = ?
                ORDER BY attempt DESC
                LIMIT 1
                """,
                (spec.session_id, spec.workflow_instance_id, spec.task_key),
            ).fetchone()
            if latest is not None:
                record = _record_from_row(latest)
                if record.execution_key != spec.execution_key:
                    raise ValidationError(
                        f"task inputs changed for existing workflow task: {spec.task_key}."
                    )
                if record.status != GRAPH_TASK_STATUS_FAILED or not retry_failed:
                    conn.commit()
                    return record
            attempt = 1 if latest is None else int(latest["attempt"]) + 1
            attempt_id = f"graph_task_{uuid4().hex[:16]}"
            conn.execute(
                """
                INSERT INTO graph_agent_task_attempts (
                    attempt_id, session_id, workflow_instance_id, execution_key,
                    task_key, attempt, target_agent_id, instruction, constraints_json,
                    artifact_refs_json, skill_names_json, max_tool_rounds, status,
                    child_run_id, summary, error, output_artifact_refs_json,
                    product_refs_json, lease_owner_id, lease_expires_at,
                    created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, NULL, NULL, ?, ?, NULL)
                """,
                (
                    attempt_id,
                    spec.session_id,
                    spec.workflow_instance_id,
                    spec.execution_key,
                    spec.task_key,
                    attempt,
                    spec.target_agent_id,
                    spec.instruction,
                    _json(spec.constraints),
                    _json(spec.artifact_refs),
                    _json(spec.skill_names),
                    spec.max_tool_rounds,
                    GRAPH_TASK_STATUS_QUEUED,
                    _json(()),
                    _json(()),
                    to_app_iso(now),
                    to_app_iso(now),
                ),
            )
            conn.commit()
        loaded = self.get_attempt(attempt_id)
        if loaded is None:
            raise ValidationError(f"failed to reload graph task attempt: {attempt_id}")
        return loaded

    def get_attempt(self, attempt_id: str) -> GraphAgentTaskAttemptRecord | None:
        attempt_id = _require_non_empty("attempt_id", attempt_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM graph_agent_task_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        return None if row is None else _record_from_row(row)

    def latest_attempt(
        self,
        *,
        session_id: str,
        workflow_instance_id: str,
        task_key: str,
    ) -> GraphAgentTaskAttemptRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM graph_agent_task_attempts
                WHERE session_id = ? AND workflow_instance_id = ? AND task_key = ?
                ORDER BY attempt DESC
                LIMIT 1
                """,
                (
                    _require_non_empty("session_id", session_id),
                    _require_non_empty("workflow_instance_id", workflow_instance_id),
                    _require_non_empty("task_key", task_key),
                ),
            ).fetchone()
        return None if row is None else _record_from_row(row)

    def list_workflow_attempts(
        self,
        *,
        session_id: str,
        workflow_instance_id: str,
    ) -> list[GraphAgentTaskAttemptRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM graph_agent_task_attempts
                WHERE session_id = ? AND workflow_instance_id = ?
                ORDER BY task_key, attempt
                """,
                (
                    _require_non_empty("session_id", session_id),
                    _require_non_empty("workflow_instance_id", workflow_instance_id),
                ),
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def claim_attempt(
        self,
        attempt_id: str,
        *,
        owner_id: str,
        child_run_id: str,
        ttl_seconds: float,
    ) -> GraphAgentTaskAttemptRecord:
        attempt_id = _require_non_empty("attempt_id", attempt_id)
        owner_id = _require_non_empty("owner_id", owner_id)
        child_run_id = _require_non_empty("child_run_id", child_run_id)
        if ttl_seconds <= 0:
            raise ValidationError("graph task lease ttl_seconds must be positive.")
        now = app_now()
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _required_attempt_row(conn, attempt_id)
            record = _record_from_row(row)
            if record.status == GRAPH_TASK_STATUS_RUNNING:
                if record.lease_expires_at is not None and record.lease_expires_at <= now:
                    raise ValidationError(
                        f"graph task attempt lease expired and requires reconciliation: {attempt_id}."
                    )
                raise ValidationError(f"graph task attempt is already running: {attempt_id}.")
            if record.status != GRAPH_TASK_STATUS_QUEUED:
                raise ValidationError(
                    f"graph task attempt cannot be claimed from status={record.status}: {attempt_id}."
                )
            conn.execute(
                """
                UPDATE graph_agent_task_attempts
                SET status = ?, child_run_id = ?, lease_owner_id = ?, lease_expires_at = ?, updated_at = ?
                WHERE attempt_id = ?
                """,
                (
                    GRAPH_TASK_STATUS_RUNNING,
                    child_run_id,
                    owner_id,
                    to_app_iso(expires_at),
                    to_app_iso(now),
                    attempt_id,
                ),
            )
            conn.commit()
        return _required_attempt(self, attempt_id)

    def mark_completed(
        self,
        attempt_id: str,
        *,
        owner_id: str,
        summary: str,
        output_artifact_refs: list[str],
        product_refs: list[str],
    ) -> GraphAgentTaskAttemptRecord:
        return self._finish_attempt(
            attempt_id,
            owner_id=owner_id,
            status=GRAPH_TASK_STATUS_COMPLETED,
            summary=_require_non_empty("summary", summary),
            error=None,
            output_artifact_refs=output_artifact_refs,
            product_refs=product_refs,
        )

    def mark_failed(
        self,
        attempt_id: str,
        *,
        owner_id: str,
        error: str,
    ) -> GraphAgentTaskAttemptRecord:
        return self._finish_attempt(
            attempt_id,
            owner_id=owner_id,
            status=GRAPH_TASK_STATUS_FAILED,
            summary=None,
            error=_require_non_empty("error", error),
            output_artifact_refs=[],
            product_refs=[],
        )

    def reconcile_stale_running(self, *, now: datetime | None = None) -> list[GraphAgentTaskAttemptRecord]:
        current = now or app_now()
        current_iso = to_app_iso(current)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT attempt_id FROM graph_agent_task_attempts
                WHERE status = ? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?
                """,
                (GRAPH_TASK_STATUS_RUNNING, current_iso),
            ).fetchall()
            attempt_ids = [str(row["attempt_id"]) for row in rows]
            if attempt_ids:
                placeholders = ",".join("?" for _ in attempt_ids)
                conn.execute(
                    f"""
                    UPDATE graph_agent_task_attempts
                    SET status = ?, error = ?, lease_owner_id = NULL, lease_expires_at = NULL,
                        updated_at = ?, completed_at = ?
                    WHERE attempt_id IN ({placeholders})
                    """,
                    (
                        GRAPH_TASK_STATUS_FAILED,
                        "task process stopped before completion; retry is required",
                        current_iso,
                        current_iso,
                        *attempt_ids,
                    ),
                )
            conn.commit()
        return [
            record
            for attempt_id in attempt_ids
            if (record := self.get_attempt(attempt_id)) is not None
        ]

    def _finish_attempt(
        self,
        attempt_id: str,
        *,
        owner_id: str,
        status: str,
        summary: str | None,
        error: str | None,
        output_artifact_refs: list[str],
        product_refs: list[str],
    ) -> GraphAgentTaskAttemptRecord:
        attempt_id = _require_non_empty("attempt_id", attempt_id)
        owner_id = _require_non_empty("owner_id", owner_id)
        now = app_now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            record = _record_from_row(_required_attempt_row(conn, attempt_id))
            if record.status != GRAPH_TASK_STATUS_RUNNING or record.lease_owner_id != owner_id:
                raise ValidationError(f"graph task attempt is not owned by {owner_id}: {attempt_id}.")
            conn.execute(
                """
                UPDATE graph_agent_task_attempts
                SET status = ?, summary = ?, error = ?, output_artifact_refs_json = ?,
                    product_refs_json = ?, lease_owner_id = NULL, lease_expires_at = NULL,
                    updated_at = ?, completed_at = ?
                WHERE attempt_id = ?
                """,
                (
                    status,
                    summary,
                    error,
                    _json(output_artifact_refs),
                    _json(product_refs),
                    to_app_iso(now),
                    to_app_iso(now),
                    attempt_id,
                ),
            )
            conn.commit()
        return _required_attempt(self, attempt_id)

    def _setup(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_agent_task_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    workflow_instance_id TEXT NOT NULL,
                    execution_key TEXT NOT NULL,
                    task_key TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    target_agent_id TEXT NOT NULL,
                    instruction TEXT NOT NULL,
                    constraints_json TEXT NOT NULL,
                    artifact_refs_json TEXT NOT NULL,
                    skill_names_json TEXT NOT NULL,
                    max_tool_rounds INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    child_run_id TEXT,
                    summary TEXT,
                    error TEXT,
                    output_artifact_refs_json TEXT NOT NULL,
                    product_refs_json TEXT NOT NULL,
                    lease_owner_id TEXT,
                    lease_expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE(session_id, workflow_instance_id, task_key, attempt)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_graph_task_execution
                ON graph_agent_task_attempts(session_id, workflow_instance_id, task_key, execution_key)
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def _required_attempt(store: SqliteGraphAgentTaskStore, attempt_id: str) -> GraphAgentTaskAttemptRecord:
    record = store.get_attempt(attempt_id)
    if record is None:
        raise ValidationError(f"unknown graph task attempt: {attempt_id}")
    return record


def _required_attempt_row(conn: sqlite3.Connection, attempt_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM graph_agent_task_attempts WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise ValidationError(f"unknown graph task attempt: {attempt_id}")
    return cast(sqlite3.Row, row)


def _record_from_row(row: sqlite3.Row) -> GraphAgentTaskAttemptRecord:
    return GraphAgentTaskAttemptRecord(
        attempt_id=str(row["attempt_id"]),
        session_id=str(row["session_id"]),
        workflow_instance_id=str(row["workflow_instance_id"]),
        execution_key=str(row["execution_key"]),
        task_key=str(row["task_key"]),
        attempt=int(row["attempt"]),
        target_agent_id=str(row["target_agent_id"]),
        instruction=str(row["instruction"]),
        constraints=tuple(_json_list(row["constraints_json"])),
        artifact_refs=tuple(_json_list(row["artifact_refs_json"])),
        skill_names=tuple(_json_list(row["skill_names_json"])),
        max_tool_rounds=int(row["max_tool_rounds"]),
        status=str(row["status"]),
        child_run_id=_optional_string(row["child_run_id"]),
        summary=_optional_string(row["summary"]),
        error=_optional_string(row["error"]),
        output_artifact_refs=tuple(_json_list(row["output_artifact_refs_json"])),
        product_refs=tuple(_json_list(row["product_refs_json"])),
        lease_owner_id=_optional_string(row["lease_owner_id"]),
        lease_expires_at=_optional_datetime(row["lease_expires_at"]),
        created_at=from_app_iso(str(row["created_at"])),
        updated_at=from_app_iso(str(row["updated_at"])),
        completed_at=_optional_datetime(row["completed_at"]),
    )


def _json(values: object) -> str:
    return json.dumps(list(values) if isinstance(values, tuple) else values, ensure_ascii=True)


def _json_list(value: Any) -> list[str]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, list):
        raise ValidationError("graph task JSON list field is invalid.")
    return [str(item) for item in parsed if isinstance(item, str) and item.strip()]


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_datetime(value: Any) -> datetime | None:
    text = _optional_string(value)
    return None if text is None else from_app_iso(text)


def _require_non_empty(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()
