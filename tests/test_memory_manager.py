"""Tests for memory manager."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.domain.models import RunContext
from app.memory.facade import FileMemoryFacade
from app.memory.models import MemoryReadRequest, MemoryRecord, MemoryScope, MemoryStatus, MemoryType
from app.memory.policies import default_memory_policy
from app.memory.stores.jsonl_file_store import JsonlFileMemoryStore
from app.runtime.agent_capability import AgentCapability, AgentCapabilityRegistry
from app.runtime.memory_manager import MemoryManager

__all__ = []


def _capability_registry() -> AgentCapabilityRegistry:
    return AgentCapabilityRegistry.for_tests()


def _single_agent_registry(
    *,
    allow_cross_session_short_read: bool = True,
    memory_read_scopes: list[MemoryScope] | None = None,
    memory_write_scopes: list[MemoryScope] | None = None,
) -> AgentCapabilityRegistry:
    return AgentCapabilityRegistry(
        {
            "agent_main": AgentCapability(
                agent_id="agent_main",
                allowed_tools=["*"],
                memory_read_scopes=memory_read_scopes
                if memory_read_scopes is not None
                else [MemoryScope.AGENT_SHORT, MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                memory_write_scopes=memory_write_scopes
                if memory_write_scopes is not None
                else [MemoryScope.AGENT_SHORT, MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                allow_cross_session_short_read=allow_cross_session_short_read,
                allow_cross_agent_memory_read=False,
                allow_cross_agent_memory_write=False,
            )
        }
    )


def _context(session_id: str, agent_id: str = "agent_main") -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}",
        agent_id=agent_id,
        turn_id=f"turn_{session_id}",
        entry_agent_id=agent_id,
        parent_run_id=None,
        trace_flags={},
    )



def test_memory_manager_write_and_search(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(memory_facade=facade, capability_registry=_capability_registry())

    written = manager.write_memory(
        content="Prefer JSONL storage",
        tags=["preference", "storage"],
        context=_context("sess_1"),
        source_event_id="evt_1",
    )
    hits = manager.search(query="jsonl", limit=5, context=_context("sess_1"))

    assert written.memory_id
    assert len(hits) == 1
    assert hits[0].content == "Prefer JSONL storage"


def test_memory_manager_write_persists_v2_record(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(memory_facade=facade, capability_registry=_capability_registry())

    manager.write_memory(
        content="Remember deployment checklist",
        tags=["plan", "long_term"],
        context=_context("sess_1"),
        source_event_id="evt_2",
    )

    bundle = facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_1",
            query="deployment",
            limit=5,
            token_budget=1200,
        )
    )
    assert len(bundle.items) == 1
    assert bundle.items[0].scope.value == "agent_long"


def test_memory_manager_write_without_tags_defaults_to_agent_short(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(memory_facade=facade, capability_registry=_capability_registry())

    manager.write_memory(
        content="Keep answers concise",
        tags=[],
        context=_context("sess_1"),
        source_event_id="evt_3",
    )

    bundle = facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_1",
            query="concise",
            limit=5,
            token_budget=1200,
        )
    )
    assert len(bundle.items) == 1
    assert bundle.items[0].scope.value == "agent_short"


def test_memory_manager_search_recalls_chinese_long_memory_by_question_form(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(memory_facade=facade, capability_registry=_capability_registry())

    manager.write_memory(
        content='用户要求以后叫我"李华"，这是我的新名字/称呼。',
        tags=["preference", "long_term"],
        context=_context("sess_first"),
        source_event_id="evt_name",
    )

    hits = manager.search(query="你叫什么名字", limit=5, context=_context("sess_second"))

    assert len(hits) >= 1
    assert any("李华" in item.content for item in hits)


def test_memory_manager_search_prefers_preferred_name_memory_for_name_question(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(memory_facade=facade, capability_registry=_capability_registry())

    manager.write_memory(
        content='以后叫我"李华"',
        tags=["preference", "long_term"],
        context=_context("sess_name_prefer"),
        source_event_id="evt_name_prefer",
    )
    manager.write_memory(
        content="这个项目名字叫珍格格",
        tags=["long_term"],
        context=_context("sess_name_prefer"),
        source_event_id="evt_name_other",
    )

    hits = manager.search(query="你叫什么名字", limit=5, context=_context("sess_name_prefer"))

    assert len(hits) >= 2
    assert hits[0].content == '以后叫我"李华"'


def test_memory_manager_search_prefers_canonical_exact_memory_over_newer_text_match(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(memory_facade=facade, capability_registry=_capability_registry())

    manager.write_memory(
        content="用户称呼是李华",
        tags=["preference", "long_term"],
        context=_context("sess_exact_prefer"),
        source_event_id="evt_exact_prefer",
    )
    manager.write_memory(
        content="用户长期目标是加入李华实验室",
        tags=["long_term"],
        context=_context("sess_exact_prefer"),
        source_event_id="evt_exact_other",
    )

    hits = manager.search(query="用户称呼是李华", limit=5, context=_context("sess_exact_prefer"))

    assert len(hits) >= 2
    assert hits[0].content == "用户称呼是李华"


def test_memory_manager_write_respects_scope_permission(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(
        memory_facade=facade,
        capability_registry=_single_agent_registry(memory_write_scopes=[MemoryScope.AGENT_SHORT]),
    )

    with pytest.raises(ValidationError):
        manager.write_memory(
            content="平台约束：所有接口必须鉴权。",
            tags=["long_term", "constraint"],
            context=_context("sess_scope"),
            source_event_id="evt_scope",
        )


def test_memory_manager_short_read_can_be_session_bound_by_capability(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(
        memory_facade=facade,
        capability_registry=_single_agent_registry(allow_cross_session_short_read=False),
    )

    manager.write_memory(
        content="回答尽量简洁",
        tags=[],
        context=_context("sess_local_1"),
        source_event_id="evt_local",
    )

    current_hits = manager.search(query="简洁", limit=5, context=_context("sess_local_1"))
    other_hits = manager.search(query="简洁", limit=5, context=_context("sess_local_2"))

    assert len(current_hits) >= 1
    assert other_hits == []


def test_memory_manager_search_context_memories_excludes_agent_short(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(memory_facade=facade, capability_registry=_capability_registry())

    manager.write_memory(
        content="提到 state 这个词即可",
        tags=[],
        context=_context("sess_ctx_1"),
        source_event_id="evt_ctx_short",
    )
    manager.write_memory(
        content="用户长期偏好：回答简洁直接",
        tags=["preference", "long_term"],
        context=_context("sess_ctx_1"),
        source_event_id="evt_ctx_long",
    )

    hits, summary = manager.search_context_memories(
        query="简洁 state",
        limit=5,
        context=_context("sess_ctx_1"),
    )

    assert len(hits) == 1
    assert hits[0].content == "用户长期偏好：回答简洁直接"
    assert "agent_short" not in summary["searched_scopes"]


def test_memory_manager_rejects_obvious_working_state_write(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(memory_facade=facade, capability_registry=_capability_registry())

    with pytest.raises(ValidationError) as exc_info:
        manager.write_memory(
            content="下一步：先补 state_set 测试",
            tags=[],
            context=_context("sess_reject_state"),
            source_event_id="evt_reject_state",
        )

    assert "state_set" in str(exc_info.value)


def test_memory_manager_rejects_raw_json_blob_write(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(memory_facade=facade, capability_registry=_capability_registry())

    with pytest.raises(ValidationError) as exc_info:
        manager.write_memory(
            content='{"steps": ["a", "b"], "status": "ok"}',
            tags=[],
            context=_context("sess_reject_blob"),
            source_event_id="evt_reject_blob",
        )

    assert "raw file/tool output" in str(exc_info.value)


def test_memory_manager_write_persists_structured_classification_metadata(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(memory_facade=facade, capability_registry=_capability_registry())

    manager.write_memory(
        content='以后叫我"李华"',
        tags=["preference", "long_term"],
        context=_context("sess_classified"),
        source_event_id="evt_classified",
    )

    bundle = facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_classified",
            query="李华",
            limit=5,
            token_budget=1200,
        )
    )

    assert len(bundle.items) == 1
    metadata = bundle.items[0].metadata
    assert metadata["kind"] == "user_preference"
    assert metadata["source_kind"] == "explicit_user"
    assert metadata["canonical_key"] == "preferred_name"
    assert metadata["normalized_value"] == "李华"


def test_memory_manager_resolve_update_targets_prefers_canonical_exact(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(memory_facade=facade, capability_registry=_capability_registry())

    manager.write_memory(
        content="用户称呼是李华",
        tags=["preference", "long_term"],
        context=_context("sess_update_resolve"),
        source_event_id="evt_update_name_1",
    )
    manager.write_memory(
        content="用户长期目标是加入李华实验室",
        tags=["long_term"],
        context=_context("sess_update_resolve"),
        source_event_id="evt_update_name_2",
    )

    hits, match_strategy = manager.resolve_update_targets(
        query="用户称呼是李华",
        limit=5,
        context=_context("sess_update_resolve"),
    )

    assert match_strategy == "canonical_exact"
    assert len(hits) == 1
    assert hits[0].metadata["canonical_key"] == "preferred_name"
    assert hits[0].metadata["normalized_value"] == "李华"


def test_memory_manager_ensure_structured_metadata_backfills_legacy_record(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    manager = MemoryManager(memory_facade=facade, capability_registry=_capability_registry())
    now = datetime.now(UTC)
    legacy_record = MemoryRecord(
        memory_id="mem_legacy_name",
        scope=MemoryScope.AGENT_LONG,
        owner_agent_id="agent_main",
        session_id=None,
        memory_type=MemoryType.PREFERENCE,
        content="以后叫我李华",
        tags=["preference", "long_term"],
        importance=0.7,
        confidence=0.7,
        status=MemoryStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        expires_at=None,
        source_event_id=None,
        source_agent_id="agent_main",
        version=1,
        parent_memory_id=None,
        content_hash="",
        metadata={},
    )
    memory_store.write_records([legacy_record])

    refreshed = manager.ensure_structured_metadata(
        context=_context("sess_update_resolve"),
        record=legacy_record,
    )

    assert refreshed.memory_id == legacy_record.memory_id
    assert refreshed.version == 2
    assert refreshed.metadata["canonical_key"] == "preferred_name"
    assert refreshed.metadata["normalized_value"] == "李华"
    assert refreshed.metadata["source_kind"] == "explicit_user"
