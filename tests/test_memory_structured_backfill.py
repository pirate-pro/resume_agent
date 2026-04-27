"""Tests for offline structured metadata backfill."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.memory.facade import FileMemoryFacade
from app.memory.models import (
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryStructuredBackfillRequest,
    MemoryType,
)
from app.memory.policies import default_memory_policy
from app.memory.stores.jsonl_file_store import JsonlFileMemoryStore

__all__ = []


def test_structured_backfill_patches_legacy_records_and_writes_log(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=store, policy=default_memory_policy())

    store.write_records(
        [
            _build_record(
                memory_id="mem_legacy_name",
                scope=MemoryScope.AGENT_LONG,
                owner_agent_id="agent_main",
                session_id=None,
                content="以后叫我李华",
                status=MemoryStatus.ACTIVE,
                created_at=now - timedelta(days=2),
                updated_at=now - timedelta(days=1),
                tags=["preference", "long_term"],
                metadata={},
            ),
            _build_record(
                memory_id="mem_stale_policy",
                scope=MemoryScope.AGENT_LONG,
                owner_agent_id="agent_main",
                session_id=None,
                content="用户称呼是老王",
                status=MemoryStatus.ACTIVE,
                created_at=now - timedelta(days=2),
                updated_at=now - timedelta(days=1),
                tags=["preference", "long_term", "system_policy"],
                metadata={"source": "memory_write_tool", "source_kind": "memory_write_tool"},
            ),
            _build_record(
                memory_id="mem_archived_goal",
                scope=MemoryScope.AGENT_LONG,
                owner_agent_id="agent_main",
                session_id=None,
                content="长期目标是转向 AI 工程",
                status=MemoryStatus.ARCHIVED,
                created_at=now - timedelta(days=3),
                updated_at=now - timedelta(days=2),
                tags=["long_term"],
                metadata={"archive_reason": "manual"},
            ),
            _build_record(
                memory_id="mem_deleted",
                scope=MemoryScope.AGENT_LONG,
                owner_agent_id="agent_main",
                session_id=None,
                content="以后叫我小张",
                status=MemoryStatus.DELETED,
                created_at=now - timedelta(days=4),
                updated_at=now - timedelta(days=3),
                tags=["preference", "long_term"],
                metadata={},
            ),
            _build_record(
                memory_id="mem_structured",
                scope=MemoryScope.AGENT_LONG,
                owner_agent_id="agent_main",
                session_id=None,
                content="以后叫我小陈",
                status=MemoryStatus.ACTIVE,
                created_at=now - timedelta(days=5),
                updated_at=now - timedelta(days=1),
                tags=["preference", "long_term"],
                metadata={
                    "kind": "user_preference",
                    "source_kind": "explicit_user",
                    "subject_kind": "user",
                    "classification_version": "v1",
                    "canonical_key": "preferred_name",
                    "normalized_value": "小陈",
                },
            ),
        ]
    )

    result = facade.backfill_structured_metadata(
        MemoryStructuredBackfillRequest(
            scopes=[MemoryScope.AGENT_LONG],
            agent_id="agent_main",
        )
    )

    assert result.scanned_files == 1
    assert result.rewritten_files == 1
    assert result.scanned_rows == 5
    assert result.patched_records == 3
    assert result.skipped_structured == 1
    assert result.skipped_deleted == 1

    rows = _read_jsonl(tmp_path / "memory_v2" / "agents" / "agent_main" / "long.jsonl")
    by_id = {row["memory_id"]: row for row in rows}
    assert by_id["mem_legacy_name"]["metadata"]["canonical_key"] == "preferred_name"
    assert by_id["mem_legacy_name"]["metadata"]["normalized_value"] == "李华"
    assert by_id["mem_legacy_name"]["metadata"]["metadata_refresh_reason"] == "bulk_structured_backfill"
    assert by_id["mem_stale_policy"]["metadata"]["source_kind"] == "system_policy"
    assert by_id["mem_archived_goal"]["metadata"]["canonical_key"] == "long_term_goal"
    assert by_id["mem_deleted"]["metadata"] == {}
    assert by_id["mem_structured"]["metadata"]["normalized_value"] == "小陈"
    assert "metadata_refresh_reason" not in by_id["mem_structured"]["metadata"]

    log_rows = _read_jsonl(tmp_path / "memory_v2" / "ops" / "structured_backfill.log.jsonl")
    assert len(log_rows) == 1
    assert log_rows[0]["operation"] == "structured_backfill"
    assert log_rows[0]["result"]["patched_records"] == 3


def test_structured_backfill_can_target_single_short_session(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=store, policy=default_memory_policy())

    store.write_records(
        [
            _build_record(
                memory_id="mem_short_a",
                scope=MemoryScope.AGENT_SHORT,
                owner_agent_id="agent_main",
                session_id="sess_a",
                content="以后叫我阿华",
                status=MemoryStatus.ACTIVE,
                created_at=now - timedelta(hours=4),
                updated_at=now - timedelta(hours=3),
                tags=["preference"],
                metadata={},
            ),
            _build_record(
                memory_id="mem_short_b",
                scope=MemoryScope.AGENT_SHORT,
                owner_agent_id="agent_main",
                session_id="sess_b",
                content="以后叫我阿杰",
                status=MemoryStatus.ACTIVE,
                created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=1),
                tags=["preference"],
                metadata={},
            ),
        ]
    )

    result = facade.backfill_structured_metadata(
        MemoryStructuredBackfillRequest(
            scopes=[MemoryScope.AGENT_SHORT],
            agent_id="agent_main",
            session_id="sess_a",
        )
    )

    assert result.scanned_files == 1
    assert result.patched_records == 1

    rows_a = _read_jsonl(tmp_path / "memory_v2" / "agents" / "agent_main" / "short" / "sess_a.jsonl")
    rows_b = _read_jsonl(tmp_path / "memory_v2" / "agents" / "agent_main" / "short" / "sess_b.jsonl")
    assert rows_a[0]["metadata"]["canonical_key"] == "preferred_name"
    assert rows_b[0]["metadata"] == {}


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
    tags: list[str],
    metadata: dict[str, str],
) -> MemoryRecord:
    memory_type = MemoryType.PREFERENCE if "preference" in tags else MemoryType.FACT
    return MemoryRecord(
        memory_id=memory_id,
        scope=scope,
        owner_agent_id=owner_agent_id,
        session_id=session_id,
        memory_type=memory_type,
        content=content,
        tags=tags,
        importance=0.8,
        confidence=0.7,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        expires_at=None,
        source_event_id="evt_test",
        source_agent_id="agent_main",
        version=1,
        parent_memory_id=None,
        content_hash="",
        metadata=metadata,
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
