"""Tests for tool registry and builtin tool safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import ToolExecutionError, ValidationError
from app.domain.models import ToolCall
from app.infra.storage.jsonl_memory_repository import JsonlMemoryRepository
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.tools.builtins import MemoryWriteTool, WorkspaceReadFileTool, WorkspaceWriteFileTool
from app.tools.registry import ToolRegistry

__all__ = []



def test_tool_register_success_and_duplicate_error(tmp_path: Path) -> None:
    memory_repo = JsonlMemoryRepository(data_dir=tmp_path)
    registry = ToolRegistry()

    registry.register(MemoryWriteTool(memory_repository=memory_repo))

    assert len(registry.list_definitions()) == 1

    with pytest.raises(ValidationError):
        registry.register(MemoryWriteTool(memory_repository=memory_repo))



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
