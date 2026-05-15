"""Tests for debug token usage aggregation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_token_usage_debug_service
from app.core.errors import SessionNotFoundError
from app.debug.token_usage import TokenUsageDebugService
from app.domain.models import EventRecord
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.main import app

__all__ = []


def test_token_usage_summary_aggregates_sessions_and_buckets(tmp_path: Path) -> None:
    repository = JsonlSessionRepository(data_dir=tmp_path)
    _create_session(repository, "sess_alpha", "第一轮诊断")
    _create_session(repository, "sess_beta", "岗位匹配")
    base = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
    repository.append_event(
        "sess_alpha",
        _usage_event(
            "evt_alpha_1",
            "sess_alpha",
            created_at=base,
            agent_id="agent_main",
            prompt_tokens=100,
            completion_tokens=40,
            total_tokens=140,
            phase="tool_loop",
            model="model-a",
        ),
    )
    repository.append_event(
        "sess_alpha",
        _usage_event(
            "evt_alpha_2",
            "sess_alpha",
            created_at=base + timedelta(minutes=1),
            agent_id="resume_agent",
            prompt_tokens=200,
            completion_tokens=50,
            total_tokens=250,
            phase="tool_loop",
            model="model-a",
            estimated=True,
        ),
    )
    repository.append_event(
        "sess_beta",
        _usage_event(
            "evt_beta_1",
            "sess_beta",
            created_at=base + timedelta(minutes=2),
            agent_id="job_agent",
            prompt_tokens=300,
            completion_tokens=70,
            total_tokens=370,
            phase="final_answer",
            model="model-b",
        ),
    )

    service = TokenUsageDebugService(session_repository=repository)
    summary = service.summarize(session_limit=10, call_limit=10, bucket_limit=10)

    assert summary.session_count == 2
    assert summary.call_count == 3
    assert summary.prompt_tokens == 600
    assert summary.completion_tokens == 160
    assert summary.total_tokens == 760
    assert summary.estimated_count == 1
    assert summary.provider_count == 2
    assert [item.session_id for item in summary.sessions] == ["sess_beta", "sess_alpha"]
    assert {item.key: item.total_tokens for item in summary.agent_buckets} == {
        "job_agent": 370,
        "resume_agent": 250,
        "agent_main": 140,
    }
    assert [item.event_id for item in summary.recent_calls] == [
        "evt_beta_1",
        "evt_alpha_2",
        "evt_alpha_1",
    ]


def test_token_usage_calls_filter_without_product_store_coupling(tmp_path: Path) -> None:
    repository = JsonlSessionRepository(data_dir=tmp_path)
    _create_session(repository, "sess_usage", "成本排查")
    base = datetime(2026, 5, 15, 11, 0, tzinfo=UTC)
    repository.append_event(
        "sess_usage",
        EventRecord(
            event_id="evt_user",
            session_id="sess_usage",
            type="user_message",
            payload={"content": "不会被读取"},
            created_at=base,
        ),
    )
    repository.append_event(
        "sess_usage",
        _usage_event(
            "evt_estimated",
            "sess_usage",
            created_at=base + timedelta(seconds=1),
            agent_id="resume_agent",
            prompt_tokens=90,
            completion_tokens=10,
            total_tokens=100,
            phase="tool_loop",
            estimated=True,
        ),
    )
    repository.append_event(
        "sess_usage",
        _usage_event(
            "evt_provider",
            "sess_usage",
            created_at=base + timedelta(seconds=2),
            agent_id="resume_agent",
            prompt_tokens=70,
            completion_tokens=5,
            total_tokens=75,
            phase="final_answer",
        ),
    )

    service = TokenUsageDebugService(session_repository=repository)

    assert [item.event_id for item in service.list_calls(limit=10)] == [
        "evt_provider",
        "evt_estimated",
    ]
    assert [item.event_id for item in service.list_calls(agent_id="resume_agent", phase="tool_loop", estimated=True)] == [
        "evt_estimated"
    ]
    assert service.summarize(agent_id="job_agent").call_count == 0


def test_token_usage_missing_total_uses_prompt_plus_completion(tmp_path: Path) -> None:
    repository = JsonlSessionRepository(data_dir=tmp_path)
    _create_session(repository, "sess_missing_total", "兼容旧事件")
    event = _usage_event(
        "evt_missing_total",
        "sess_missing_total",
        created_at=datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
        agent_id="agent_main",
        prompt_tokens=12,
        completion_tokens=8,
        total_tokens=None,
    )
    repository.append_event("sess_missing_total", event)

    call = TokenUsageDebugService(session_repository=repository).list_calls(limit=1)[0]

    assert call.total_tokens == 20


def test_token_usage_session_detail_handles_missing_session(tmp_path: Path) -> None:
    repository = JsonlSessionRepository(data_dir=tmp_path)
    service = TokenUsageDebugService(session_repository=repository)

    with pytest.raises(SessionNotFoundError):
        service.get_session_detail("sess_missing")


def test_token_usage_debug_api_exposes_summary(tmp_path: Path) -> None:
    repository = JsonlSessionRepository(data_dir=tmp_path)
    _create_session(repository, "sess_api", "API 成本看板")
    repository.append_event(
        "sess_api",
        _usage_event(
            "evt_api",
            "sess_api",
            created_at=datetime(2026, 5, 15, 13, 0, tzinfo=UTC),
            agent_id="agent_main",
            prompt_tokens=21,
            completion_tokens=9,
            total_tokens=30,
        ),
    )
    service = TokenUsageDebugService(session_repository=repository)
    app.dependency_overrides[get_token_usage_debug_service] = lambda: service

    try:
        with TestClient(app) as client:
            response = client.get("/api/debug/token-usage/summary")
            assert response.status_code == 200
            payload = _data(response)
            assert payload["call_count"] == 1
            assert payload["total_tokens"] == 30
            assert payload["sessions"][0]["session_id"] == "sess_api"
            assert str(tmp_path) not in response.text
    finally:
        app.dependency_overrides.clear()


def _create_session(repository: JsonlSessionRepository, session_id: str, title: str) -> None:
    repository.create_session(session_id)
    repository.update_session_title(session_id, title)


def _usage_event(
    event_id: str,
    session_id: str,
    *,
    created_at: datetime,
    agent_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int | None,
    phase: str = "tool_loop",
    model: str = "test-model",
    estimated: bool = False,
) -> EventRecord:
    payload: dict[str, Any] = {
        "api": "POST /v1/chat/completions",
        "operation": "model.generate",
        "mode": "stream",
        "phase": phase,
        "round_index": 1,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated": estimated,
        "usage_source": "estimated" if estimated else "provider",
        "message_count": 2,
        "tool_schema_count": 3,
        "returned_tool_call_count": 1,
        "content_chars": 20,
        "reasoning_chars": 0,
    }
    if total_tokens is not None:
        payload["total_tokens"] = total_tokens
    return EventRecord(
        event_id=event_id,
        session_id=session_id,
        type="llm_usage",
        payload=payload,
        created_at=created_at,
        agent_id=agent_id,
        run_id=f"run_{event_id}",
    )


def _data(response: Any) -> Any:
    payload = response.json()
    assert payload["code"] == 0
    assert payload["msg"] == "ok"
    return payload["data"]
