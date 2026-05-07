"""Contract tests for multi-agent preparation boundaries."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.domain.models import RunContext
from app.schemas.chat import ChatRequest
from tests.helpers import StaticModelClient, build_chat_service, build_chat_service_bundle

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


def test_single_agent_run_preserves_event_schema_fields_and_participants(tmp_path: Path) -> None:
    bundle = build_chat_service_bundle(data_dir=tmp_path, model_client=StaticModelClient(content="ok"))
    service = bundle.chat_service

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
    events = bundle.session_query_service.list_session_events(response.session_id)
    meta = service._session_repository.get_session(response.session_id)  # noqa: SLF001

    assert meta is not None
    assert "agent_alpha" in meta.participants
    assert meta.entry_agent_id == "agent_alpha"
    assert len(events) >= 3
    assert all(item.event_version == 2 for item in events)
    assert all(item.agent_id == "agent_alpha" for item in events)
    assert all(item.run_id for item in events)


def test_entry_agent_rejects_unallowed_skill(tmp_path: Path) -> None:
    bundle = build_chat_service_bundle(data_dir=tmp_path, model_client=StaticModelClient(content="ok"))

    with pytest.raises(ValidationError, match="Skill not allowed"):
        asyncio.run(
            bundle.chat_service.chat(
                ChatRequest(
                    session_id=None,
                    message="hello",
                    skill_names=["memory-editor"],
                    max_tool_rounds=0,
                    entry_agent_id="resume_agent",
                )
            )
        )


def test_entry_agent_uses_default_skills_when_request_omits_skills(tmp_path: Path) -> None:
    bundle = build_chat_service_bundle(data_dir=tmp_path, model_client=StaticModelClient(content="ok"))

    response = asyncio.run(
        bundle.chat_service.chat(
            ChatRequest(
                session_id=None,
                message="hello",
                skill_names=[],
                max_tool_rounds=0,
                entry_agent_id="resume_agent",
            )
        )
    )

    assert response.answer == "ok"


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


def test_child_agent_long_term_memory_isolated_between_resume_and_job_agents(tmp_path: Path) -> None:
    _, memory_manager = build_chat_service(data_dir=tmp_path, model_client=StaticModelClient(content="ok"))

    memory_manager.write_memory(
        content="resume_agent 私有长期记忆：用户简历重点是后端项目。",
        tags=["preference", "long_term"],
        context=_context("sess_resume_memory", "resume_agent"),
        source_event_id="evt_resume_memory",
    )
    memory_manager.write_memory(
        content="job_agent 私有长期记忆：目标岗位强调数据平台经验。",
        tags=["preference", "long_term"],
        context=_context("sess_job_memory", "job_agent"),
        source_event_id="evt_job_memory",
    )

    resume_hits = memory_manager.search_for_agent(
        query="私有长期记忆",
        limit=10,
        request_agent_id="resume_agent",
    )
    job_hits = memory_manager.search_for_agent(
        query="私有长期记忆",
        limit=10,
        request_agent_id="job_agent",
    )

    assert any("resume_agent 私有长期记忆" in item.content for item in resume_hits)
    assert all("job_agent 私有长期记忆" not in item.content for item in resume_hits)
    assert any("job_agent 私有长期记忆" in item.content for item in job_hits)
    assert all("resume_agent 私有长期记忆" not in item.content for item in job_hits)


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
