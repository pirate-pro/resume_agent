"""Built-in workspace file tools."""

from __future__ import annotations

import logging
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import ToolExecutionError
from app.domain.models import RunContext, SessionArtifact, ToolDefinition, ToolExecutionResult
from app.domain.protocols import SessionRepository
from app.tools.builtin_tools.common import require_non_empty_argument, validate_context

_logger = logging.getLogger(__name__)


class WorkspaceWriteFileTool:
    """Write a text file under current agent workspace."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="workspace_write_file",
            description="Write content into the current agent's private session workspace.",
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
        agent_id = run_context.agent_id
        relative_path = require_non_empty_argument(arguments, "path")
        content = require_non_empty_argument(arguments, "content")
        workspace = self._session_repository.get_agent_workspace_path(session_id, agent_id)
        target = _resolve_workspace_path(workspace, relative_path)
        _logger.debug(
            "执行 workspace_write_file: session_id=%s agent_id=%s path=%s",
            session_id,
            agent_id,
            relative_path,
        )
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
    """Read a text file under current agent workspace."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="workspace_read_file",
            description=(
                "Read content from a file in the current agent's private workspace. "
                "No parent-directory fallback is allowed."
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
        agent_id = run_context.agent_id
        relative_path = require_non_empty_argument(arguments, "path")
        workspace = self._session_repository.get_agent_workspace_path(session_id, agent_id).resolve()
        target = _resolve_workspace_path(workspace, relative_path)
        if not target.exists() or not target.is_file():
            raise ToolExecutionError(
                "File does not exist in current agent workspace. "
                f"path={relative_path} agent_id={agent_id} workspace={workspace}"
            )
        _logger.debug(
            "执行 workspace_read_file: session_id=%s agent_id=%s path=%s resolved_path=%s workspace=%s",
            session_id,
            agent_id,
            relative_path,
            target,
            workspace,
        )
        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise ToolExecutionError(f"Failed to read file: {exc}") from exc
        return ToolExecutionResult(tool_name="workspace_read_file", success=True, content=content or "(empty)")


class PublishArtifactTool:
    """Publish a current-agent workspace file as a session shared artifact."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="publish_artifact",
            description="Publish a current-agent workspace file into session shared artifacts.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["path", "title"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        session_id = run_context.session_id
        agent_id = run_context.agent_id
        relative_path = require_non_empty_argument(arguments, "path")
        title = require_non_empty_argument(arguments, "title")
        raw_description = arguments.get("description")
        description = raw_description.strip() if isinstance(raw_description, str) and raw_description.strip() else None

        workspace = self._session_repository.get_agent_workspace_path(session_id, agent_id).resolve()
        source = _resolve_workspace_path(workspace, relative_path)
        if not source.exists() or not source.is_file():
            raise ToolExecutionError(
                f"Workspace file does not exist: session_id={session_id} agent_id={agent_id} path={relative_path}"
            )
        try:
            content = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = source.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ToolExecutionError(f"Failed to read workspace file for publishing: {exc}") from exc

        artifact_id = f"artifact_{uuid4().hex[:12]}"
        root = self._session_repository.get_session_root_path(session_id).resolve()
        artifact_dir = root / "artifacts" / artifact_id
        artifact_dir.mkdir(parents=True, exist_ok=False)
        original_path = artifact_dir / "original.bin"
        text_path = artifact_dir / "content.txt"
        try:
            original_path.write_text(content, encoding="utf-8")
            text_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ToolExecutionError(f"Failed to publish artifact: {exc}") from exc

        now = datetime.now(UTC)
        artifact = SessionArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            kind="generated_file",
            title=title,
            description=description,
            media_type=_infer_text_media_type(source),
            size_bytes=original_path.stat().st_size,
            status="ready",
            visibility="session_shared",
            owner_agent_id=agent_id,
            source_type="workspace_publish",
            source_event_id=None,
            created_at=now,
            updated_at=now,
            storage_relpath=str(original_path.relative_to(root)),
            text_relpath=str(text_path.relative_to(root)),
            error=None,
            text_char_count=len(content),
            token_estimate=_estimate_tokens_from_text(content),
            parsed_at=now,
        )
        self._session_repository.add_or_update_session_artifact(artifact)
        payload = {
            "artifact_id": artifact_id,
            "title": title,
            "owner_agent_id": agent_id,
            "visibility": "session_shared",
            "source_workspace_path": relative_path,
        }
        return ToolExecutionResult(
            tool_name="publish_artifact",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


def _resolve_workspace_path(workspace: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ToolExecutionError("Absolute paths are not allowed.")
    workspace_resolved = workspace.resolve()
    target = (workspace_resolved / candidate).resolve()
    if not target.is_relative_to(workspace_resolved):
        raise ToolExecutionError("Path traversal is not allowed.")
    return target


def _infer_text_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    if suffix == ".json":
        return "application/json"
    return "text/plain"


def _estimate_tokens_from_text(text: str) -> int:
    if not text:
        return 1
    return max(1, (len(text) + 3) // 4)
