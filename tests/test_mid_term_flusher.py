"""Tests for model-driven mid-term flush jobs."""

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
from app.runtime.memory_manager import MemoryManager
from app.runtime.mid_term_flusher import MidTermFlusher

__all__ = []


class _ValidSummaryModel:
    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = (system_prompt, tools)
        payload = _build_summary_payload(_extract_pack_from_prompt(messages))
        return ModelResponse(content=json.dumps(payload, ensure_ascii=False), tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        response = self.generate(system_prompt=system_prompt, messages=messages, tools=tools)
        yield StreamChunk(delta=response.content, finished=True, has_tool_call_delta=False)


class _InvalidSummaryModel:
    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = (system_prompt, messages, tools)
        return ModelResponse(content='{"active_context":[]}', tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        _ = (system_prompt, messages, tools)
        yield StreamChunk(delta='{"active_context":[]}', finished=True, has_tool_call_delta=False)


class _CapturingSummaryModel:
    def __init__(self) -> None:
        self.captured_packs: list[dict[str, Any]] = []

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = (system_prompt, tools)
        pack = _extract_pack_from_prompt(messages)
        self.captured_packs.append(pack)
        payload = _build_summary_payload(pack)
        return ModelResponse(content=json.dumps(payload, ensure_ascii=False), tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        response = self.generate(system_prompt=system_prompt, messages=messages, tools=tools)
        yield StreamChunk(delta=response.content, finished=True, has_tool_call_delta=False)


class _OldNameCandidateModel:
    def __init__(self, content: str) -> None:
        self._content = content

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = (system_prompt, tools)
        pack = _extract_pack_from_prompt(messages)
        events = _event_index_from_pack(pack)
        event_ids = [str(item.get("event_id", "")).strip() for item in events if str(item.get("event_id", "")).strip()]
        evidence = event_ids[:1] or ["evt_missing"]
        payload = {
            "active_context": [],
            "decisions": [],
            "progress": [],
            "open_questions": [],
            "candidate_long_term": [
                {
                    "content": self._content,
                    "tags": ["preference", "long_term"],
                    "confidence": 0.9,
                    "why_reusable": "用户名字偏好",
                    "evidence_event_ids": evidence,
                }
            ],
            "artifact_refs": [],
        }
        return ModelResponse(content=json.dumps(payload, ensure_ascii=False), tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        response = self.generate(system_prompt=system_prompt, messages=messages, tools=tools)
        yield StreamChunk(delta=response.content, finished=True, has_tool_call_delta=False)


class _StaticSummaryModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = (system_prompt, messages, tools)
        return ModelResponse(content=json.dumps(self._payload, ensure_ascii=False), tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        response = self.generate(system_prompt=system_prompt, messages=messages, tools=tools)
        yield StreamChunk(delta=response.content, finished=True, has_tool_call_delta=False)


def _extract_pack_from_prompt(messages: list[dict[str, Any]]) -> dict[str, Any]:
    if not messages:
        raise AssertionError("summarizer message is empty")
    content = str(messages[-1].get("content", ""))
    marker = "Event pack:\n"
    index = content.find(marker)
    if index < 0:
        raise AssertionError("event pack marker is missing from prompt")
    payload_text = content[index + len(marker) :].strip()
    payload = json.loads(payload_text)
    if not isinstance(payload, dict):
        raise AssertionError("event pack payload must be object")
    return payload


def _build_summary_payload(pack: dict[str, Any]) -> dict[str, Any]:
    events = _event_index_from_pack(pack)
    event_ids = [str(item.get("event_id", "")).strip() for item in events if str(item.get("event_id", "")).strip()]
    event_types: dict[str, str] = {
        str(item.get("event_id", "")).strip(): str(item.get("type", "")).strip() for item in events
    }
    user_id = _first_event_id_by_type(event_types, "user_message") or event_ids[0]
    assistant_id = _first_event_id_by_type(event_types, "assistant_message") or event_ids[-1]
    run_finished_id = _first_event_id_by_type(event_types, "run_finished") or event_ids[-1]
    tool_call_id = _first_event_id_by_type(event_types, "tool_call")
    tool_result_id = _first_event_id_by_type(event_types, "tool_result")
    progress_items: list[dict[str, Any]] = []
    if tool_call_id and tool_result_id:
        progress_items.append(
            {
                "tool_name": "memory_search",
                "call_summary": "查询用户偏好",
                "result_summary": "返回检索结果",
                "success": True,
                "evidence_event_ids": [tool_call_id, tool_result_id],
            }
        )

    return {
        "active_context": [
            {
                "summary": "用户希望系统记住偏好信息",
                "evidence_event_ids": [user_id],
                "confidence": 0.84,
            }
        ],
        "decisions": [
            {
                "summary": "本轮继续沿用用户偏好回复",
                "evidence_event_ids": [assistant_id],
                "stability": "tentative",
            }
        ],
        "progress": progress_items,
        "open_questions": [
            {
                "question": "后续是否需要提升为长期记忆",
                "evidence_event_ids": [run_finished_id],
            }
        ],
        "candidate_long_term": [
            {
                "content": "用户偏好被长期记住",
                "tags": ["preference"],
                "confidence": 0.86,
                "why_reusable": "跨会话复用",
                "evidence_event_ids": [user_id],
            }
        ],
        "artifact_refs": [
            {
                "path_or_file_id": "session://events",
                "reason": "回溯本轮执行细节",
                "evidence_event_ids": [run_finished_id],
            }
        ],
    }


def _empty_summary_payload() -> dict[str, Any]:
    return {
        "active_context": [],
        "decisions": [],
        "progress": [],
        "open_questions": [],
        "candidate_long_term": [],
        "artifact_refs": [],
    }


def _first_event_id_by_type(event_types: dict[str, str], event_type: str) -> str | None:
    for event_id, observed_type in event_types.items():
        if observed_type == event_type:
            return event_id
    return None


def _event_index_from_pack(pack: dict[str, Any]) -> list[dict[str, Any]]:
    raw = pack.get("event_index")
    if raw is None:
        raw = pack.get("events")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _context(session_id: str, agent_id: str = "agent_main", run_id: str = "run_mid_term") -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=run_id,
        agent_id=agent_id,
        turn_id=f"turn_{session_id}",
        entry_agent_id=agent_id,
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
    agent_id: str = "agent_main",
    run_id: str = "run_mid_term",
) -> None:
    repo.append_event(
        session_id,
        EventRecord(
            event_id=event_id,
            session_id=session_id,
            type=event_type,
            payload=payload,
            created_at=created_at,
            agent_id=agent_id,
            run_id=run_id,
        ),
    )


def test_mid_term_flusher_writes_daily_with_model_summary(tmp_path: Path) -> None:
    session_id = "sess_mid_term_flush"
    repo = JsonlSessionRepository(data_dir=tmp_path)
    repo.create_session(session_id)
    store = FileMemoryStore(root_dir=tmp_path / "memory")
    flusher = MidTermFlusher(
        session_repository=repo,
        memory_store=store,
        model_client=_ValidSummaryModel(),
    )

    base = datetime(2026, 4, 30, 8, 0, tzinfo=UTC)
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_001",
        event_type="run_started",
        payload={"max_tool_rounds": 3},
        created_at=base,
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_002",
        event_type="user_message",
        payload={"content": "请记住我的偏好"},
        created_at=base + timedelta(seconds=1),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_003",
        event_type="tool_call",
        payload={"name": "memory_search", "arguments": {"query": "偏好"}, "tool_call_id": "call_001"},
        created_at=base + timedelta(seconds=2),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_004",
        event_type="tool_result",
        payload={"tool_name": "memory_search", "success": True, "content": "[]", "tool_call_id": "call_001"},
        created_at=base + timedelta(seconds=3),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_005",
        event_type="assistant_message",
        payload={"content": "我会按你的偏好执行。"},
        created_at=base + timedelta(seconds=4),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_006",
        event_type="run_finished",
        payload={"answer_length": 10, "tool_calls": 1},
        created_at=base + timedelta(seconds=5),
    )

    result = flusher.flush_for_run_finished(_context(session_id))
    assert result.flushed is True
    assert result.reason == "succeeded"
    assert result.job_status == "succeeded"
    assert result.daily_path is not None
    metrics = flusher.collect_job_metrics()
    assert metrics.total_jobs >= 1
    assert metrics.succeeded_jobs >= 1
    assert metrics.retry_jobs == 0
    assert metrics.deferred_jobs == 0

    content = Path(result.daily_path).read_text(encoding="utf-8")
    assert "### Progress" in content
    assert "[CALL] memory_search 查询用户偏好" in content
    assert "| [RESULT] success=True 返回检索结果" in content
    assert "### Candidate Long-Term Memories" in content

    facts_path = tmp_path / "memory" / "agents" / "agent_main" / "facts.jsonl"
    rows = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(row.get("content") == "用户偏好被长期记住" for row in rows)
    matched = [row for row in rows if row.get("content") == "用户偏好被长期记住"]
    assert matched
    latest = matched[-1]
    assert latest.get("scope") == "agent"
    source = latest.get("source")
    assert isinstance(source, dict)
    assert source.get("type") == "mid_term_flush"
    assert source.get("sessionId") == session_id
    tags = latest.get("tags")
    assert isinstance(tags, list)
    assert "long_term" in tags
    assert "mid_term_flush_candidate" in tags
    metadata = latest.get("metadata")
    assert isinstance(metadata, dict)
    assert metadata.get("origin") == "mid_term_flush"
    assert metadata.get("flush_job_id") == result.job_id


def test_mid_term_flusher_does_not_resurrect_archived_canonical_name_candidate(tmp_path: Path) -> None:
    session_id = "sess_mid_term_name_conflict"
    repo = JsonlSessionRepository(data_dir=tmp_path)
    repo.create_session(session_id)
    store = FileMemoryStore(root_dir=tmp_path / "memory")
    manager = MemoryManager(
        capability_registry=AgentCapabilityRegistry.for_tests(),
        memory_store=store,
    )
    old_content = "用户希望我叫小猪。我应该记住这个名字。"
    new_content = "用户希望我叫小明。我应该记住这个名字。"
    manager.write_memory(
        content=old_content,
        tags=["preference", "long_term"],
        context=_context(session_id),
        source_event_id="evt_old_name",
    )
    manager.write_memory(
        content=new_content,
        tags=["preference", "long_term"],
        context=_context(session_id),
        source_event_id="evt_new_name",
    )
    flusher = MidTermFlusher(
        session_repository=repo,
        memory_store=store,
        model_client=_OldNameCandidateModel(old_content),
    )

    base = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_n01",
        event_type="user_message",
        payload={"content": "以后你叫小猪，记住这个名字。"},
        created_at=base,
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_n02",
        event_type="tool_call",
        payload={"name": "memory_write", "arguments": {"content": old_content}, "tool_call_id": "call_name"},
        created_at=base + timedelta(seconds=1),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_n03",
        event_type="tool_result",
        payload={"tool_name": "memory_write", "success": True, "content": "ok", "tool_call_id": "call_name"},
        created_at=base + timedelta(seconds=2),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_n04",
        event_type="assistant_message",
        payload={"content": "已记住。"},
        created_at=base + timedelta(seconds=3),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_n05",
        event_type="run_finished",
        payload={"answer_length": 4, "tool_calls": 1},
        created_at=base + timedelta(seconds=4),
    )

    result = flusher.flush_for_run_finished(_context(session_id))

    assert result.flushed is True
    facts_path = tmp_path / "memory" / "agents" / "agent_main" / "facts.jsonl"
    rows = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    active_old = [row for row in rows if row.get("content") == old_content and row.get("status") == "active"]
    active_new = [row for row in rows if row.get("content") == new_content and row.get("status") == "active"]
    archived_old = [row for row in rows if row.get("content") == old_content and row.get("status") == "archived"]

    assert active_old == []
    assert len(active_new) == 1
    assert len(archived_old) == 1


def test_mid_term_flusher_cursor_skips_duplicate_flush(tmp_path: Path) -> None:
    session_id = "sess_mid_term_cursor"
    repo = JsonlSessionRepository(data_dir=tmp_path)
    repo.create_session(session_id)
    store = FileMemoryStore(root_dir=tmp_path / "memory")
    flusher = MidTermFlusher(
        session_repository=repo,
        memory_store=store,
        model_client=_ValidSummaryModel(),
    )

    base = datetime(2026, 4, 30, 9, 0, tzinfo=UTC)
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_a01",
        event_type="run_started",
        payload={"max_tool_rounds": 2},
        created_at=base,
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_a02",
        event_type="user_message",
        payload={"content": "继续任务"},
        created_at=base + timedelta(seconds=1),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_a03",
        event_type="assistant_message",
        payload={"content": "好的，继续。"},
        created_at=base + timedelta(seconds=2),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_a04",
        event_type="run_finished",
        payload={"answer_length": 6, "tool_calls": 0},
        created_at=base + timedelta(seconds=3),
    )

    first = flusher.flush_for_run_finished(_context(session_id))
    assert first.flushed is True
    assert first.daily_path is not None
    before = Path(first.daily_path).read_text(encoding="utf-8")

    second = flusher.flush_for_run_finished(_context(session_id))
    assert second.flushed is False
    assert second.reason == "no_new_events"
    after = Path(first.daily_path).read_text(encoding="utf-8")
    assert before == after


def test_mid_term_flusher_model_failure_enters_retry_without_cursor_commit(tmp_path: Path) -> None:
    session_id = "sess_mid_term_retry"
    repo = JsonlSessionRepository(data_dir=tmp_path)
    repo.create_session(session_id)
    store = FileMemoryStore(root_dir=tmp_path / "memory")
    flusher = MidTermFlusher(
        session_repository=repo,
        memory_store=store,
        model_client=_InvalidSummaryModel(),
    )

    base = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_r01",
        event_type="user_message",
        payload={"content": "记录一下"},
        created_at=base,
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_r02",
        event_type="assistant_message",
        payload={"content": "收到"},
        created_at=base + timedelta(seconds=1),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_r03",
        event_type="assistant_message",
        payload={"content": "继续处理中"},
        created_at=base + timedelta(seconds=2),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_r04",
        event_type="run_finished",
        payload={"answer_length": 4, "tool_calls": 0},
        created_at=base + timedelta(seconds=3),
    )

    result = flusher.flush_for_run_finished(_context(session_id))
    assert result.flushed is False
    assert result.reason == "retry"
    assert result.job_status == "retry"
    assert result.retry_count == 1
    assert result.last_event_id == "evt_r04"
    metrics = flusher.collect_job_metrics()
    assert metrics.total_jobs == 1
    assert metrics.retry_jobs == 1
    assert metrics.succeeded_jobs == 0

    cursor_path = (
        store.root_dir
        / "agents"
        / "agent_main"
        / "mid_term"
        / "flush_cursors"
        / f"{session_id}.json"
    )
    assert cursor_path.exists() is False


