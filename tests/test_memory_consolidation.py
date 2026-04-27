"""Tests for consolidation strategy in memory v2."""

from __future__ import annotations

import json
from pathlib import Path

from app.memory.facade import FileMemoryFacade
from app.memory.intake import build_candidate_request
from app.memory.models import MemoryConsolidateRequest, MemoryReadRequest, MemoryScope
from app.memory.policies import MemoryPolicy
from app.memory.stores.jsonl_file_store import JsonlFileMemoryStore

__all__ = []


def _build_facade(tmp_path: Path) -> FileMemoryFacade:
    policy = MemoryPolicy(
        short_ttl_seconds=24 * 60 * 60,
        shared_promotion_min_confidence=0.85,
        shared_promotion_min_repeat=2,
    )
    store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    return FileMemoryFacade(store=store, policy=policy)


def test_shared_promotion_requires_repeat_threshold(tmp_path: Path) -> None:
    facade = _build_facade(tmp_path)

    first = build_candidate_request(
        agent_id="agent_main",
        session_id="sess_1",
        content="发布策略需要固定 checklist",
        tags=["shared", "verified"],
        source_event_id="evt_1",
        source="test",
    )
    facade.write_candidate(first)
    first_result = facade.consolidate(MemoryConsolidateRequest(max_candidates=20))

    assert first_result.promoted_shared == 0

    shared_after_first = facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_1",
            query="checklist",
            include_scopes=[MemoryScope.SHARED_LONG],
            limit=10,
            token_budget=2000,
        )
    )
    assert len(shared_after_first.items) == 0

    second = build_candidate_request(
        agent_id="agent_main",
        session_id="sess_2",
        content="发布策略需要固定 checklist",
        tags=["shared", "verified"],
        source_event_id="evt_2",
        source="test",
    )
    facade.write_candidate(second)
    second_result = facade.consolidate(MemoryConsolidateRequest(max_candidates=20))

    assert second_result.promoted_shared == 1

    shared_after_second = facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_2",
            query="checklist",
            include_scopes=[MemoryScope.SHARED_LONG],
            limit=10,
            token_budget=2000,
        )
    )
    assert len(shared_after_second.items) == 1


def test_consolidation_skips_duplicates_against_existing_records(tmp_path: Path) -> None:
    facade = _build_facade(tmp_path)

    req = build_candidate_request(
        agent_id="agent_main",
        session_id="sess_dup",
        content="用户偏好响应使用短句",
        tags=["preference", "verified"],
        source_event_id="evt_dup_1",
        source="test",
    )
    facade.write_candidate(req)
    first_result = facade.consolidate(MemoryConsolidateRequest(max_candidates=20))
    assert first_result.written_records == 1

    req_again = build_candidate_request(
        agent_id="agent_main",
        session_id="sess_dup",
        content="用户偏好响应使用短句",
        tags=["preference", "verified"],
        source_event_id="evt_dup_2",
        source="test",
    )
    facade.write_candidate(req_again)
    second_result = facade.consolidate(MemoryConsolidateRequest(max_candidates=20))

    assert second_result.written_records == 0
    assert second_result.merged_records >= 1

    agent_long = facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_dup",
            query="短句",
            include_scopes=[MemoryScope.AGENT_LONG],
            limit=10,
            token_budget=2000,
        )
    )
    assert len(agent_long.items) == 1


def test_short_memory_promotes_to_agent_long_after_repeat(tmp_path: Path) -> None:
    facade = _build_facade(tmp_path)

    first = build_candidate_request(
        agent_id="agent_main",
        session_id="sess_repeat",
        content="临时结论：接口字段名统一 snake_case",
        tags=[],
        source_event_id="evt_s1",
        source="test",
    )
    facade.write_candidate(first)
    facade.consolidate(MemoryConsolidateRequest(max_candidates=20))

    short_after_first = facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_repeat",
            query="snake_case",
            include_scopes=[MemoryScope.AGENT_SHORT],
            limit=10,
            token_budget=2000,
        )
    )
    assert len(short_after_first.items) == 1

    second = build_candidate_request(
        agent_id="agent_main",
        session_id="sess_repeat",
        content="临时结论：接口字段名统一 snake_case",
        tags=[],
        source_event_id="evt_s2",
        source="test",
    )
    facade.write_candidate(second)
    facade.consolidate(MemoryConsolidateRequest(max_candidates=20))

    long_after_second = facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_other",
            query="snake_case",
            include_scopes=[MemoryScope.AGENT_LONG],
            limit=10,
            token_budget=2000,
        )
    )
    assert len(long_after_second.items) == 1


