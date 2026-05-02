"""Pressure-style tests for memory, mid-term flush, and context compaction."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.domain.models import EventRecord, RunContext
from app.domain.protocols import ModelResponse, StreamChunk
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.memory.file_store import FileMemoryStore
from app.runtime.agent_capability import AgentCapabilityRegistry
from app.runtime.context_compactor import ContextCompactionConfig, ContextCompactor
from app.runtime.memory_manager import MemoryManager
from app.runtime.mid_term.event_packer import MidTermEventPackBuilder
from app.runtime.mid_term.models import FlushCursor

__all__ = []


class _CompactionSummaryModel:
    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = (system_prompt, tools)
        payload = _extract_compaction_prompt_payload(messages[-1]["content"])
        compressed_units = [item for item in payload.get("compressed_units", []) if isinstance(item, dict)]
        evidence: list[str] = []
        for unit in compressed_units[:4]:
            assert "events" not in unit
            raw_ids = unit.get("event_ids")
            if isinstance(raw_ids, list):
                evidence.extend(str(item) for item in raw_ids if isinstance(item, str))
        if not evidence:
            evidence = ["evt_missing"]
        return ModelResponse(
            content=json.dumps(
                {
                    "summary": "压缩后的历史上下文摘要，保留用户意图、工具结果和可复用记忆线索。",
                    "timeline": ["用户持续进行压力测试", "工具调用返回了多轮结果"],
                    "decisions": ["保留最近未压缩事件继续推进"],
                    "open_threads": ["继续观察 memory 和 context 压缩质量"],
                    "tool_progress": [
                        {
                            "tool_name": "memory_search",
                            "call_summary": "查询历史记忆",
                            "result_summary": "返回匹配结果",
                            "success": True,
                            "evidence_event_ids": evidence[:2],
                        }
                    ],
                    "agent_activity": ["主 agent 处理了多轮事件"],
                    "memory_relevant": ["用户偏好和名字信息需要保持最新"],
                    "evidence_event_ids": evidence,
                },
                ensure_ascii=False,
            ),
            tool_calls=[],
        )

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        response = self.generate(system_prompt=system_prompt, messages=messages, tools=tools)
        yield StreamChunk(delta=response.content, finished=True, has_tool_call_delta=False)


def test_memory_name_conflict_pressure_keeps_latest_value(tmp_path: Path) -> None:
    context = _context("sess_memory_pressure")
    manager = MemoryManager(
        capability_registry=AgentCapabilityRegistry.for_tests(),
        memory_store=FileMemoryStore(root_dir=tmp_path / "memory"),
    )

    for index in range(24):
        manager.write_memory(
            content=f"用户偏好第 {index} 轮回答保持结构化。",
            tags=["preference", "long_term"],
            context=context,
            source_event_id=f"evt_pref_{index}",
        )
    manager.write_memory(
        content="用户希望我叫他小猪。",
        tags=["preference", "long_term"],
        context=context,
        source_event_id="evt_name_old",
    )
    manager.write_memory(
        content="用户希望我叫他小明。",
        tags=["preference", "long_term"],
        context=context,
        source_event_id="evt_name_new",
    )

    hits = manager.search(query="用户名字", limit=8, context=context)
    name_hits = [item for item in hits if item.metadata.get("canonical_key") == "preferred_name"]

    assert len(name_hits) == 1
    assert name_hits[0].metadata["normalized_value"] == "小明"
    assert "小猪" not in "\n".join(item.content for item in hits)


def test_mid_term_event_packer_pressure_keeps_single_flush_pack_without_splitting_tool_pairs(tmp_path: Path) -> None:
    session_id = "sess_mid_term_pressure"
    repo = JsonlSessionRepository(data_dir=tmp_path)
    repo.create_session(session_id)
    base_time = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
    for index in range(36):
        _append_event(
            repo,
            session_id=session_id,
            event_id=f"evt_user_{index:03d}",
            event_type="user_message",
            payload={"content": f"第 {index} 轮用户提出 memory/context 压力测试问题"},
            created_at=base_time + timedelta(seconds=index * 4),
        )
        _append_event(
            repo,
            session_id=session_id,
            event_id=f"evt_call_{index:03d}",
            event_type="tool_call",
            payload={
                "name": "memory_search",
                "arguments": {"query": f"压力测试 {index}"},
                "tool_call_id": f"call_{index:03d}",
            },
            created_at=base_time + timedelta(seconds=index * 4 + 1),
        )
        _append_event(
            repo,
            session_id=session_id,
            event_id=f"evt_result_{index:03d}",
            event_type="tool_result",
            payload={
                "tool_name": "memory_search",
                "success": True,
                "content": "命中若干记忆，包含偏好、名字和上下文。",
                "tool_call_id": f"call_{index:03d}",
            },
            created_at=base_time + timedelta(seconds=index * 4 + 2),
        )
        _append_event(
            repo,
            session_id=session_id,
            event_id=f"evt_assistant_{index:03d}",
            event_type="assistant_message",
            payload={"content": f"第 {index} 轮回答完成"},
            created_at=base_time + timedelta(seconds=index * 4 + 3),
        )

    packer = MidTermEventPackBuilder(
        session_repository=repo,
        model_context_window_tokens=4096,
        model_input_ratio=0.4,
        model_output_reserve_tokens=300,
        prompt_overhead_tokens=200,
        max_input_tokens=900,
    )
    packs, reason = packer.build(context=_context(session_id), cursor=FlushCursor(last_event_id=None, last_flushed_at=None))

    assert reason == "ready"
    assert packs is not None
    assert len(packs) == 1
    for pack in packs:
        event_ids = {str(item.get("event_id")) for item in pack.events}
        for unit in pack.semantic_units:
            if unit["unit_type"] != "tool_pair":
                continue
            pair_ids = unit["event_ids"]
            assert len(pair_ids) == 2
            assert pair_ids[0].startswith("evt_call_")
            assert pair_ids[1].startswith("evt_result_")
            assert set(pair_ids).issubset(event_ids)


def test_context_compactor_pressure_keeps_recent_tool_pair_atomic(tmp_path: Path) -> None:
    session_id = "sess_compaction_pressure"
    repo = JsonlSessionRepository(data_dir=tmp_path)
    repo.create_session(session_id)
    base_time = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
    for index in range(28):
        _append_event(
            repo,
            session_id=session_id,
            event_id=f"evt_user_{index:03d}",
            event_type="user_message",
            payload={"content": f"第 {index} 轮上下文压缩压力测试"},
            created_at=base_time + timedelta(seconds=index * 4),
        )
        _append_event(
            repo,
            session_id=session_id,
            event_id=f"evt_assistant_{index:03d}",
            event_type="assistant_message",
            payload={"content": f"第 {index} 轮回复"},
            created_at=base_time + timedelta(seconds=index * 4 + 1),
        )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_call_latest",
        event_type="tool_call",
        payload={"name": "memory_search", "arguments": {"query": "名字"}, "tool_call_id": "call_latest"},
        created_at=base_time + timedelta(seconds=200),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_result_latest",
        event_type="tool_result",
        payload={
            "tool_name": "memory_search",
            "success": True,
            "content": "命中用户最新名字。",
            "tool_call_id": "call_latest",
        },
        created_at=base_time + timedelta(seconds=201),
    )

    compactor = ContextCompactor(
        session_repository=repo,
        model_client=_CompactionSummaryModel(),
        config=ContextCompactionConfig(trigger_event_count=20, retain_event_count=2),
    )
    result = compactor.compact_after_flush(_context(session_id))
    events = repo.list_events(session_id)

    assert result.compacted is True
    assert events[0].type == "context_summary"
    assert [event.event_id for event in events[-2:]] == ["evt_call_latest", "evt_result_latest"]
    assert events[-2].payload["tool_call_id"] == events[-1].payload["tool_call_id"]


def _context(session_id: str) -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}",
        agent_id="agent_main",
        turn_id=f"turn_{session_id}",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={},
    )


def _append_event(
    repo: JsonlSessionRepository,
    *,
    session_id: str,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    created_at: datetime,
) -> None:
    repo.append_event(
        session_id,
        EventRecord(
            event_id=event_id,
            session_id=session_id,
            type=event_type,
            payload=payload,
            created_at=created_at,
            agent_id="agent_main",
            run_id=f"run_{session_id}",
            event_version=2,
        ),
    )


def _extract_compaction_prompt_payload(content: object) -> dict[str, Any]:
    text = str(content)
    start = text.find("{")
    if start < 0:
        raise AssertionError("compaction prompt payload is missing")
    payload = json.loads(text[start:])
    if not isinstance(payload, dict):
        raise AssertionError("compaction prompt payload must be object")
    return payload
