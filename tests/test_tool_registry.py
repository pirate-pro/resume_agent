"""Tests for tool registry and builtin tool safety."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.errors import ToolExecutionError, ValidationError
from app.domain.models import SessionFile, ToolCall
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.memory.facade import FileMemoryFacade
from app.memory.models import MemoryReadRequest
from app.memory.policies import default_memory_policy
from app.memory.stores.jsonl_file_store import JsonlFileMemoryStore
from app.tools.builtins import (
    MemorySearchTool,
    MemoryWriteTool,
    SessionListFilesTool,
    SessionPlanFileAccessTool,
    SessionReadFileTool,
    SessionSearchFileTool,
    WorkspaceReadFileTool,
    WorkspaceWriteFileTool,
)
from app.tools.registry import ToolRegistry

__all__ = []



def test_tool_register_success_and_duplicate_error(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    registry = ToolRegistry()

    registry.register(MemoryWriteTool(memory_facade=memory_facade))

    assert len(registry.list_definitions()) == 1

    with pytest.raises(ValidationError):
        registry.register(MemoryWriteTool(memory_facade=memory_facade))


def test_memory_write_tool_writes_v2_memory(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())

    registry = ToolRegistry()
    registry.register(MemoryWriteTool(memory_facade=memory_facade))

    result = registry.execute(
        ToolCall(name="memory_write", arguments={"content": "Use markdown format", "tags": ["preference"]}),
        session_id="sess_1",
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


def test_memory_write_tool_without_tags_defaults_to_short_and_is_session_scoped(tmp_path: Path) -> None:
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())

    registry = ToolRegistry()
    registry.register(MemoryWriteTool(memory_facade=memory_facade))
    registry.register(MemorySearchTool(memory_facade=memory_facade))

    write_result = registry.execute(
        ToolCall(name="memory_write", arguments={"content": "User likes concise replies"}),
        session_id="sess_1",
    )
    same_session_result = registry.execute(
        ToolCall(name="memory_search", arguments={"query": "concise", "limit": 5}),
        session_id="sess_1",
    )
    other_session_result = registry.execute(
        ToolCall(name="memory_search", arguments={"query": "concise", "limit": 5}),
        session_id="sess_2",
    )

    assert write_result.success is True
    assert same_session_result.success is True
    same_payload = json.loads(same_session_result.content)
    assert len(same_payload) >= 1
    assert same_payload[0]["scope"] == "agent_short"

    assert other_session_result.success is True
    other_payload = json.loads(other_session_result.content)
    assert other_payload == []



def test_execute_missing_tool_raises(tmp_path: Path) -> None:
    _ = tmp_path
    registry = ToolRegistry()

    with pytest.raises(ToolExecutionError):
        registry.execute(ToolCall(name="missing", arguments={}), session_id="sess_1")



def test_workspace_path_traversal_is_blocked(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_1")

    registry = ToolRegistry()
    registry.register(WorkspaceWriteFileTool(session_repository=session_repo))

    with pytest.raises(ToolExecutionError):
        registry.execute(
            ToolCall(name="workspace_write_file", arguments={"path": "../escape.txt", "content": "x"}),
            session_id="sess_1",
        )


def test_workspace_read_file_fallback_to_parent_directories(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_2")
    (tmp_path / ".env.example").write_text("HELLO=1", encoding="utf-8")

    registry = ToolRegistry()
    registry.register(WorkspaceReadFileTool(session_repository=session_repo))

    result = registry.execute(
        ToolCall(name="workspace_read_file", arguments={"path": ".env.example"}),
        session_id="sess_2",
    )

    assert result.success is True
    assert "HELLO=1" in result.content


def test_workspace_read_file_error_contains_workspace(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_3")
    workspace = session_repo.get_workspace_path("sess_3").resolve()

    registry = ToolRegistry()
    registry.register(WorkspaceReadFileTool(session_repository=session_repo))

    with pytest.raises(ToolExecutionError) as exc_info:
        registry.execute(
            ToolCall(name="workspace_read_file", arguments={"path": "missing.txt"}),
            session_id="sess_3",
        )

    message = str(exc_info.value)
    assert "workspace-first lookup" in message
    assert str(workspace) in message


def test_workspace_read_file_blocks_explicit_parent_segments(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_4")

    registry = ToolRegistry()
    registry.register(WorkspaceReadFileTool(session_repository=session_repo))

    with pytest.raises(ToolExecutionError):
        registry.execute(
            ToolCall(name="workspace_read_file", arguments={"path": "../.env"}),
            session_id="sess_4",
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

    registry = ToolRegistry()
    registry.register(SessionListFilesTool(session_repository=session_repo))

    result = registry.execute(ToolCall(name="session_list_files", arguments={}), session_id="sess_file_1")
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

    registry = ToolRegistry()
    registry.register(SessionReadFileTool(session_repository=session_repo))

    result = registry.execute(
        ToolCall(name="session_read_file", arguments={"file_id": "file_2", "offset": 0, "max_chars": 12}),
        session_id="sess_file_2",
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

    registry = ToolRegistry()
    registry.register(SessionSearchFileTool(session_repository=session_repo))

    result = registry.execute(
        ToolCall(name="session_search_file", arguments={"file_id": "file_3", "query": "beta", "top_k": 2}),
        session_id="sess_file_3",
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
    registry = ToolRegistry()
    registry.register(SessionPlanFileAccessTool(session_repository=session_repo))
    result = registry.execute(
        ToolCall(name="session_plan_file_access", arguments={"file_id": "file_4"}),
        session_id="sess_file_4",
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
    registry = ToolRegistry()
    registry.register(SessionPlanFileAccessTool(session_repository=session_repo))
    result = registry.execute(
        ToolCall(
            name="session_plan_file_access",
            arguments={"file_id": "file_5", "user_goal": "quote_exact"},
        ),
        session_id="sess_file_5",
    )
    assert result.success is True
    assert "\"strategy\": \"search_then_read\"" in result.content
