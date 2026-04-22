"""Tests for memory compact operations."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.memory.models import MemoryCompactRequest, MemoryRecord, MemoryScope, MemoryStatus, MemoryType
from app.memory.stores.jsonl_file_store import JsonlFileMemoryStore

__all__ = []


def test_compact_prunes_deleted_and_expired_and_writes_index(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")

    active = _build_record(
        memory_id="mem_active",
        scope=MemoryScope.AGENT_SHORT,
        owner_agent_id="agent_main",
        session_id="sess_1",
        content="active memory",
        status=MemoryStatus.ACTIVE,
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=6),
    )
    deleted = _build_record(
        memory_id="mem_deleted",
        scope=MemoryScope.AGENT_SHORT,
        owner_agent_id="agent_main",
        session_id="sess_1",
        content="deleted memory",
        status=MemoryStatus.DELETED,
        created_at=now - timedelta(hours=3),
        updated_at=now - timedelta(hours=2),
        expires_at=None,
    )
    expired = _build_record(
        memory_id="mem_expired",
        scope=MemoryScope.AGENT_SHORT,
        owner_agent_id="agent_main",
        session_id="sess_1",
        content="expired memory",
        status=MemoryStatus.ACTIVE,
        created_at=now - timedelta(hours=4),
        updated_at=now - timedelta(hours=3),
        expires_at=now - timedelta(minutes=1),
    )

    store.write_records([active, deleted, expired])

    result = store.compact(
        MemoryCompactRequest(
            scopes=[MemoryScope.AGENT_SHORT],
            agent_id="agent_main",
            session_id="sess_1",
        ),
        now=now,
    )

    assert result.scanned_files == 1
    assert result.rewritten_files == 1
    assert result.scanned_rows == 3
    assert result.kept_rows == 1
    assert result.dropped_deleted == 1
    assert result.dropped_expired == 1
    assert result.index_files_written == 1

    record_file = tmp_path / "memory_v2" / "agents" / "agent_main" / "short" / "sess_1.jsonl"
    rows = _read_jsonl(record_file)
    assert len(rows) == 1
    assert rows[0]["memory_id"] == "mem_active"

    index_file = tmp_path / "memory_v2" / "agents" / "agent_main" / "short" / "sess_1.index.json"
    index_payload = json.loads(index_file.read_text(encoding="utf-8"))
    assert index_payload["record_count"] == 1
    assert index_payload["active_count"] == 1

    compact_log_file = tmp_path / "memory_v2" / "ops" / "compact.log.jsonl"
    log_rows = _read_jsonl(compact_log_file)
    assert len(log_rows) == 1
    assert log_rows[0]["operation"] == "compact"


def test_compact_dedupe_by_memory_id_keeps_latest(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")

    old = _build_record(
        memory_id="mem_same",
        scope=MemoryScope.AGENT_LONG,
        owner_agent_id="agent_main",
        session_id=None,
        content="old content",
        status=MemoryStatus.ACTIVE,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=1),
        expires_at=None,
        version=1,
    )
    new = _build_record(
        memory_id="mem_same",
        scope=MemoryScope.AGENT_LONG,
        owner_agent_id="agent_main",
        session_id=None,
        content="new content",
        status=MemoryStatus.ACTIVE,
        created_at=now - timedelta(hours=20),
        updated_at=now - timedelta(hours=1),
        expires_at=None,
        version=2,
    )

    store.write_records([old, new])
    result = store.compact(
        MemoryCompactRequest(scopes=[MemoryScope.AGENT_LONG], agent_id="agent_main"),
        now=now,
    )

    assert result.dropped_superseded == 1
    assert result.kept_rows == 1

    record_file = tmp_path / "memory_v2" / "agents" / "agent_main" / "long.jsonl"
    rows = _read_jsonl(record_file)
    assert len(rows) == 1
    assert rows[0]["memory_id"] == "mem_same"
    assert rows[0]["content"] == "new content"


def test_compact_dedupe_by_content_hash_is_optional(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")

    a = _build_record(
        memory_id="mem_a",
        scope=MemoryScope.AGENT_LONG,
        owner_agent_id="agent_main",
        session_id=None,
        content="same content",
        status=MemoryStatus.ACTIVE,
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(hours=3),
        expires_at=None,
    )
    b = _build_record(
        memory_id="mem_b",
        scope=MemoryScope.AGENT_LONG,
        owner_agent_id="agent_main",
        session_id=None,
        content="same content",
        status=MemoryStatus.ACTIVE,
        created_at=now - timedelta(hours=4),
        updated_at=now - timedelta(hours=2),
        expires_at=None,
    )

    store.write_records([a, b])

    result_without_hash_dedupe = store.compact(
        MemoryCompactRequest(
            scopes=[MemoryScope.AGENT_LONG],
            agent_id="agent_main",
            dedupe_by_content_hash=False,
        ),
        now=now,
    )
    assert result_without_hash_dedupe.dropped_duplicate_hash == 0
    assert result_without_hash_dedupe.kept_rows == 2

    result_with_hash_dedupe = store.compact(
        MemoryCompactRequest(
            scopes=[MemoryScope.AGENT_LONG],
            agent_id="agent_main",
            dedupe_by_content_hash=True,
        ),
        now=now,
    )
    assert result_with_hash_dedupe.dropped_duplicate_hash == 1
    assert result_with_hash_dedupe.kept_rows == 1


def _build_record(
    *,
    memory_id: str,
    scope: MemoryScope,
    owner_agent_id: str | None,
    session_id: str | None,
    content: str,
    status: MemoryStatus,
    created_at: datetime,
    updated_at: datetime,
    expires_at: datetime | None,
    version: int = 1,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        scope=scope,
        owner_agent_id=owner_agent_id,
        session_id=session_id,
        memory_type=MemoryType.FACT,
        content=content,
        tags=["t1"],
        importance=0.8,
        confidence=0.9,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        expires_at=expires_at,
        source_event_id="evt_test",
        source_agent_id="agent_main",
        version=version,
        parent_memory_id=None,
        content_hash="",
        metadata={"source": "test"},
    )


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
    return rows