def test_mid_term_flusher_rejects_progress_with_unpaired_tool_evidence(tmp_path: Path) -> None:
    session_id = "sess_mid_term_unpaired_tool"
    repo = JsonlSessionRepository(data_dir=tmp_path)
    repo.create_session(session_id)
    store = FileMemoryStore(root_dir=tmp_path / "memory")
    payload = _empty_summary_payload()
    payload["progress"] = [
        {
            "tool_name": "memory_search",
            "call_summary": "查询用户名字",
            "result_summary": "缺少结果 evidence",
            "success": True,
            "evidence_event_ids": ["evt_t02"],
        }
    ]
    flusher = MidTermFlusher(
        session_repository=repo,
        memory_store=store,
        model_client=_StaticSummaryModel(payload),
    )

    base = datetime(2026, 4, 30, 10, 30, tzinfo=UTC)
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_t01",
        event_type="user_message",
        payload={"content": "查一下我的名字。"},
        created_at=base,
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_t02",
        event_type="tool_call",
        payload={"name": "memory_search", "arguments": {"query": "名字"}, "tool_call_id": "call_name"},
        created_at=base + timedelta(seconds=1),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_t03",
        event_type="tool_result",
        payload={"tool_name": "memory_search", "success": True, "content": "名字是小明", "tool_call_id": "call_name"},
        created_at=base + timedelta(seconds=2),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_t04",
        event_type="run_finished",
        payload={"answer_length": 10, "tool_calls": 1},
        created_at=base + timedelta(seconds=3),
    )

    result = flusher.flush_for_run_finished(_context(session_id))

    assert result.flushed is False
    assert result.job_status == "retry"
    assert result.daily_path is not None
    assert Path(result.daily_path).exists() is False


