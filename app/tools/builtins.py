"""Built-in tools for memory and workspace access."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import StorageError, ToolExecutionError, ValidationError
from app.domain.models import MemoryItem, ToolDefinition, ToolExecutionResult
from app.domain.protocols import MemoryRepository, SessionRepository

__all__ = [
    "MemorySearchTool",
    "MemoryWriteTool",
    "WorkspaceReadFileTool",
    "WorkspaceWriteFileTool",
]
_logger = logging.getLogger(__name__)


class MemoryWriteTool:
    """Write long-term memory entries."""

    def __init__(self, memory_repository: MemoryRepository) -> None:
        self._memory_repository = memory_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="memory_write",
            description="Write a long-term memory item.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                    },
                },
                "required": ["content"],
            },
        )

    def execute(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        _validate_session_id(session_id)
        content = _require_non_empty_argument(arguments, "content")
        tags = _normalize_tags(arguments.get("tags", []))
        _logger.debug("执行 memory_write: session_id=%s tags=%s content_len=%s", session_id, len(tags), len(content))
        memory_item = MemoryItem(
            memory_id=f"mem_{uuid4().hex[:12]}",
            session_id=session_id,
            content=content,
            tags=tags,
            created_at=datetime.now(UTC),
            source_event_id=None,
        )
        try:
            self._memory_repository.add_memory(memory_item)
        except StorageError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return ToolExecutionResult(
            tool_name="memory_write",
            success=True,
            content=json.dumps({"memory_id": memory_item.memory_id}, ensure_ascii=False),
        )


class MemorySearchTool:
    """Search memory items by query."""

    def __init__(self, memory_repository: MemoryRepository) -> None:
        self._memory_repository = memory_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="memory_search",
            description="Search memory items using plain-text matching.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
        )

    def execute(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        _validate_session_id(session_id)
        query = _require_non_empty_argument(arguments, "query")
        raw_limit = arguments.get("limit", 5)
        if not isinstance(raw_limit, int) or raw_limit <= 0:
            raise ToolExecutionError("'limit' must be a positive integer.")
        limit = min(raw_limit, 20)
        hits = self._memory_repository.search(query, limit)
        _logger.debug("执行 memory_search: session_id=%s query=%s hit_count=%s", session_id, query, len(hits))
        payload = [
            {
                "memory_id": item.memory_id,
                "content": item.content,
                "tags": item.tags,
            }
            for item in hits
        ]
        return ToolExecutionResult(
            tool_name="memory_search",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class WorkspaceWriteFileTool:
    """Write a text file under session workspace."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="workspace_write_file",
            description="Write content into a session workspace file.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        )

    def execute(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        _validate_session_id(session_id)
        relative_path = _require_non_empty_argument(arguments, "path")
        content = _require_non_empty_argument(arguments, "content")
        workspace = self._session_repository.get_workspace_path(session_id)
        target = _resolve_workspace_path(workspace, relative_path)
        _logger.debug("执行 workspace_write_file: session_id=%s path=%s", session_id, relative_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ToolExecutionError(f"Failed to write file: {exc}") from exc
        return ToolExecutionResult(
            tool_name="workspace_write_file",
            success=True,
            content=f"Wrote file: {relative_path}",
        )


class WorkspaceReadFileTool:
    """Read a text file under session workspace."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="workspace_read_file",
            description=(
                "Read content from file with workspace-first lookup. "
                "Workspace is data/sessions/<session_id>/workspace. "
                "If missing in workspace, search parent directories upward to filesystem root."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        )

    def execute(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        _validate_session_id(session_id)
        relative_path = _require_non_empty_argument(arguments, "path")
        workspace = self._session_repository.get_workspace_path(session_id).resolve()
        target = _find_file_with_workspace_fallback(workspace, relative_path)
        if target is None:
            raise ToolExecutionError(
                "File does not exist after workspace-first lookup. "
                f"path={relative_path} workspace={workspace}"
            )
        _logger.debug(
            "执行 workspace_read_file: session_id=%s path=%s resolved_path=%s workspace=%s",
            session_id,
            relative_path,
            target,
            workspace,
        )
        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise ToolExecutionError(f"Failed to read file: {exc}") from exc
        return ToolExecutionResult(tool_name="workspace_read_file", success=True, content=content or "(empty)")



def _validate_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValidationError("session_id must be a non-empty string.")
    return session_id.strip()



def _require_non_empty_argument(arguments: dict[str, Any], key: str) -> str:
    if not isinstance(arguments, dict):
        raise ToolExecutionError("Tool arguments must be an object.")
    raw_value = arguments.get(key)
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ToolExecutionError(f"'{key}' must be a non-empty string.")
    return raw_value.strip()



def _normalize_tags(raw_tags: Any) -> list[str]:
    if raw_tags is None:
        return []
    if not isinstance(raw_tags, list):
        raise ToolExecutionError("'tags' must be a list of strings.")
    normalized: list[str] = []
    for tag in raw_tags:
        if not isinstance(tag, str) or not tag.strip():
            raise ToolExecutionError("each tag must be a non-empty string.")
        normalized.append(tag.strip())
    return normalized



def _resolve_workspace_path(workspace: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ToolExecutionError("Absolute paths are not allowed.")
    workspace_resolved = workspace.resolve()
    target = (workspace_resolved / candidate).resolve()
    if not target.is_relative_to(workspace_resolved):
        raise ToolExecutionError("Path traversal is not allowed.")
    return target


def _find_file_with_workspace_fallback(workspace: Path, relative_path: str) -> Path | None:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ToolExecutionError("Absolute paths are not allowed.")
    if ".." in candidate.parts:
        raise ToolExecutionError("Path traversal is not allowed.")

    # 查找顺序：workspace -> workspace 的父目录 ... -> 文件系统根目录
    search_roots = [workspace, *list(workspace.parents)]
    for root in search_roots:
        target = root / candidate
        if target.exists() and target.is_file():
            return target
    return None
