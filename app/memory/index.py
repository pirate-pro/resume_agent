"""Derived indexes for current-schema memory records."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from app.core.errors import StorageError, ValidationError
from app.memory.models import MemoryRecord, MemoryScope, MemoryStatus
from app.memory.policies import memory_lane_for_metadata
from app.memory.serialization import memory_payload_to_record, memory_record_to_payload

__all__ = ["MemoryIndex", "SqliteMemoryIndex"]

_INDEX_SCHEMA_VERSION = "memory_index_v1"


class MemoryIndex(Protocol):
    """Rebuildable read index derived from JSONL memory records."""

    def source_is_fresh(self, source_file: str, fingerprint: str) -> bool: ...

    def replace_source_records(self, source_file: str, fingerprint: str, records: list[MemoryRecord]) -> None: ...

    def list_active_records(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        now: datetime,
    ) -> list[MemoryRecord]: ...

    def count_active_records_by_hash(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        content_hash: str,
        now: datetime,
    ) -> int: ...

    def count_active_records_by_canonical_value(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        canonical_key: str,
        normalized_value: str,
        now: datetime,
    ) -> int: ...

    def list_active_records_by_canonical_key(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        canonical_key: str,
        now: datetime,
    ) -> list[MemoryRecord]: ...


class SqliteMemoryIndex:
    """SQLite-backed derived index.

    JSONL remains the source of truth. The SQLite file only caches current-schema
    records by source file and can be deleted/rebuilt at any time.
    """

    def __init__(self, db_path: Path) -> None:
        if not isinstance(db_path, Path):
            raise ValidationError("db_path must be pathlib.Path.")
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def source_is_fresh(self, source_file: str, fingerprint: str) -> bool:
        normalized_source = _require_non_empty("source_file", source_file)
        normalized_fingerprint = _require_non_empty("fingerprint", fingerprint)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT fingerprint FROM indexed_sources WHERE source_file = ?",
                    (normalized_source,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to read memory index source state: {exc}") from exc
        if row is None:
            return False
        return str(row["fingerprint"]) == normalized_fingerprint

    def replace_source_records(self, source_file: str, fingerprint: str, records: list[MemoryRecord]) -> None:
        normalized_source = _require_non_empty("source_file", source_file)
        normalized_fingerprint = _require_non_empty("fingerprint", fingerprint)
        if not isinstance(records, list):
            raise ValidationError("records must be a list.")
        now_text = _to_iso(datetime.now(UTC))
        try:
            with self._connect() as connection:
                connection.execute("DELETE FROM memory_records WHERE source_file = ?", (normalized_source,))
                connection.execute(
                    """
                    INSERT OR REPLACE INTO indexed_sources (source_file, fingerprint, refreshed_at)
                    VALUES (?, ?, ?)
                    """,
                    (normalized_source, normalized_fingerprint, now_text),
                )
                for record in records:
                    if not isinstance(record, MemoryRecord):
                        raise ValidationError("records item must be MemoryRecord.")
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO memory_records (
                            memory_id,
                            source_file,
                            scope,
                            owner_agent_id,
                            session_id,
                            status,
                            memory_type,
                            content,
                            tags_json,
                            content_hash,
                            canonical_key,
                            normalized_value,
                            kind,
                            source_kind,
                            lane,
                            confidence,
                            importance,
                            created_at,
                            updated_at,
                            expires_at,
                            version,
                            payload_json
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        _record_to_index_row(record=record, source_file=normalized_source),
                    )
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to replace memory index source records: {exc}") from exc

    def list_active_records(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        now: datetime,
    ) -> list[MemoryRecord]:
        where, params = _active_filter(
            scope=scope,
            agent_id=agent_id,
            session_id=session_id,
            now=now,
        )
        return self._select_records(
            where=where,
            params=params,
            order_by="updated_at DESC, version DESC, created_at DESC, memory_id DESC",
        )

    def count_active_records_by_hash(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        content_hash: str,
        now: datetime,
    ) -> int:
        normalized_hash = _require_non_empty("content_hash", content_hash)
        where, params = _active_filter(
            scope=scope,
            agent_id=agent_id,
            session_id=session_id,
            now=now,
        )
        return self._select_count(where=f"{where} AND content_hash = ?", params=[*params, normalized_hash])

    def count_active_records_by_canonical_value(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        canonical_key: str,
        normalized_value: str,
        now: datetime,
    ) -> int:
        normalized_key = _require_non_empty("canonical_key", canonical_key)
        normalized_value_text = _require_non_empty("normalized_value", normalized_value)
        where, params = _active_filter(
            scope=scope,
            agent_id=agent_id,
            session_id=session_id,
            now=now,
        )
        return self._select_count(
            where=f"{where} AND canonical_key = ? AND normalized_value = ?",
            params=[*params, normalized_key, normalized_value_text],
        )

    def list_active_records_by_canonical_key(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        canonical_key: str,
        now: datetime,
    ) -> list[MemoryRecord]:
        normalized_key = _require_non_empty("canonical_key", canonical_key)
        where, params = _active_filter(
            scope=scope,
            agent_id=agent_id,
            session_id=session_id,
            now=now,
        )
        return self._select_records(
            where=f"{where} AND canonical_key = ?",
            params=[*params, normalized_key],
            order_by="updated_at DESC, version DESC, created_at DESC, memory_id DESC",
        )

    def _ensure_schema(self) -> None:
        try:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS indexed_sources (
                        source_file TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL,
                        refreshed_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS memory_records (
                        memory_id TEXT PRIMARY KEY,
                        source_file TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        owner_agent_id TEXT,
                        session_id TEXT,
                        status TEXT NOT NULL,
                        memory_type TEXT NOT NULL,
                        content TEXT NOT NULL,
                        tags_json TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        canonical_key TEXT,
                        normalized_value TEXT,
                        kind TEXT,
                        source_kind TEXT,
                        lane TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        importance REAL NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        expires_at TEXT,
                        version INTEGER NOT NULL,
                        payload_json TEXT NOT NULL,
                        FOREIGN KEY(source_file) REFERENCES indexed_sources(source_file)
                    );

                    CREATE INDEX IF NOT EXISTS idx_memory_records_scope_owner_session_status
                        ON memory_records(scope, owner_agent_id, session_id, status);
                    CREATE INDEX IF NOT EXISTS idx_memory_records_canonical
                        ON memory_records(scope, owner_agent_id, session_id, canonical_key, normalized_value, status);
                    CREATE INDEX IF NOT EXISTS idx_memory_records_hash
                        ON memory_records(scope, owner_agent_id, session_id, content_hash, status);
                    CREATE INDEX IF NOT EXISTS idx_memory_records_lane
                        ON memory_records(scope, owner_agent_id, session_id, lane, status, updated_at);
                    CREATE INDEX IF NOT EXISTS idx_memory_records_status_updated
                        ON memory_records(status, updated_at);
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS index_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "INSERT OR REPLACE INTO index_meta (key, value) VALUES ('schema', ?)",
                    (_INDEX_SCHEMA_VERSION,),
                )
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to initialize memory SQLite index: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self._db_path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            return connection
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to open memory SQLite index: {exc}") from exc

    def _select_count(self, *, where: str, params: list[str]) -> int:
        try:
            with self._connect() as connection:
                row = connection.execute(f"SELECT COUNT(*) AS count FROM memory_records WHERE {where}", params).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to count memory index records: {exc}") from exc
        if row is None:
            return 0
        return int(row["count"])

    def _select_records(self, *, where: str, params: list[str], order_by: str) -> list[MemoryRecord]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"SELECT payload_json FROM memory_records WHERE {where} ORDER BY {order_by}",
                    params,
                ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to read memory index records: {exc}") from exc
        return [_record_from_payload_json(str(row["payload_json"])) for row in rows]


def _record_to_index_row(record: MemoryRecord, source_file: str) -> tuple[
    str,
    str,
    str,
    str | None,
    str | None,
    str,
    str,
    str,
    str,
    str,
    str | None,
    str | None,
    str | None,
    str | None,
    str,
    float,
    float,
    str,
    str,
    str | None,
    int,
    str,
]:
    payload = memory_record_to_payload(record)
    metadata = record.metadata
    canonical_key = metadata.get("canonical_key")
    normalized_value = metadata.get("normalized_value")
    kind = metadata.get("kind")
    source_kind = metadata.get("source_kind")
    lane = memory_lane_for_metadata(canonical_key, kind)
    return (
        record.memory_id,
        source_file,
        record.scope.value,
        record.owner_agent_id,
        record.session_id,
        record.status.value,
        record.memory_type.value,
        record.content,
        json.dumps(record.tags, ensure_ascii=False),
        record.content_hash,
        canonical_key,
        normalized_value,
        kind,
        source_kind,
        lane,
        record.confidence,
        record.importance,
        _to_iso(record.created_at),
        _to_iso(record.updated_at),
        None if record.expires_at is None else _to_iso(record.expires_at),
        record.version,
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )


def _active_filter(
    *,
    scope: MemoryScope,
    agent_id: str | None,
    session_id: str | None,
    now: datetime,
) -> tuple[str, list[str]]:
    where = ["scope = ?", "status = ?", "(expires_at IS NULL OR expires_at > ?)"]
    params = [scope.value, MemoryStatus.ACTIVE.value, _to_iso(now)]
    if scope != MemoryScope.SHARED_LONG and agent_id is not None:
        where.append("owner_agent_id = ?")
        params.append(agent_id)
    if scope == MemoryScope.AGENT_SHORT and session_id is not None:
        where.append("session_id = ?")
        params.append(session_id)
    return " AND ".join(where), params


def _record_from_payload_json(value: str) -> MemoryRecord:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise StorageError(f"Invalid memory index payload JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise StorageError("Invalid memory index payload: expected object.")
    return memory_payload_to_record(payload)


def _require_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