def test_mid_term_flusher_rejects_forbidden_long_term_candidate(tmp_path: Path) -> None:
    session_id = "sess_mid_term_forbidden_candidate"
    repo = JsonlSessionRepository(data_dir=tmp_path)
    repo.create_session(session_id)
    store = FileMemoryStore(root_dir=tmp_path / "memory")
    payload = _empty_summary_payload()
    payload["candidate_long_term"] = [
        {
            "content": "临时暗号是蓝鲸。",
            "tags": ["preference", "long_term"],
            "confidence": 0.9,
            "why_reusable": "用户提到暗号",
            "evidence_event_ids": ["evt_f01"],
        }
    ]
    flusher = MidTermFlusher(
        session_repository=repo,
        memory_store=store,
        model_client=_StaticSummaryModel(payload),
    )

    base = datetime(2026, 4, 30, 10, 45, tzinfo=UTC)
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_f01",
        event_type="user_message",
        payload={"content": "临时暗号是蓝鲸，只用于这次调试，不要记住。"},
        created_at=base,
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_f02",
        event_type="assistant_message",
        payload={"content": "知道了，不会写入长期记忆。"},
        created_at=base + timedelta(seconds=1),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_f03",
        event_type="assistant_message",
        payload={"content": "这只是临时上下文。"},
        created_at=base + timedelta(seconds=2),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_f04",
        event_type="run_finished",
        payload={"answer_length": 16, "tool_calls": 0},
        created_at=base + timedelta(seconds=3),
    )

    result = flusher.flush_for_run_finished(_context(session_id))

    assert result.flushed is False
    assert result.job_status == "retry"
    assert result.daily_path is not None
    assert Path(result.daily_path).exists() is False
    facts_path = store.root_dir / "agents" / "agent_main" / "facts.jsonl"
    assert facts_path.exists() is False