def test_shared_promotion_bypasses_repeat_for_explicit_rule_source(tmp_path: Path) -> None:
    facade = _build_facade(tmp_path)

    explicit_shared = build_candidate_request(
        agent_id="agent_main",
        session_id="sess_rule",
        content="系统策略：生产环境禁止自动删除数据",
        tags=["shared", "system_policy", "verified"],
        source_event_id="evt_rule_1",
        source="system_policy",
    )
    facade.write_candidate(explicit_shared)
    result = facade.consolidate(MemoryConsolidateRequest(max_candidates=20))

    assert result.promoted_shared == 1
    shared_hits = facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_any",
            query="禁止自动删除",
            include_scopes=[MemoryScope.SHARED_LONG],
            limit=10,
            token_budget=2000,
        )
    )
    assert len(shared_hits.items) == 1


def test_consolidation_dedupes_semantic_duplicates_by_canonical_key(tmp_path: Path) -> None:
    facade = _build_facade(tmp_path)

    first = build_candidate_request(
        agent_id="agent_main",
        session_id="sess_name",
        content="以后叫我李华",
        tags=["preference", "long_term"],
        source_event_id="evt_name_1",
        source="test",
    )
    facade.write_candidate(first)
    first_result = facade.consolidate(MemoryConsolidateRequest(max_candidates=20))
    assert first_result.written_records == 1

    second = build_candidate_request(
        agent_id="agent_main",
        session_id="sess_name_other",
        content="请叫我李华",
        tags=["preference", "long_term"],
        source_event_id="evt_name_2",
        source="test",
    )
    facade.write_candidate(second)
    second_result = facade.consolidate(MemoryConsolidateRequest(max_candidates=20))

    assert second_result.written_records == 0
    assert second_result.merged_records >= 1

    agent_long = facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_name",
            query="李华",
            include_scopes=[MemoryScope.AGENT_LONG],
            limit=10,
            token_budget=2000,
        )
    )
    assert len(agent_long.items) == 1
    assert agent_long.items[0].metadata["canonical_key"] == "preferred_name"
    assert agent_long.items[0].metadata["normalized_value"] == "李华"


def test_consolidation_supersedes_old_canonical_value_with_new_value(tmp_path: Path) -> None:
    facade = _build_facade(tmp_path)

    first = build_candidate_request(
        agent_id="agent_main",
        session_id="sess_name",
        content="以后叫我李华",
        tags=["preference", "long_term"],
        source_event_id="evt_name_old",
        source="test",
    )
    facade.write_candidate(first)
    facade.consolidate(MemoryConsolidateRequest(max_candidates=20))

    second = build_candidate_request(
        agent_id="agent_main",
        session_id="sess_name",
        content="以后叫我小李",
        tags=["preference", "long_term"],
        source_event_id="evt_name_new",
        source="test",
    )
    facade.write_candidate(second)
    result = facade.consolidate(MemoryConsolidateRequest(max_candidates=20))

    assert result.written_records == 1
    old_hits = facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_name",
            query="李华",
            include_scopes=[MemoryScope.AGENT_LONG],
            limit=10,
            token_budget=2000,
        )
    )
    new_hits = facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_name",
            query="小李",
            include_scopes=[MemoryScope.AGENT_LONG],
            limit=10,
            token_budget=2000,
        )
    )

    assert len(new_hits.items) == 1
    assert new_hits.items[0].metadata["normalized_value"] == "小李"
    assert new_hits.items[0].version >= 2
    assert new_hits.items[0].parent_memory_id is not None
    record_file = tmp_path / "memory_v2" / "agents" / "agent_main" / "long.jsonl"
    rows = _read_jsonl(record_file)
    active_rows = [row for row in rows if row["status"] == "active"]
    archived_rows = [row for row in rows if row["status"] == "archived"]
    assert len(active_rows) == 1
    assert active_rows[0]["metadata"]["normalized_value"] == "小李"
    assert len(archived_rows) == 1
    assert archived_rows[0]["metadata"]["normalized_value"] == "李华"
    assert archived_rows[0]["metadata"]["superseded_by_normalized_value"] == "小李"


def test_consolidation_does_not_let_low_priority_source_override_explicit_user(tmp_path: Path) -> None:
    facade = _build_facade(tmp_path)

    first = build_candidate_request(
        agent_id="agent_main",
        session_id="sess_name",
        content="以后叫我李华",
        tags=["preference", "long_term"],
        source_event_id="evt_name_user",
        source="test",
    )
    facade.write_candidate(first)
    facade.consolidate(MemoryConsolidateRequest(max_candidates=20))

    second = build_candidate_request(
        agent_id="agent_main",
        session_id="sess_name",
        content="以后叫我小李",
        tags=["preference", "long_term", "assistant_inferred"],
        source_event_id="evt_name_inferred",
        source="test",
    )
    facade.write_candidate(second)
    result = facade.consolidate(MemoryConsolidateRequest(max_candidates=20))

    assert result.written_records == 0
    assert result.conflicts == 1
    hits = facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_name",
            query="李华",
            include_scopes=[MemoryScope.AGENT_LONG],
            limit=10,
            token_budget=2000,
        )
    )
    assert len(hits.items) == 1
    assert hits.items[0].metadata["normalized_value"] == "李华"


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
