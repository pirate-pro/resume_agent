"""Tests for the memory file-first store."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.models import RunContext
from app.memory.models import MemoryScope
from app.memory.file_store import FileMemoryStore
from app.runtime.agent_capability import AgentCapabilityRegistry
from app.runtime.memory_manager import MemoryManager


def _context(session_id: str, agent_id: str = "agent_main") -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id="run_1",
        agent_id=agent_id,
        turn_id="turn_1",
        entry_agent_id=agent_id,
    )


def _manager(tmp_path: Path) -> MemoryManager:
    return MemoryManager(
        capability_registry=AgentCapabilityRegistry.for_tests(),
        memory_store=FileMemoryStore(root_dir=tmp_path / "memory"),
    )


def test_memory_manager_writes_and_searches_current_agent_fact(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    written = manager.write_memory(
        content="用户指定以后叫我小猪。",
        tags=["preference", "long_term"],
        context=_context("sess_1"),
        source_event_id="evt_1",
    )

    _, _, bundle = manager.search_bundle(
        query="你的名字叫什么？",
        limit=5,
        context=_context("sess_2"),
    )

    assert written.memory_id.startswith("fact_")
    assert any("小猪" in item.content for item in bundle.items)

    fact_file = tmp_path / "memory" / "agents" / "agent_main" / "facts.jsonl"
    rows = [json.loads(line) for line in fact_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[0]["source"]["sessionId"] == "sess_1"
    assert rows[0]["source"]["eventIds"] == ["evt_1"]
    assert rows[0]["injectPolicy"] == "always"


def test_memory_keeps_agent_private_facts_isolated(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    manager.write_memory(
        content="agent_main 私有偏好：回答要先给结论。",
        tags=["preference", "long_term"],
        context=_context("sess_1", agent_id="agent_main"),
        source_event_id=None,
    )

    main_hits = manager.search(
        query="结论",
        limit=5,
        context=_context("sess_2", agent_id="agent_main"),
    )
    other_hits = manager.search(
        query="结论",
        limit=5,
        context=_context("sess_3", agent_id="agent_other"),
    )

    assert any("先给结论" in item.content for item in main_hits)
    assert other_hits == []


def test_memory_generic_preference_defaults_to_retrieval_injection(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    manager.write_memory(
        content="用户偏好：回答要先给结论。",
        tags=["preference", "long_term"],
        context=_context("sess_1"),
        source_event_id="evt_pref",
    )

    fact_file = tmp_path / "memory" / "agents" / "agent_main" / "facts.jsonl"
    rows = [json.loads(line) for line in fact_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[0]["injectPolicy"] == "retrieval"


def test_memory_shared_facts_are_visible_to_other_agents(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    manager.write_memory(
        content="共享规则：回答必须避免编造工具结果。",
        tags=["shared", "constraint"],
        context=_context("sess_1", agent_id="agent_main"),
        source_event_id=None,
    )

    other_hits = manager.search(
        query="工具结果",
        limit=5,
        context=_context("sess_2", agent_id="agent_other"),
    )

    assert any("避免编造工具结果" in item.content for item in other_hits)


def test_memory_forget_archives_current_agent_fact(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    written = manager.write_memory(
        content="用户喜欢番茄钟工作法。",
        tags=["preference", "long_term"],
        context=_context("sess_1"),
        source_event_id=None,
    )

    result = manager.forget_memory_ids(
        context=_context("sess_2"),
        memory_ids=[written.memory_id],
        scopes=[MemoryScope.AGENT_LONG],
        hard_delete=False,
        reason="test",
    )
    hits = manager.search(query="番茄钟", limit=5, context=_context("sess_3"))

    assert result.touched_records == 1
    assert result.archived_records == 1
    assert hits == []


def test_memory_context_standing_only_injects_identity_not_generic_preferences(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.write_memory(
        content="普通上下文：用户偶尔提到绿色茶杯。",
        tags=[],
        context=_context("sess_1"),
        source_event_id=None,
    )
    manager.write_memory(
        content="用户偏好：回答先给结论。",
        tags=["preference", "long_term"],
        context=_context("sess_1"),
        source_event_id=None,
    )
    manager.write_memory(
        content="用户希望我叫小明。",
        tags=["preference", "long_term"],
        context=_context("sess_1"),
        source_event_id=None,
    )

    lanes, _ = manager.search_context_memory_lanes(
        query="完全不相关的问题",
        limit=5,
        context=_context("sess_2"),
    )
    contents = [item.content for items in lanes.values() for item in items]

    assert any("小明" in content for content in contents)
    assert all("先给结论" not in content for content in contents)
    assert all("绿色茶杯" not in content for content in contents)
