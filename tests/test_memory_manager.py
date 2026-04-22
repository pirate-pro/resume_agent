"""Tests for memory manager."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.domain.models import RunContext
from app.memory.facade import FileMemoryFacade
from app.memory.models import MemoryReadRequest, MemoryScope
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
        content="临时偏好：回答尽量简洁",
        tags=[],
        context=_context("sess_local_1"),
        source_event_id="evt_local",
    )

    current_hits = manager.search(query="简洁", limit=5, context=_context("sess_local_1"))
    other_hits = manager.search(query="简洁", limit=5, context=_context("sess_local_2"))

    assert len(current_hits) >= 1
    assert other_hits == []
