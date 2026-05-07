"""Tests for memory manager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.domain.models import RunContext
from app.memory.models import MemoryScope
from app.memory.file_store import FileMemoryStore
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
                allowed_skills=["*"],
                default_skills=["base"],
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


def _manager(
    tmp_path: Path,
    *,
    capability_registry: AgentCapabilityRegistry | None = None,
) -> MemoryManager:
    return MemoryManager(
        capability_registry=capability_registry or _capability_registry(),
        memory_store=FileMemoryStore(root_dir=tmp_path / "memory"),
    )


def test_memory_manager_write_and_search(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

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


def test_memory_manager_write_persists_fact(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    manager.write_memory(
        content="Remember deployment checklist",
        tags=["plan", "long_term"],
        context=_context("sess_1"),
        source_event_id="evt_2",
    )

    _, _, bundle = manager.search_bundle(
        query="deployment",
        limit=5,
        context=_context("sess_1"),
    )
    assert len(bundle.items) == 1
    assert bundle.items[0].scope.value == "agent_long"


def test_memory_manager_write_skips_exact_duplicate_fact(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    context = _context("sess_duplicate_write")

    first = manager.write_memory_with_result(
        content="上下文压缩链路调试重点：tool call/result 不能被切开。",
        tags=["constraint", "long_term"],
        context=context,
        source_event_id="evt_dup_1",
    )
    second = manager.write_memory_with_result(
        content="上下文压缩链路调试重点：tool call/result 不能被切开。",
        tags=["constraint", "long_term"],
        context=context,
        source_event_id="evt_dup_2",
    )

    assert first.written_records == 1
    assert second.written_records == 0
    assert second.memory.memory_id == first.memory.memory_id
    hits = manager.search(query="tool call/result", limit=10, context=context)
    assert [item.content for item in hits].count("上下文压缩链路调试重点：tool call/result 不能被切开。") == 1


def test_memory_manager_write_refreshes_agent_long_term_summary(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    manager.write_memory(
        content="用户希望我叫李华。",
        tags=["preference", "long_term"],
        context=_context("sess_summary_1"),
        source_event_id="evt_summary_1",
    )

    payload = (tmp_path / "memory" / "agents" / "agent_main" / "long_term_overlay.json").read_text(encoding="utf-8")
    long_term = json.loads(payload)
    summary = str(long_term["user"]["personalContext"]["summary"])
    assert "李华" in summary


def test_memory_manager_write_without_tags_defaults_to_agent_private_short_hint(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    manager.write_memory(
        content="Keep answers concise",
        tags=[],
        context=_context("sess_1"),
        source_event_id="evt_3",
    )

    _, _, bundle = manager.search_bundle(
        query="concise",
        limit=5,
        context=_context("sess_1"),
    )
    assert len(bundle.items) == 1
    assert bundle.items[0].scope.value == "agent_short"


def test_memory_manager_search_recalls_chinese_long_memory_by_question_form(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

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
    manager = _manager(tmp_path)

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
    assert any(item.content == '以后叫我"李华"' for item in hits)


def test_memory_manager_search_recalls_relevant_text_match(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

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
    assert any(item.content == "用户称呼是李华" for item in hits)


def test_memory_manager_write_respects_scope_permission(tmp_path: Path) -> None:
    manager = _manager(
        tmp_path,
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
    manager = _manager(
        tmp_path,
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
    manager = _manager(tmp_path)

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

    assert any(item.content == "用户长期偏好：回答简洁直接" for item in hits)
    assert all("提到 state 这个词即可" not in item.content for item in hits)
    assert "agent_short" not in summary["searched_scopes"]


def test_memory_manager_context_lanes_include_response_preferences_without_text_match(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    manager.write_memory(
        content="以后回答简洁一点",
        tags=["preference", "long_term"],
        context=_context("sess_lane_response"),
        source_event_id="evt_lane_response",
    )

    lanes, summary = manager.search_context_memory_lanes(
        query="帮我检查接口实现",
        limit=5,
        context=_context("sess_lane_response"),
    )

    assert "response_preferences" in lanes
    assert lanes["response_preferences"][0].content == "以后回答简洁一点"
    assert summary["lanes"]["response_preferences"] == 1


def test_memory_manager_rejects_obvious_working_state_write(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    with pytest.raises(ValidationError) as exc_info:
        manager.write_memory(
            content="下一步：先补 state_set 测试",
            tags=[],
            context=_context("sess_reject_state"),
            source_event_id="evt_reject_state",
        )

    assert "state_set" in str(exc_info.value)


def test_memory_manager_rejects_raw_json_blob_write(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    with pytest.raises(ValidationError) as exc_info:
        manager.write_memory(
            content='{"steps": ["a", "b"], "status": "ok"}',
            tags=[],
            context=_context("sess_reject_blob"),
            source_event_id="evt_reject_blob",
        )

    assert "raw file/tool output" in str(exc_info.value)


def test_memory_manager_write_persists_structured_classification_metadata(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    manager.write_memory(
        content='以后叫我"李华"',
        tags=["preference", "long_term"],
        context=_context("sess_classified"),
        source_event_id="evt_classified",
    )

    _, _, bundle = manager.search_bundle(
        query="李华",
        limit=5,
        context=_context("sess_classified"),
    )

    assert len(bundle.items) == 1
    item = bundle.items[0]
    assert item.kind == "user_preference"
    assert item.source_kind == "explicit_user"
    assert item.canonical_key == "preferred_name"
    assert item.normalized_value == "李华"
    assert item.subject_kind == "user"
    assert item.classification_version == "v1"
    assert item.metadata["source"] == "memory_manager"
    assert item.metadata["memory_scope"] == "agent_long"


def test_memory_manager_replaces_active_preferred_name_by_canonical_key(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    old = manager.write_memory(
        content="用户希望我叫小猪。我应该记住这个名字。",
        tags=["preference", "long_term"],
        context=_context("sess_name_replace"),
        source_event_id="evt_name_old",
    )
    new = manager.write_memory(
        content="用户希望我叫小明。我应该记住这个名字。",
        tags=["preference", "long_term"],
        context=_context("sess_name_replace"),
        source_event_id="evt_name_new",
    )

    assert old.metadata["canonical_key"] == "preferred_name"
    assert old.metadata["normalized_value"] == "小猪"
    assert new.metadata["canonical_key"] == "preferred_name"
    assert new.metadata["normalized_value"] == "小明"

    facts_path = tmp_path / "memory" / "agents" / "agent_main" / "facts.jsonl"
    rows = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    old_rows = [row for row in rows if row.get("content") == "用户希望我叫小猪。我应该记住这个名字。"]
    new_rows = [row for row in rows if row.get("content") == "用户希望我叫小明。我应该记住这个名字。"]

    assert old_rows[-1]["status"] == "archived"
    assert old_rows[-1]["metadata"]["archivedReason"] == "canonical_replace:preferred_name"
    assert new_rows[-1]["status"] == "active"

    hits = manager.search(query="你的名字叫什么", limit=5, context=_context("sess_name_replace_later"))
    contents = [item.content for item in hits]
    assert "用户希望我叫小明。我应该记住这个名字。" in contents
    assert "用户希望我叫小猪。我应该记住这个名字。" not in contents


def test_memory_manager_resolve_update_targets_uses_text_search(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

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

    assert match_strategy == "text_search"
    assert len(hits) >= 1
    assert any(item.content == "用户称呼是李华" for item in hits)
