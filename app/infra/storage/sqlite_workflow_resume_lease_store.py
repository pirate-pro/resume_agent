"""SQLite-backed workflow resume lease store."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import timedelta
from pathlib import Path
from types import TracebackType

from app.core.errors import ValidationError
from app.core.time import app_now, to_app_iso
from app.domain.workflow_resume_locks import WorkflowResumeLease

__all__ = ["SqliteWorkflowResumeLeaseStore"]


class SqliteWorkflowResumeLeaseStore:
    """Provide cross-process best-effort leases for workflow resume calls."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise ValidationError("workflow resume lease path must be a pathlib.Path.")
        self._path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "SqliteWorkflowResumeLeaseStore":
        await self._setup()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        _ = (exc_type, exc_value, traceback)
        conn = self._conn
        self._conn = None
        if conn is not None:
            await asyncio.to_thread(conn.close)
        return None

    async def acquire(
        self,
        *,
        workflow_instance_id: str,
        owner_id: str,
        ttl_seconds: float,
    ) -> WorkflowResumeLease:
        workflow_instance_id = _require_non_empty("workflow_instance_id", workflow_instance_id)
        owner_id = _require_non_empty("owner_id", owner_id)
        if ttl_seconds <= 0:
            raise ValidationError("workflow resume lease ttl_seconds must be positive.")
        await self._setup()
        now = app_now()
        expires_at = now + timedelta(seconds=ttl_seconds)
        now_iso = to_app_iso(now)
        expires_iso = to_app_iso(expires_at)
        async with self._lock:
            conn = self._require_conn()

            def _acquire_sync() -> None:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "DELETE FROM workflow_resume_leases WHERE workflow_instance_id = ? AND expires_at <= ?",
                        (workflow_instance_id, now_iso),
                    )
                    conn.execute(
                        """
                        INSERT INTO workflow_resume_leases
                            (workflow_instance_id, owner_id, acquired_at, expires_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (workflow_instance_id, owner_id, now_iso, expires_iso),
                    )
                    conn.commit()
                except sqlite3.IntegrityError as exc:
                    conn.rollback()
                    raise ValidationError(
                        f"workflow_instance_id is already being resumed: {workflow_instance_id}."
                    ) from exc
                except Exception:
                    conn.rollback()
                    raise

            await asyncio.to_thread(_acquire_sync)
        return WorkflowResumeLease(
            workflow_instance_id=workflow_instance_id,
            owner_id=owner_id,
            expires_at=expires_at,
        )

    async def release(self, lease: WorkflowResumeLease) -> None:
        if not isinstance(lease, WorkflowResumeLease):
            raise ValidationError("lease must be WorkflowResumeLease.")
        await self._setup()
        async with self._lock:
            conn = self._require_conn()

            def _release_sync() -> None:
                conn.execute(
                    "DELETE FROM workflow_resume_leases WHERE workflow_instance_id = ? AND owner_id = ?",
                    (lease.workflow_instance_id, lease.owner_id),
                )
                conn.commit()

            await asyncio.to_thread(_release_sync)

    async def _setup(self) -> None:
        if self._conn is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)

        def _connect() -> sqlite3.Connection:
            conn = sqlite3.connect(self._path, timeout=5.0, isolation_level=None, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_resume_leases (
                    workflow_instance_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
            return conn

        async with self._lock:
            if self._conn is None:
                self._conn = await asyncio.to_thread(_connect)

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise ValidationError("workflow resume lease store is not initialized.")
        return self._conn


def _require_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()