def test_mid_term_flusher_rejects_outdated_name_candidate_in_same_pack(tmp_path: Path) -> None:
    session_id = "sess_mid_term_outdated_name"
    repo = JsonlSessionRepository(data_dir=tmp_path)
    repo.create_session(session_id)
    store = FileMemoryStore(root_dir=tmp_path / "memory")
    payload = _empty_summary_payload()
    payload["candidate_long_term"] = [
        {
            "content": "用户最新名字是小猪。",
            "tags": ["preference", "long_term"],
            "confidence": 0.9,
            "why_reusable": "用户提到名字",
            "evidence_event_ids": ["evt_o01"],
        }
    ]
    flusher = MidTermFlusher(
        session_repository=repo,
        memory_store=store,
        model_client=_StaticSummaryModel(payload),
    )

    base = datetime(2026, 4, 30, 11, 15, tzinfo=UTC)
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_o01",
        event_type="user_message",
        payload={"content": "先记一下，名字叫小猪。"},
        created_at=base,
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_o02",
        event_type="user_message",
        payload={"content": "最终确认：以后叫我小王，小猪不是最新名字。"},
        created_at=base + timedelta(seconds=1),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_o03",
        event_type="assistant_message",
        payload={"content": "已按最新名字小王处理。"},
        created_at=base + timedelta(seconds=2),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_o04",
        event_type="run_finished",
        payload={"answer_length": 12, "tool_calls": 0},
        created_at=base + timedelta(seconds=3),
    )

    result = flusher.flush_for_run_finished(_context(session_id))

    assert result.flushed is False
    assert result.job_status == "retry"
    assert result.daily_path is not None
    assert Path(result.daily_path).exists() is False


