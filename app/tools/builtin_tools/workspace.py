"""Built-in workspace file tools."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.errors import ToolExecutionError
from app.domain.models import RunContext, ToolDefinition, ToolExecutionResult
from app.domain.protocols import SessionRepository
from app.tools.builtin_tools.common import require_non_empty_argument, validate_context

_logger = logging.getLogger(__name__)


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

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        session_id = run_context.session_id
        relative_path = require_non_empty_argument(arguments, "path")
        content = require_non_empty_argument(arguments, "content")
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

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        session_id = run_context.session_id
        relative_path = require_non_empty_argument(arguments, "path")
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

    search_roots = [workspace, *list(workspace.parents)]
    for root in search_roots:
        target = root / candidate
        if target.exists() and target.is_file():
            return target
    return None
