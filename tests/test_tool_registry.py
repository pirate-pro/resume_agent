"""Tests for tool registry and builtin tool safety."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.errors import ToolExecutionError, ValidationError
from app.domain.models import RunContext, SessionFile, ToolCall
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.memory.facade import FileMemoryFacade
from app.memory.models import MemoryReadRequest, MemoryRecord, MemoryScope, MemoryStatus, MemoryType
from app.memory.policies import default_memory_policy
from app.memory.stores.jsonl_file_store import JsonlFileMemoryStore
from app.runtime.agent_capability import AgentCapability, AgentCapabilityRegistry
from app.runtime.memory_manager import MemoryManager
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.tools.builtins import (
    MemoryForgetTool,
    MemorySearchTool,
    MemoryUpdateTool,
    MemoryWriteTool,
    SessionListFilesTool,
    SessionPlanFileAccessTool,
    SessionReadFileTool,
    SessionSearchFileTool,
    StateListTool,
    StatePublishTool,
    StateSetTool,
    WorkspaceReadFileTool,
    WorkspaceWriteFileTool,
)
from app.tools.registry import ToolRegistry

__all__ = []


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


def _capability_registry() -> AgentCapabilityRegistry:
    return AgentCapabilityRegistry.for_tests()


def _registry(
    capability_registry: AgentCapabilityRegistry | None = None,
) -> ToolRegistry:
    resolved = capability_registry if capability_registry is not None else _capability_registry()
    return ToolRegistry(capability_registry=resolved)


def _memory_manager(
    memory_facade: FileMemoryFacade,
    capability_registry: AgentCapabilityRegistry | None = None,
) -> MemoryManager:
    resolved = capability_registry if capability_registry is not None else _capability_registry()
    return MemoryManager(memory_facade=memory_facade, capability_registry=resolved)


def _state_manager(tmp_path: Path) -> StateManager:
    return StateManager(store=JsonlFileStateStore(root_dir=tmp_path / "state_v1"))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
    return rows



def test_tool_register_success_and_duplicate_error(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    memory_manager = _memory_manager(memory_facade)
    registry = _registry()

    registry.register(MemoryWriteTool(memory_manager=memory_manager))

    assert len(registry.list_definitions()) == 1

    with pytest.raises(ValidationError):
        registry.register(MemoryWriteTool(memory_manager=memory_manager))


def test_memory_write_tool_writes_v2_memory(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    memory_manager = _memory_manager(memory_facade)

    registry = _registry()
    registry.register(MemoryWriteTool(memory_manager=memory_manager))

    result = registry.execute(
        ToolCall(name="memory_write", arguments={"content": "Use markdown format", "tags": ["preference"]}),
        context=_context("sess_1"),
    )

    assert result.success is True
    bundle = memory_facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_1",
            query="markdown",
            limit=5,
            token_budget=1200,
        )
    )
    assert len(bundle.items) == 1
    assert bundle.items[0].scope.value == "agent_long"


def test_memory_write_tool_without_tags_defaults_to_short_and_is_agent_scoped(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    memory_manager = _memory_manager(memory_facade)

    registry = _registry()
    registry.register(MemoryWriteTool(memory_manager=memory_manager))
    registry.register(MemorySearchTool(memory_manager=memory_manager))

    write_result = registry.execute(
        ToolCall(name="memory_write", arguments={"content": "User likes concise replies"}),
        context=_context("sess_1"),
    )
    same_session_result = registry.execute(
        ToolCall(name="memory_search", arguments={"query": "concise", "limit": 5}),
        context=_context("sess_1"),
    )
    other_session_result = registry.execute(
        ToolCall(name="memory_search", arguments={"query": "concise", "limit": 5}),
        context=_context("sess_2"),
    )

    assert write_result.success is True
    assert same_session_result.success is True
    same_payload = json.loads(same_session_result.content)
    assert len(same_payload) >= 1
    assert same_payload[0]["scope"] == "agent_short"

    assert other_session_result.success is True
    other_payload = json.loads(other_session_result.content)
    assert len(other_payload) >= 1
    assert other_payload[0]["scope"] == "agent_short"


def test_memory_search_tool_isolated_by_agent_id(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    memory_manager = _memory_manager(memory_facade)

    main_registry = _registry()
    main_registry.register(MemoryWriteTool(memory_manager=memory_manager))
    main_registry.register(MemorySearchTool(memory_manager=memory_manager))

    other_registry = _registry()
    other_registry.register(MemorySearchTool(memory_manager=memory_manager))

    write_result = main_registry.execute(
        ToolCall(name="memory_write", arguments={"content": "用户明天要多喝水"}),
        context=_context("sess_1", agent_id="agent_main"),
    )
    main_search_result = main_registry.execute(
        ToolCall(name="memory_search", arguments={"query": "多喝水", "limit": 5}),
        context=_context("sess_2", agent_id="agent_main"),
    )
    other_search_result = other_registry.execute(
        ToolCall(name="memory_search", arguments={"query": "多喝水", "limit": 5}),
        context=_context("sess_2", agent_id="agent_other"),
    )

    assert write_result.success is True
    assert main_search_result.success is True
    assert len(json.loads(main_search_result.content)) >= 1
    assert other_search_result.success is True
    assert json.loads(other_search_result.content) == []


def test_memory_write_tool_rejects_working_state_and_points_to_state_set(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    memory_manager = _memory_manager(memory_facade)

    registry = _registry()
    registry.register(MemoryWriteTool(memory_manager=memory_manager))

    with pytest.raises(ToolExecutionError) as exc_info:
        registry.execute(
            ToolCall(name="memory_write", arguments={"content": "当前目标：先整理 session working state"}),
            context=_context("sess_reject_tool"),
        )

    message = str(exc_info.value)
    assert "state_set" in message


def test_memory_forget_tool_forgets_target_memory(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    memory_manager = _memory_manager(memory_facade)

    registry = _registry()
    registry.register(MemoryWriteTool(memory_manager=memory_manager))
    registry.register(MemorySearchTool(memory_manager=memory_manager))
    registry.register(MemoryForgetTool(memory_manager=memory_manager))

    registry.execute(
        ToolCall(
            name="memory_write",
            arguments={"content": "用户偏好：回答简洁", "tags": ["preference", "long_term"]},
        ),
        context=_context("sess_forget_1"),
    )
    forget_result = registry.execute(
        ToolCall(
            name="memory_forget",
            arguments={"query": "回答简洁", "limit": 5},
        ),
        context=_context("sess_forget_1"),
    )
    search_after = registry.execute(
        ToolCall(name="memory_search", arguments={"query": "回答简洁", "limit": 5}),
        context=_context("sess_forget_2"),
    )

    forget_payload = json.loads(forget_result.content)
    assert forget_result.success is True
    assert forget_payload["matched"] >= 1
    assert forget_payload["forgotten"] >= 1
    assert json.loads(search_after.content) == []


def test_memory_update_tool_replaces_single_match(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    memory_manager = _memory_manager(memory_facade)

    registry = _registry()
    registry.register(MemoryWriteTool(memory_manager=memory_manager))
    registry.register(MemorySearchTool(memory_manager=memory_manager))
    registry.register(MemoryUpdateTool(memory_manager=memory_manager))

    registry.execute(
        ToolCall(
            name="memory_write",
            arguments={"content": "用户称呼是李华", "tags": ["preference", "long_term"]},
        ),
        context=_context("sess_update_1"),
    )
    update_result = registry.execute(
        ToolCall(
            name="memory_update",
            arguments={
                "query": "用户称呼是李华",
                "new_content": "用户称呼改为小李",
                "new_tags": ["preference", "long_term"],
                "limit": 3,
            },
        ),
        context=_context("sess_update_1"),
    )
    new_search = registry.execute(
        ToolCall(name="memory_search", arguments={"query": "小李", "limit": 5}),
        context=_context("sess_update_2"),
    )
    old_search = registry.execute(
        ToolCall(name="memory_search", arguments={"query": "李华", "limit": 5}),
        context=_context("sess_update_2"),
    )

    update_payload = json.loads(update_result.content)
    assert update_result.success is True
    assert update_payload["updated"] is True
    assert update_payload["update_mode"] == "canonical_supersede"
    assert len(json.loads(new_search.content)) >= 1
    old_payload = json.loads(old_search.content)
    assert all(item.get("content") != "用户称呼是李华" for item in old_payload)
    rows = _read_jsonl(tmp_path / "memory_v2" / "agents" / "agent_main" / "long.jsonl")
    active_rows = [row for row in rows if row["status"] == "active"]
    archived_rows = [row for row in rows if row["status"] == "archived"]
    assert len(active_rows) == 1
    assert active_rows[0]["metadata"]["normalized_value"] == "小李"
    assert active_rows[0]["parent_memory_id"] == update_payload["old_memory_id"]
    assert len(archived_rows) == 1
    assert archived_rows[0]["metadata"]["superseded_by_normalized_value"] == "小李"


def test_memory_update_tool_returns_ambiguous_when_multi_match(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    memory_manager = _memory_manager(memory_facade)

    registry = _registry()
    registry.register(MemoryWriteTool(memory_manager=memory_manager))
    registry.register(MemoryUpdateTool(memory_manager=memory_manager))

    registry.execute(
        ToolCall(
            name="memory_write",
            arguments={"content": "用户喜欢奶茶", "tags": ["preference", "long_term"]},
        ),
        context=_context("sess_update_3"),
    )
    registry.execute(
        ToolCall(
            name="memory_write",
            arguments={"content": "用户喜欢奶咖", "tags": ["preference", "long_term"]},
        ),
        context=_context("sess_update_3"),
    )

    update_result = registry.execute(
        ToolCall(
            name="memory_update",
            arguments={
                "query": "用户喜欢奶",
                "new_content": "用户喜欢美式",
                "limit": 5,
            },
        ),
        context=_context("sess_update_3"),
    )
    payload = json.loads(update_result.content)
    assert update_result.success is True
    assert payload["updated"] is False
    assert payload["reason"] == "ambiguous_match"
    assert len(payload["candidates"]) >= 2


def test_memory_update_tool_prefers_canonical_exact_before_text_search(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    memory_manager = _memory_manager(memory_facade)

    registry = _registry()
    registry.register(MemoryWriteTool(memory_manager=memory_manager))
    registry.register(MemorySearchTool(memory_manager=memory_manager))
    registry.register(MemoryUpdateTool(memory_manager=memory_manager))

    registry.execute(
        ToolCall(
            name="memory_write",
            arguments={"content": "用户称呼是李华", "tags": ["preference", "long_term"]},
        ),
        context=_context("sess_update_4"),
    )
    registry.execute(
        ToolCall(
            name="memory_write",
            arguments={"content": "用户长期目标是加入李华实验室", "tags": ["long_term"]},
        ),
        context=_context("sess_update_4"),
    )
    ambiguous_search = registry.execute(
        ToolCall(name="memory_search", arguments={"query": "用户称呼是李华", "limit": 5}),
        context=_context("sess_update_4"),
    )

    update_result = registry.execute(
        ToolCall(
            name="memory_update",
            arguments={
                "query": "用户称呼是李华",
                "new_content": "用户称呼改为小李",
                "new_tags": ["preference", "long_term"],
                "limit": 5,
            },
        ),
        context=_context("sess_update_4"),
    )
    new_search = registry.execute(
        ToolCall(name="memory_search", arguments={"query": "小李", "limit": 5}),
        context=_context("sess_update_5"),
    )
    old_search = registry.execute(
        ToolCall(name="memory_search", arguments={"query": "李华", "limit": 5}),
        context=_context("sess_update_5"),
    )

    payload = json.loads(update_result.content)
    ambiguous_payload = json.loads(ambiguous_search.content)
    assert update_result.success is True
    assert len(ambiguous_payload) >= 2
    assert payload["updated"] is True
    assert payload["match_strategy"] == "canonical_exact"
    assert payload["update_mode"] == "canonical_supersede"
    assert len(json.loads(new_search.content)) >= 1
    old_payload = json.loads(old_search.content)
    assert all(item.get("content") != "用户称呼是李华" for item in old_payload)


def test_memory_update_tool_canonical_update_respects_source_priority(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    memory_manager = _memory_manager(memory_facade)

    registry = _registry()
    registry.register(MemoryWriteTool(memory_manager=memory_manager))
    registry.register(MemorySearchTool(memory_manager=memory_manager))
    registry.register(MemoryUpdateTool(memory_manager=memory_manager))

    registry.execute(
        ToolCall(
            name="memory_write",
            arguments={"content": "用户称呼是李华", "tags": ["preference", "long_term", "system_policy"]},
        ),
        context=_context("sess_update_6"),
    )

    update_result = registry.execute(
        ToolCall(
            name="memory_update",
            arguments={
                "query": "用户称呼是李华",
                "new_content": "用户称呼改为小李",
                "new_tags": ["preference", "long_term"],
                "limit": 3,
            },
        ),
        context=_context("sess_update_6"),
    )
    old_search = registry.execute(
        ToolCall(name="memory_search", arguments={"query": "李华", "limit": 5}),
        context=_context("sess_update_7"),
    )
    new_search = registry.execute(
        ToolCall(name="memory_search", arguments={"query": "小李", "limit": 5}),
        context=_context("sess_update_7"),
    )

    payload = json.loads(update_result.content)
    assert update_result.success is True
    assert payload["updated"] is False
    assert payload["reason"] == "source_priority_conflict"
    assert payload["match_strategy"] == "canonical_exact"
    assert payload["update_mode"] == "canonical_direct"
    assert any(item.get("content") == "用户称呼是李华" for item in json.loads(old_search.content))
    assert all(item.get("content") != "用户称呼改为小李" for item in json.loads(new_search.content))


def test_memory_update_tool_backfills_legacy_target_and_uses_canonical_supersede(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    memory_manager = _memory_manager(memory_facade)
    now = datetime.now(UTC)
    memory_store.write_records(
        [
            MemoryRecord(
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
        ]
    )

    registry = _registry()
    registry.register(MemorySearchTool(memory_manager=memory_manager))
    registry.register(MemoryUpdateTool(memory_manager=memory_manager))

    update_result = registry.execute(
        ToolCall(
            name="memory_update",
            arguments={
                "query": "以后叫我李华",
                "new_content": "以后叫我小李",
                "new_tags": ["preference", "long_term"],
                "limit": 3,
            },
        ),
        context=_context("sess_update_legacy"),
    )
    new_search = registry.execute(
        ToolCall(name="memory_search", arguments={"query": "小李", "limit": 5}),
        context=_context("sess_update_legacy"),
    )

    payload = json.loads(update_result.content)
    rows = _read_jsonl(tmp_path / "memory_v2" / "agents" / "agent_main" / "long.jsonl")
    active_rows = [row for row in rows if row["status"] == "active"]
    archived_rows = [row for row in rows if row["status"] == "archived"]
    assert update_result.success is True
    assert payload["updated"] is True
    assert payload["match_strategy"] == "text_search"
    assert payload["update_mode"] == "canonical_supersede"
    assert len(json.loads(new_search.content)) >= 1
    assert len(active_rows) == 1
    assert active_rows[0]["metadata"]["normalized_value"] == "小李"
    assert active_rows[0]["parent_memory_id"] == "mem_legacy_name"
    assert len(archived_rows) == 1
    assert archived_rows[0]["memory_id"] == "mem_legacy_name"
    assert archived_rows[0]["metadata"]["canonical_key"] == "preferred_name"
    assert archived_rows[0]["metadata"]["metadata_refresh_reason"] == "structured_backfill"


def test_state_tools_write_list_and_publish_session_state(tmp_path: Path) -> None:
    state_manager = _state_manager(tmp_path)

    registry = _registry()
    registry.register(StateSetTool(state_manager=state_manager))
    registry.register(StateListTool(state_manager=state_manager))
    registry.register(StatePublishTool(state_manager=state_manager))

    set_result = registry.execute(
        ToolCall(name="state_set", arguments={"key": "current_goal", "value": "完成 state 接线"}),
        context=_context("sess_state_1"),
    )
    publish_result = registry.execute(
        ToolCall(name="state_publish", arguments={"keys": ["current_goal"]}),
        context=_context("sess_state_1"),
    )
    list_result = registry.execute(
        ToolCall(name="state_list", arguments={"scope": "all"}),
        context=_context("sess_state_1"),
    )

    assert set_result.success is True
    assert publish_result.success is True
    payload = json.loads(list_result.content)
    assert payload["scope"] == "all"
    assert len(payload["agent_state"]) == 1
    assert payload["agent_state"][0]["key"] == "current_goal"
    assert payload["agent_state"][0]["value"] == "完成 state 接线"
    assert len(payload["shared_state"]) == 1
    assert payload["shared_state"][0]["key"] == "current_goal"
    assert payload["shared_state"][0]["metadata"]["published_from_agent_id"] == "agent_main"


def test_state_list_tool_keeps_private_state_isolated_by_agent(tmp_path: Path) -> None:
    state_manager = _state_manager(tmp_path)

    writer_registry = _registry()
    writer_registry.register(StateSetTool(state_manager=state_manager))
    writer_registry.execute(
        ToolCall(name="state_set", arguments={"key": "current_goal", "value": "仅主 agent 可见"}),
        context=_context("sess_state_2", agent_id="agent_main"),
    )

    reader_registry = _registry()
    reader_registry.register(StateListTool(state_manager=state_manager))
    result = reader_registry.execute(
        ToolCall(name="state_list", arguments={"scope": "all"}),
        context=_context("sess_state_2", agent_id="agent_other"),
    )

    payload = json.loads(result.content)
    assert payload["agent_state"] == []
    assert payload["shared_state"] == []



def test_execute_missing_tool_raises(tmp_path: Path) -> None:
    _ = tmp_path
    registry = _registry()

    with pytest.raises(ToolExecutionError):
        registry.execute(ToolCall(name="missing", arguments={}), context=_context("sess_1"))



def test_workspace_path_traversal_is_blocked(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_1")

    registry = _registry()
    registry.register(WorkspaceWriteFileTool(session_repository=session_repo))

    with pytest.raises(ToolExecutionError):
        registry.execute(
            ToolCall(name="workspace_write_file", arguments={"path": "../escape.txt", "content": "x"}),
            context=_context("sess_1"),
        )


def test_workspace_read_file_fallback_to_parent_directories(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_2")
    (tmp_path / ".env.example").write_text("HELLO=1", encoding="utf-8")

    registry = _registry()
    registry.register(WorkspaceReadFileTool(session_repository=session_repo))

    result = registry.execute(
        ToolCall(name="workspace_read_file", arguments={"path": ".env.example"}),
        context=_context("sess_2"),
    )

    assert result.success is True
    assert "HELLO=1" in result.content


def test_workspace_read_file_error_contains_workspace(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_3")
    workspace = session_repo.get_workspace_path("sess_3").resolve()

    registry = _registry()
    registry.register(WorkspaceReadFileTool(session_repository=session_repo))

    with pytest.raises(ToolExecutionError) as exc_info:
        registry.execute(
            ToolCall(name="workspace_read_file", arguments={"path": "missing.txt"}),
            context=_context("sess_3"),
        )

    message = str(exc_info.value)
    assert "workspace-first lookup" in message
    assert str(workspace) in message


def test_workspace_read_file_blocks_explicit_parent_segments(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_4")

    registry = _registry()
    registry.register(WorkspaceReadFileTool(session_repository=session_repo))

    with pytest.raises(ToolExecutionError):
        registry.execute(
            ToolCall(name="workspace_read_file", arguments={"path": "../.env"}),
            context=_context("sess_4"),
        )


def test_session_list_files_returns_uploaded_file(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    meta = session_repo.create_session("sess_file_1")
    workspace = session_repo.get_workspace_path("sess_file_1")
    upload_path = workspace / "uploads" / "file_1_notes.txt"
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    upload_path.write_text("alpha beta gamma", encoding="utf-8")
    session_repo.add_or_update_session_file(
        SessionFile(
            file_id="file_1",
            session_id="sess_file_1",
            filename="notes.txt",
            media_type="text/plain",
            size_bytes=16,
            status="uploaded",
            uploaded_at=meta.created_at,
            storage_relpath="workspace/uploads/file_1_notes.txt",
            text_relpath=None,
            error=None,
        )
    )
    session_repo.set_active_file_ids("sess_file_1", ["file_1"])

    registry = _registry()
    registry.register(SessionListFilesTool(session_repository=session_repo))

    result = registry.execute(
        ToolCall(name="session_list_files", arguments={}),
        context=_context("sess_file_1"),
    )
    assert result.success is True
    assert "file_1" in result.content
    assert "\"is_active\": true" in result.content
    assert "\"recommended_access_plan\"" in result.content


def test_session_read_file_lazy_parse_uploaded_text(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    meta = session_repo.create_session("sess_file_2")
    workspace = session_repo.get_workspace_path("sess_file_2")
    upload_path = workspace / "uploads" / "file_2_notes.txt"
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    upload_path.write_text("first line\nsecond line\nthird line", encoding="utf-8")
    session_repo.add_or_update_session_file(
        SessionFile(
            file_id="file_2",
            session_id="sess_file_2",
            filename="notes.txt",
            media_type="text/plain",
            size_bytes=31,
            status="uploaded",
            uploaded_at=meta.created_at,
            storage_relpath="workspace/uploads/file_2_notes.txt",
            text_relpath=None,
            error=None,
        )
    )

    registry = _registry()
    registry.register(SessionReadFileTool(session_repository=session_repo))

    result = registry.execute(
        ToolCall(name="session_read_file", arguments={"file_id": "file_2", "offset": 0, "max_chars": 12}),
        context=_context("sess_file_2"),
    )
    updated = session_repo.get_session_file("sess_file_2", "file_2")

    assert result.success is True
    assert "\"content\": \"first line\\ns\"" in result.content
    assert updated is not None
    assert updated.status == "ready"
    assert updated.text_relpath is not None
    assert updated.parsed_char_count is not None
    assert updated.parsed_char_count > 0
    assert updated.parsed_token_estimate is not None
    assert updated.parsed_token_estimate > 0
    assert updated.parsed_at is not None


def test_session_search_file_returns_hits(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    meta = session_repo.create_session("sess_file_3")
    workspace = session_repo.get_workspace_path("sess_file_3")
    upload_path = workspace / "uploads" / "file_3_notes.txt"
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    upload_path.write_text("alpha beta\ngamma beta\ndelta", encoding="utf-8")
    session_repo.add_or_update_session_file(
        SessionFile(
            file_id="file_3",
            session_id="sess_file_3",
            filename="notes.txt",
            media_type="text/plain",
            size_bytes=27,
            status="uploaded",
            uploaded_at=meta.created_at,
            storage_relpath="workspace/uploads/file_3_notes.txt",
            text_relpath=None,
            error=None,
        )
    )

    registry = _registry()
    registry.register(SessionSearchFileTool(session_repository=session_repo))

    result = registry.execute(
        ToolCall(name="session_search_file", arguments={"file_id": "file_3", "query": "beta", "top_k": 2}),
        context=_context("sess_file_3"),
    )

    assert result.success is True
    assert "\"hit_count\": 2" in result.content
    assert "gamma beta" in result.content


def test_session_plan_file_access_returns_direct_read_for_small_file(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    meta = session_repo.create_session("sess_file_4")
    session_repo.add_or_update_session_file(
        SessionFile(
            file_id="file_4",
            session_id="sess_file_4",
            filename="small.txt",
            media_type="text/plain",
            size_bytes=1200,
            status="ready",
            uploaded_at=meta.created_at,
            storage_relpath="workspace/uploads/file_4_small.txt",
            text_relpath="workspace/.parsed/file_4.txt",
            error=None,
            parsed_char_count=2000,
            parsed_token_estimate=500,
            parsed_at=meta.created_at,
        )
    )
    registry = _registry()
    registry.register(SessionPlanFileAccessTool(session_repository=session_repo))
    result = registry.execute(
        ToolCall(name="session_plan_file_access", arguments={"file_id": "file_4"}),
        context=_context("sess_file_4"),
    )
    assert result.success is True
    assert "\"strategy\": \"direct_read\"" in result.content


def test_session_plan_file_access_returns_search_for_precision_goal(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    meta = session_repo.create_session("sess_file_5")
    session_repo.add_or_update_session_file(
        SessionFile(
            file_id="file_5",
            session_id="sess_file_5",
            filename="manual.txt",
            media_type="text/plain",
            size_bytes=5000,
            status="ready",
            uploaded_at=meta.created_at,
            storage_relpath="workspace/uploads/file_5_manual.txt",
            text_relpath="workspace/.parsed/file_5.txt",
            error=None,
            parsed_char_count=6000,
            parsed_token_estimate=1500,
            parsed_at=meta.created_at,
        )
    )
    registry = _registry()
    registry.register(SessionPlanFileAccessTool(session_repository=session_repo))
    result = registry.execute(
        ToolCall(
            name="session_plan_file_access",
            arguments={"file_id": "file_5", "user_goal": "quote_exact"},
        ),
        context=_context("sess_file_5"),
    )
    assert result.success is True
    assert "\"strategy\": \"search_then_read\"" in result.content


def test_tool_registry_blocks_tool_when_agent_not_allowed(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_perm_1")
    restricted_registry = AgentCapabilityRegistry(
        {
            "agent_main": AgentCapability(
                agent_id="agent_main",
                allowed_tools=["memory_search"],
                memory_read_scopes=[MemoryScope.AGENT_SHORT, MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                memory_write_scopes=[MemoryScope.AGENT_SHORT, MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                allow_cross_session_short_read=True,
                allow_cross_agent_memory_read=False,
                allow_cross_agent_memory_write=False,
            )
        }
    )
    registry = _registry(restricted_registry)
    registry.register(WorkspaceWriteFileTool(session_repository=session_repo))

    with pytest.raises(ToolExecutionError):
        registry.execute(
            ToolCall(
                name="workspace_write_file",
                arguments={"path": "notes.txt", "content": "hello"},
            ),
            context=_context("sess_perm_1", agent_id="agent_main"),
        )