def test_mid_term_flusher_repairs_latest_name_candidate_assistant_only_evidence(tmp_path: Path) -> None:
    session_id = "sess_mid_term_latest_name_evidence_repair"
    repo = JsonlSessionRepository(data_dir=tmp_path)
    repo.create_session(session_id)
    store = FileMemoryStore(root_dir=tmp_path / "memory")
    payload = _empty_summary_payload()
    payload["candidate_long_term"] = [
        {
            "content": "用户最新名字是小王。",
            "tags": ["preference", "long_term"],
            "confidence": 0.9,
            "why_reusable": "用户明确纠正名字，后续跨会话可复用。",
            "evidence_event_ids": ["evt_r03"],
        }
    ]
    flusher = MidTermFlusher(
        session_repository=repo,
        memory_store=store,
        model_client=_StaticSummaryModel(payload),
    )

    base = datetime(2026, 4, 30, 11, 30, tzinfo=UTC)
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_r01",
        event_type="user_message",
        payload={"content": "先记一下，名字叫小猪。"},
        created_at=base,
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_r02",
        event_type="user_message",
        payload={"content": "最终确认：以后叫我小王，小猪不是最新名字。"},
        created_at=base + timedelta(seconds=1),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_r03",
        event_type="assistant_message",
        payload={"content": "后续应以小王作为用户最新名字。"},
        created_at=base + timedelta(seconds=2),
    )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_r04",
        event_type="run_finished",
        payload={"answer_length": 12, "tool_calls": 0},
        created_at=base + timedelta(seconds=3),
    )

    result = flusher.flush_for_run_finished(_context(session_id))

    assert result.flushed is True
    facts_path = store.root_dir / "agents" / "agent_main" / "facts.jsonl"
    rows = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    matched = [row for row in rows if row.get("content") == "用户最新名字是小王。"]
    assert len(matched) == 1
    source = matched[0].get("source")
    assert isinstance(source, dict)
    assert source.get("eventIds") == ["evt_r02"]
    metadata = matched[0].get("metadata")
    assert isinstance(metadata, dict)
    assert metadata.get("evidence_event_ids") == "evt_r02,evt_r03"


