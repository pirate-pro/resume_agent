"""Contract tests for multi-agent preparation boundaries."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.domain.models import RunContext
from app.schemas.chat import ChatRequest
from tests.helpers import StaticModelClient, build_chat_service

__all__ = []


def _context(session_id: str, agent_id: str) -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}_{agent_id}",
        agent_id=agent_id,
        turn_id=f"turn_{session_id}",
        entry_agent_id=agent_id,
        parent_run_id=None,
        trace_flags={},
    )


def test_single_agent_run_preserves_v2_event_fields_and_participants(tmp_path: Path) -> None:
    service, _ = build_chat_service(data_dir=tmp_path, model_client=StaticModelClient(content="ok"))

    response = asyncio.run(
        service.chat(
            ChatRequest(
                session_id=None,
                message="hello",
                skill_names=["base", "memory"],
                max_tool_rounds=2,
                entry_agent_id="agent_alpha",
            )
        )
    )
    events = service.list_session_events(response.session_id)
    meta = service._session_repository.get_session(response.session_id)  # noqa: SLF001

    assert meta is not None
    assert "agent_alpha" in meta.participants
    assert meta.entry_agent_id == "agent_alpha"
    assert len(events) >= 3
    assert all(item.event_version == 2 for item in events)
    assert all(item.agent_id == "agent_alpha" for item in events)
    assert all(item.run_id for item in events)


def test_dual_agent_memory_isolation_keeps_private_memory_in_owner_scope(tmp_path: Path) -> None:
    _, memory_manager = build_chat_service(data_dir=tmp_path, model_client=StaticModelClient(content="ok"))

    memory_manager.write_memory(
        content="这是 agent_alpha 的私有偏好",
        tags=["preference", "long_term"],
        context=_context("sess_alpha", "agent_alpha"),
        source_event_id="evt_alpha",
    )

    own_hits = memory_manager.search_for_agent(
        query="私有偏好",
        limit=5,
        request_agent_id="agent_alpha",
    )
    other_hits = memory_manager.search_for_agent(
        query="私有偏好",
        limit=5,
        request_agent_id="agent_beta",
    )

    assert any("agent_alpha" in item.content for item in own_hits)
    assert other_hits == []


def test_shared_memory_is_visible_across_agents_but_cross_agent_read_switch_is_guarded(tmp_path: Path) -> None:
    _, memory_manager = build_chat_service(data_dir=tmp_path, model_client=StaticModelClient(content="ok"))

    memory_manager.write_memory(
        content="平台统一约束：所有接口返回 JSON。",
        tags=["shared", "system_policy", "verified"],
        context=_context("sess_shared", "agent_alpha"),
        source_event_id="evt_shared",
    )

    shared_hits = memory_manager.search_for_agent(
        query="所有接口返回 JSON",
        limit=5,
        request_agent_id="agent_beta",
    )
    assert any("所有接口返回 JSON" in item.content for item in shared_hits)

    with pytest.raises(ValidationError):
        memory_manager.search_for_agent(
            query="所有接口返回 JSON",
            limit=5,
            request_agent_id="agent_beta",
            target_agent_id="agent_alpha",
        )
