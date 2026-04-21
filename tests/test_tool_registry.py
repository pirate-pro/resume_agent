"""Tests for tool registry and builtin tool safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import ToolExecutionError, ValidationError
from app.domain.models import ToolCall
from app.infra.storage.jsonl_memory_repository import JsonlMemoryRepository
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.tools.builtins import MemoryWriteTool, WorkspaceWriteFileTool
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
