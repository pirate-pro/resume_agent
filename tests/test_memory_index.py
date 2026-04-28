"""Tests for the SQLite derived memory index."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.memory.models import MemoryRecord, MemoryScope, MemoryStatus, MemoryType
from app.memory.stores import jsonl_file_store
from app.memory.stores.jsonl_file_store import JsonlFileMemoryStore

__all__ = []


def test_store_search_uses_fresh_sqlite_index_without_jsonl_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root_dir = tmp_path / "memory_v2"
    store = JsonlFileMemoryStore(root_dir=root_dir)
    store.write_records(
        [
            _build_record(
                memory_id="mem_index_search",
                content="以后回答简洁一点",
                metadata={
                    "kind": "user_preference",
                    "canonical_key": "response_style",
                    "normalized_value": "concise",
                    "source_kind": "explicit_user",
                },
            )
        ]
    )

    def fail_jsonl_read(path: Path) -> list[dict[str, Any]]:
        raise AssertionError(f"unexpected JSONL scan: {path}")

    monkeypatch.setattr(jsonl_file_store, "_read_jsonl_rows", fail_jsonl_read)

    hits = store.search_records(
        scope=MemoryScope.AGENT_LONG,
        agent_id="agent_main",
        session_id=None,
        query="简洁",
        limit=5,
        now=datetime.now(UTC),
    )

    assert len(hits) == 1
    assert hits[0].memory_id == "mem_index_search"


def test_sqlite_index_can_be_deleted_and_rebuilt_from_jsonl(tmp_path: Path) -> None:
    root_dir = tmp_path / "memory_v2"
    store = JsonlFileMemoryStore(root_dir=root_dir)
    store.write_records(
        [
            _build_record(
                memory_id="mem_index_rebuild",
                content="用户称呼是李华",
                metadata={
                    "kind": "user_preference",
                    "canonical_key": "preferred_name",
                    "normalized_value": "李华",
                    "source_kind": "explicit_user",
                },
            )
        ]
    )
    _delete_sqlite_index(root_dir)

    rebuilt_store = JsonlFileMemoryStore(root_dir=root_dir)
    records = rebuilt_store.list_active_records_by_canonical_key(
        scope=MemoryScope.AGENT_LONG,
        agent_id="agent_main",
        session_id=None,
        canonical_key="preferred_name",
        now=datetime.now(UTC),
    )

    assert len(records) == 1
    assert records[0].memory_id == "mem_index_rebuild"


def test_sqlite_index_tracks_archive_status(tmp_path: Path) -> None:
    root_dir = tmp_path / "memory_v2"
    store = JsonlFileMemoryStore(root_dir=root_dir)
    record = _build_record(
        memory_id="mem_index_archive",
        content="用户称呼是李华",
        metadata={
            "kind": "user_preference",
            "canonical_key": "preferred_name",
            "normalized_value": "李华",
            "source_kind": "explicit_user",
        },
    )
    store.write_records([record])
    before_count = store.count_active_records_by_canonical_value(
        scope=MemoryScope.AGENT_LONG,
        agent_id="agent_main",
        session_id=None,
        canonical_key="preferred_name",
        normalized_value="李华",
        now=datetime.now(UTC),
    )

    archived = store.archive_records_by_memory_ids(
        scope=MemoryScope.AGENT_LONG,
        agent_id="agent_main",
        session_id=None,
        memory_ids=["mem_index_archive"],
        now=datetime.now(UTC),
        reason="test_archive",
    )
    after_count = store.count_active_records_by_canonical_value(
        scope=MemoryScope.AGENT_LONG,
        agent_id="agent_main",
        session_id=None,
        canonical_key="preferred_name",
        normalized_value="李华",
        now=datetime.now(UTC),
    )

    assert before_count == 1
    assert archived == 1
    assert after_count == 0


def _build_record(*, memory_id: str, content: str, metadata: dict[str, str]) -> MemoryRecord:
    now = datetime.now(UTC)
    return MemoryRecord(
        memory_id=memory_id,
        scope=MemoryScope.AGENT_LONG,
        owner_agent_id="agent_main",
        session_id=None,
        memory_type=MemoryType.FACT,
        content=content,
        tags=["long_term"],
        importance=0.8,
        confidence=0.9,
        status=MemoryStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        expires_at=None,
        source_event_id="evt_index",
        source_agent_id="agent_main",
        version=1,
        parent_memory_id=None,
        content_hash="",
        metadata={"source": "test", **metadata},
    )


def _delete_sqlite_index(root_dir: Path) -> None:
    db_path = root_dir / "index" / "memory_index.sqlite3"
    for path in [db_path, db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm")]:
        if path.exists():
            path.unlink()