def test_mid_term_flusher_keeps_one_atomic_job_and_tool_pairs(tmp_path: Path) -> None:
    session_id = "sess_mid_term_budget"
    repo = JsonlSessionRepository(data_dir=tmp_path)
    repo.create_session(session_id)
    store = FileMemoryStore(root_dir=tmp_path / "memory")
    model = _CapturingSummaryModel()
    flusher = MidTermFlusher(
        session_repository=repo,
        memory_store=store,
        model_client=model,
        model_context_window_tokens=2048,
        model_input_ratio=0.2,
        model_output_reserve_tokens=700,
        prompt_overhead_tokens=500,
    )

    base = datetime(2026, 4, 30, 11, 0, tzinfo=UTC)
    all_event_ids: list[str] = []
    for idx in range(1, 7):
        suffix = f"{idx:03d}"
        user_id = f"evt_b{suffix}u"
        call_id = f"evt_b{suffix}c"
        result_id = f"evt_b{suffix}r"
        assistant_id = f"evt_b{suffix}a"
        all_event_ids.extend([user_id, call_id, result_id, assistant_id])
        _append_event(
            repo,
            session_id=session_id,
            event_id=user_id,
            event_type="user_message",
            payload={"content": f"用户输入 {idx} " + ("需求描述" * 80)},
            created_at=base + timedelta(seconds=idx * 4),
        )
        _append_event(
            repo,
            session_id=session_id,
            event_id=call_id,
            event_type="tool_call",
            payload={
                "name": "memory_search",
                "arguments": {"query": f"需求{idx}", "limit": 5},
                "tool_call_id": f"call_{idx}",
            },
            created_at=base + timedelta(seconds=idx * 4 + 1),
        )
        _append_event(
            repo,
            session_id=session_id,
            event_id=result_id,
            event_type="tool_result",
            payload={
                "tool_name": "memory_search",
                "success": True,
                "content": f"result_{idx} " + ("命中信息" * 60),
                "tool_call_id": f"call_{idx}",
            },
            created_at=base + timedelta(seconds=idx * 4 + 2),
        )
        _append_event(
            repo,
            session_id=session_id,
            event_id=assistant_id,
            event_type="assistant_message",
            payload={"content": f"助手反馈 {idx} " + ("执行说明" * 70)},
            created_at=base + timedelta(seconds=idx * 4 + 3),
        )

    finish_id = "evt_b999f"
    all_event_ids.append(finish_id)
    _append_event(
        repo,
        session_id=session_id,
        event_id=finish_id,
        event_type="run_finished",
        payload={"answer_length": 120, "tool_calls": 6},
        created_at=base + timedelta(seconds=999),
    )

    result = flusher.flush_for_run_finished(_context(session_id))
    assert result.flushed is True
    assert len(model.captured_packs) == 1

    captured_event_ids: set[str] = set()
    for pack in model.captured_packs:
        events = _event_index_from_pack(pack)
        for event in events:
            event_id = str(event.get("event_id", "")).strip()
            if event_id:
                captured_event_ids.add(event_id)
        semantic_units = [item for item in pack.get("semantic_units", []) if isinstance(item, dict)]
        for unit in semantic_units:
            assert "events" not in unit
            if str(unit.get("unit_type", "")) != "tool_pair":
                continue
            event_ids = [str(item).strip() for item in unit.get("event_ids", []) if str(item).strip()]
            assert len(event_ids) == 2
            type_by_id = {
                str(item.get("event_id", "")).strip(): str(item.get("type", "")).strip()
                for item in events
                if isinstance(item, dict)
            }
            assert type_by_id.get(event_ids[0]) == "tool_call"
            assert type_by_id.get(event_ids[1]) == "tool_result"

    assert set(all_event_ids) == captured_event_ids


