"""Tests for short-term session event compaction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.errors import ValidationError
from app.domain.models import EventRecord, RunContext
from app.domain.protocols import ModelResponse
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.runtime.context_compactor import (
    CONTEXT_SUMMARY_EVENT,
    ContextCompactionConfig,
    ContextCompactor,
    RetentionStrategy,
)
from tests.helpers import StaticModelClient


def _context(session_id: str = "sess_compact") -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id="run_compact",
        agent_id="agent_main",
        turn_id="turn_compact",
        entry_agent_id="agent_main",
    )


def _event(
    session_id: str,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    offset_seconds: int,
) -> EventRecord:
    return EventRecord(
        event_id=event_id,
        session_id=session_id,
        type=event_type,
        payload=payload,
        created_at=datetime(2026, 4, 30, tzinfo=UTC) + timedelta(seconds=offset_seconds),
        agent_id="agent_main",
        run_id="run_compact",
    )


def _append(repo: JsonlSessionRepository, event: EventRecord) -> None:
    repo.append_event(event.session_id, event)


def _summary_model() -> StaticModelClient:
    return StaticModelClient(
        '{"summary":"用户前面讨论了上下文压缩，并完成了一次工具查询。",'
        '"timeline":["讨论上下文压缩"],'
        '"decisions":["压缩后保留 summary + recent events"],'
        '"open_threads":[],'
        '"tool_progress":[{"tool_name":"memory_search","call_summary":"查询名字",'
        '"result_summary":"返回已有名字记忆","success":true,'
        '"evidence_event_ids":["evt_tool_call","evt_tool_result"]}],'
        '"agent_activity":[],'
        '"memory_relevant":[],'
        '"evidence_event_ids":["evt_user_1","evt_tool_call","evt_tool_result"]}'
    )


def test_context_compaction_defaults_are_practical_for_early_runtime() -> None:
    config = ContextCompactionConfig()

    assert config.trigger_event_count == 60
    assert config.trigger_token_count == 12000
    assert config.trigger_context_window_ratio == 0.45
    assert config.retain_event_count == 32
    assert config.retain_token_count == 7000


def test_context_compactor_rewrites_events_to_summary_plus_recent(tmp_path: Path) -> None:
    repo = JsonlSessionRepository(data_dir=tmp_path)
    session_id = "sess_compact"
    repo.create_session(session_id)
    for event in [
        _event(session_id, "evt_user_1", "user_message", {"content": "先讨论上下文压缩"}, 1),
        _event(session_id, "evt_tool_call", "tool_call", {"name": "memory_search", "arguments": {"query": "名字"}, "tool_call_id": "call_1"}, 2),
        _event(session_id, "evt_tool_result", "tool_result", {"tool_name": "memory_search", "success": True, "content": "命中名字记忆", "tool_call_id": "call_1"}, 3),
        _event(session_id, "evt_user_2", "user_message", {"content": "最近这条要原样保留"}, 4),
        _event(session_id, "evt_assistant_2", "assistant_message", {"content": "我会保留最近内容"}, 5),
    ]:
        _append(repo, event)

    compactor = ContextCompactor(
        session_repository=repo,
        model_client=_summary_model(),
        config=ContextCompactionConfig(
            trigger_event_count=3,
            retention_strategy=RetentionStrategy.EVENT_COUNT,
            retain_event_count=2,
        ),
    )

    result = compactor.compact_after_flush(_context(session_id))

    assert result.compacted is True
    events = repo.list_events(session_id)
    assert [event.type for event in events] == [CONTEXT_SUMMARY_EVENT, "user_message", "assistant_message"]
    assert events[0].payload["compressed_event_count"] == 3
    assert events[0].payload["retained_event_count"] == 2
    assert "上下文压缩" in events[0].payload["summary"]
    assert [event.event_id for event in events[1:]] == ["evt_user_2", "evt_assistant_2"]


def test_context_compactor_keeps_tool_pairs_atomic_when_retaining(tmp_path: Path) -> None:
    repo = JsonlSessionRepository(data_dir=tmp_path)
    session_id = "sess_compact_tool_pair"
    repo.create_session(session_id)
    for event in [
        _event(session_id, "evt_user_1", "user_message", {"content": "旧消息"}, 1),
        _event(session_id, "evt_tool_call", "tool_call", {"name": "memory_search", "arguments": {"query": "名字"}, "tool_call_id": "call_1"}, 2),
        _event(session_id, "evt_tool_result", "tool_result", {"tool_name": "memory_search", "success": True, "content": "命中名字记忆", "tool_call_id": "call_1"}, 3),
        _event(session_id, "evt_user_2", "user_message", {"content": "最新问题"}, 4),
    ]:
        _append(repo, event)

    compactor = ContextCompactor(
        session_repository=repo,
        model_client=_summary_model(),
        config=ContextCompactionConfig(
            trigger_event_count=3,
            retention_strategy=RetentionStrategy.EVENT_COUNT,
            retain_event_count=3,
        ),
    )

    result = compactor.compact_after_flush(_context(session_id))

    assert result.compacted is True
    events = repo.list_events(session_id)
    assert [event.event_id for event in events[1:]] == ["evt_tool_call", "evt_tool_result", "evt_user_2"]


def test_context_compactor_does_not_rewrite_when_model_output_invalid(tmp_path: Path) -> None:
    repo = JsonlSessionRepository(data_dir=tmp_path)
    session_id = "sess_compact_invalid"
    repo.create_session(session_id)
    original_events = [
        _event(session_id, "evt_user_1", "user_message", {"content": "旧消息"}, 1),
        _event(session_id, "evt_user_2", "user_message", {"content": "中间消息"}, 2),
        _event(session_id, "evt_user_3", "user_message", {"content": "最新消息"}, 3),
        _event(session_id, "evt_assistant_3", "assistant_message", {"content": "最新回答"}, 4),
    ]
    for event in original_events:
        _append(repo, event)
    compactor = ContextCompactor(
        session_repository=repo,
        model_client=StaticModelClient("not json"),
        config=ContextCompactionConfig(trigger_event_count=3, retain_event_count=2),
    )

    with pytest.raises(ValidationError):
        compactor.compact_after_flush(_context(session_id))

    events = repo.list_events(session_id)
    assert [event.event_id for event in events] == [event.event_id for event in original_events]


def test_context_compactor_skips_rewrite_when_events_change_during_model_call(tmp_path: Path) -> None:
    repo = JsonlSessionRepository(data_dir=tmp_path)
    session_id = "sess_compact_race"
    repo.create_session(session_id)
    original_events = [
        _event(session_id, "evt_user_1", "user_message", {"content": "旧消息"}, 1),
        _event(session_id, "evt_user_2", "user_message", {"content": "中间消息"}, 2),
        _event(session_id, "evt_user_3", "user_message", {"content": "最新消息"}, 3),
        _event(session_id, "evt_assistant_3", "assistant_message", {"content": "最新回答"}, 4),
    ]
    for event in original_events:
        _append(repo, event)

    class MutatingModel(StaticModelClient):
        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _append(repo, _event(session_id, "evt_late", "user_message", {"content": "并发新增事件"}, 5))
            return super().generate(system_prompt=system_prompt, messages=messages, tools=tools)

    compactor = ContextCompactor(
        session_repository=repo,
        model_client=MutatingModel(
            '{"summary":"旧消息摘要","timeline":[],"decisions":[],"open_threads":[],'
            '"tool_progress":[],"agent_activity":[],"memory_relevant":[],"evidence_event_ids":["evt_user_1"]}'
        ),
        config=ContextCompactionConfig(trigger_event_count=3, retain_event_count=2),
    )

    result = compactor.compact_after_flush(_context(session_id))

    assert result.compacted is False
    assert result.reason == "events_changed_during_compaction"
    events = repo.list_events(session_id)
    assert [event.event_id for event in events] == [event.event_id for event in original_events] + ["evt_late"]