def test_mid_term_flusher_caps_model_input_budget(tmp_path: Path) -> None:
    session_id = "sess_mid_term_budget_cap"
    repo = JsonlSessionRepository(data_dir=tmp_path)
    repo.create_session(session_id)
    store = FileMemoryStore(root_dir=tmp_path / "memory")
    model = _CapturingSummaryModel()
    flusher = MidTermFlusher(
        session_repository=repo,
        memory_store=store,
        model_client=model,
        model_context_window_tokens=32768,
        model_input_ratio=0.8,
        model_output_reserve_tokens=700,
        prompt_overhead_tokens=500,
        max_input_tokens=1536,
    )

    base = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)
    for idx in range(1, 11):
        _append_event(
            repo,
            session_id=session_id,
            event_id=f"evt_cap_{idx:03d}",
            event_type="user_message",
            payload={"content": f"用户消息 {idx} " + ("需要压缩的上下文" * 20)},
            created_at=base + timedelta(seconds=idx),
        )
    _append_event(
        repo,
        session_id=session_id,
        event_id="evt_cap_finished",
        event_type="run_finished",
        payload={"answer_length": 80, "tool_calls": 0},
        created_at=base + timedelta(seconds=99),
    )

    result = flusher.flush_for_run_finished(_context(session_id))

    assert result.flushed is True
    assert model.captured_packs
    assert {pack.get("budget", {}).get("input_budget_tokens") for pack in model.captured_packs} == {1536}


def test_mid_term_flusher_retries_active_range_before_new_dirty_events(tmp_path: Path) -> None:
    session_id = "sess_mid_term_dirty_retry"
    repo = JsonlSessionRepository(data_dir=tmp_path)
    repo.create_session(session_id)
    store = FileMemoryStore(root_dir=tmp_path / "memory")
    failing = MidTermFlusher(
        session_repository=repo,
        memory_store=store,
        model_client=_InvalidSummaryModel(),
    )

    base = datetime(2026, 4, 30, 13, 0, tzinfo=UTC)
    for idx, event_type in enumerate(["user_message", "assistant_message", "user_message", "run_finished"], start=1):
        _append_event(
            repo,
            session_id=session_id,
            event_id=f"evt_d{idx:02d}",
            event_type=event_type,
            payload={"content": f"旧范围事件 {idx}"} if event_type != "run_finished" else {"answer_length": 10},
            created_at=base + timedelta(seconds=idx),
        )

    first = failing.flush_for_run_finished(_context(session_id))
    assert first.flushed is False
    assert first.reason == "retry"
    jobs_root = store.root_dir / "agents" / "agent_main" / "mid_term" / "flush_jobs" / session_id
    retry_job_path = next(jobs_root.glob("*.json"))
    retry_payload = json.loads(retry_job_path.read_text(encoding="utf-8"))
    retry_payload["next_attempt_at"] = "2026-04-30T13:00:00Z"
    retry_job_path.write_text(json.dumps(retry_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for idx in range(5, 16):
        _append_event(
            repo,
            session_id=session_id,
            event_id=f"evt_d{idx:02d}",
            event_type="user_message" if idx < 15 else "run_finished",
            payload={"content": f"新范围事件 {idx}"} if idx < 15 else {"answer_length": 20},
            created_at=base + timedelta(seconds=idx),
        )

    retrying = MidTermFlusher(
        session_repository=repo,
        memory_store=store,
        model_client=_ValidSummaryModel(),
    )
    retried = retrying.flush_for_run_finished(_context(session_id))

    assert retried.flushed is False
    assert retried.reason == "active_job_exists"

    rows = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(jobs_root.glob("*.json"))]
    succeeded = [row for row in rows if row["status"] == "succeeded"]
    pending = [row for row in rows if row["status"] == "pending"]
    assert len(succeeded) == 1
    assert len(pending) == 1
    assert succeeded[0]["event_pack"]["first_event_id"] == "evt_d01"
    assert succeeded[0]["event_pack"]["last_event_id"] == "evt_d04"
    assert pending[0]["event_pack"]["first_event_id"] == "evt_d05"
    assert pending[0]["event_pack"]["last_event_id"] == "evt_d15"

    cursor_path = store.root_dir / "agents" / "agent_main" / "mid_term" / "flush_cursors" / f"{session_id}.json"
    cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
    assert cursor["last_event_id"] == "evt_d04"
