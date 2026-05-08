"""Built-in tools for session artifacts."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.core.errors import ToolExecutionError
from app.core.time import app_now
from app.domain.models import RunContext, SessionArtifact, ToolDefinition, ToolExecutionResult
from app.domain.protocols import SessionRepository
from app.tools.builtin_tools.common import (
    parse_non_negative_int,
    parse_positive_int,
    require_non_empty_argument,
    validate_context,
)
from app.tools.builtin_tools.session_artifact_helpers import (
    collect_text_hits,
    decide_artifact_access_plan,
    ensure_session_artifact_text_ready,
    require_session_artifact,
)


class SessionCreateTextArtifactTool:
    """Create a shared text session artifact without exposing workspace paths."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_create_text_artifact",
            description="Create a shared text session artifact from direct content without using file paths.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["pasted_text", "generated_file"],
                        "default": "generated_file",
                    },
                    "media_type": {
                        "type": "string",
                        "enum": ["text/plain", "text/markdown"],
                        "default": "text/plain",
                    },
                    "description": {"type": "string"},
                },
                "required": ["title", "content"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        if not isinstance(arguments, dict):
            raise ToolExecutionError("Tool arguments must be an object.")
        title = _normalize_artifact_title(arguments.get("title"))
        content = _require_text_content(arguments.get("content"))
        kind = _parse_text_artifact_kind(arguments.get("kind", "generated_file"))
        media_type = _parse_text_media_type(arguments.get("media_type", "text/plain"))
        description = _optional_text(arguments.get("description"))

        session_id = run_context.session_id
        artifact_id = f"artifact_{uuid4().hex[:12]}"
        root = self._session_repository.get_session_root_path(session_id).resolve()
        artifact_dir = root / "artifacts" / artifact_id
        original_path = artifact_dir / "original.bin"
        text_path = artifact_dir / "content.txt"
        try:
            artifact_dir.mkdir(parents=True, exist_ok=False)
            original_path.write_text(content, encoding="utf-8")
            text_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ToolExecutionError(f"Failed to create text artifact: {exc}") from exc

        now = app_now()
        artifact = SessionArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            kind=kind,
            title=title,
            description=description,
            media_type=media_type,
            size_bytes=original_path.stat().st_size,
            status="ready",
            visibility="session_shared",
            owner_agent_id=run_context.agent_id,
            source_type="tool_session_create_text_artifact",
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
            "artifact_id": artifact.artifact_id,
            "title": artifact.title,
            "kind": artifact.kind,
            "media_type": artifact.media_type,
            "text_char_count": artifact.text_char_count,
            "token_estimate": artifact.token_estimate,
            "owner_agent_id": artifact.owner_agent_id,
        }
        return ToolExecutionResult(
            tool_name="session_create_text_artifact",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class SessionListArtifactsTool:
    """List session artifacts visible in the current session."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_list_artifacts",
            description="List shared session artifacts, including active status and parse status.",
            parameters_schema={"type": "object", "properties": {}},
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        session_id = run_context.session_id
        if not isinstance(arguments, dict):
            raise ToolExecutionError("Tool arguments must be an object.")
        artifacts = self._session_repository.list_session_artifacts(session_id)
        active_artifact_ids = set(self._session_repository.get_active_artifact_ids(session_id))
        payload = {
            "session_id": session_id,
            "active_artifact_ids": list(active_artifact_ids),
            "artifacts": [
                {
                    "artifact_id": item.artifact_id,
                    "kind": item.kind,
                    "title": item.title,
                    "media_type": item.media_type,
                    "size_bytes": item.size_bytes,
                    "status": item.status,
                    "visibility": item.visibility,
                    "owner_agent_id": item.owner_agent_id,
                    "is_active": item.artifact_id in active_artifact_ids,
                    "text_ready": item.status == "ready" and item.text_relpath is not None,
                    "text_char_count": item.text_char_count,
                    "token_estimate": item.token_estimate,
                }
                for item in artifacts
                if item.visibility == "session_shared"
            ],
        }
        return ToolExecutionResult(
            tool_name="session_list_artifacts",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class SessionReadArtifactTool:
    """Read session artifact text by artifact_id."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_read_artifact",
            description="Read text content from a shared session artifact by artifact_id.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "offset": {"type": "integer", "default": 0, "minimum": 0},
                    "max_chars": {"type": "integer", "default": 3000, "minimum": 200, "maximum": 12000},
                },
                "required": ["artifact_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        session_id = run_context.session_id
        artifact_id = require_non_empty_argument(arguments, "artifact_id")
        offset = parse_non_negative_int(arguments.get("offset", 0), field_name="offset")
        max_chars = min(parse_positive_int(arguments.get("max_chars", 3000), field_name="max_chars"), 12000)

        artifact = require_session_artifact(self._session_repository, session_id, artifact_id)
        updated_artifact, text = ensure_session_artifact_text_ready(self._session_repository, session_id, artifact)
        snippet = text[offset : offset + max_chars] if offset < len(text) else ""
        payload = {
            "artifact_id": updated_artifact.artifact_id,
            "title": updated_artifact.title,
            "media_type": updated_artifact.media_type,
            "status": updated_artifact.status,
            "total_chars": len(text),
            "offset": offset,
            "returned_chars": len(snippet),
            "truncated": offset + max_chars < len(text),
            "content": snippet,
        }
        return ToolExecutionResult(
            tool_name="session_read_artifact",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class SessionPlanArtifactAccessTool:
    """Plan a recommended artifact reading strategy from metadata."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_plan_artifact_access",
            description="Return recommended reading strategy for one shared session artifact.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "user_goal": {"type": "string"},
                },
                "required": ["artifact_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        session_id = run_context.session_id
        artifact_id = require_non_empty_argument(arguments, "artifact_id")
        raw_goal = arguments.get("user_goal")
        user_goal = raw_goal.strip() if isinstance(raw_goal, str) and raw_goal.strip() else None
        artifact = require_session_artifact(self._session_repository, session_id, artifact_id)
        plan = decide_artifact_access_plan(artifact=artifact, user_goal=user_goal)
        payload = {
            "artifact_id": artifact.artifact_id,
            "title": artifact.title,
            "media_type": artifact.media_type,
            "status": artifact.status,
            "size_bytes": artifact.size_bytes,
            "text_char_count": artifact.text_char_count,
            "token_estimate": artifact.token_estimate,
            "user_goal": user_goal,
            "plan": plan,
        }
        return ToolExecutionResult(
            tool_name="session_plan_artifact_access",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class SessionSearchArtifactTool:
    """Search keyword in parsed text for one shared artifact."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_search_artifact",
            description="Search keyword in one shared session artifact by artifact_id.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 3, "minimum": 1, "maximum": 8},
                    "window_chars": {"type": "integer", "default": 160, "minimum": 40, "maximum": 800},
                },
                "required": ["artifact_id", "query"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        session_id = run_context.session_id
        artifact_id = require_non_empty_argument(arguments, "artifact_id")
        query = require_non_empty_argument(arguments, "query")
        top_k = min(parse_positive_int(arguments.get("top_k", 3), field_name="top_k"), 8)
        window_chars = min(parse_positive_int(arguments.get("window_chars", 160), field_name="window_chars"), 800)

        artifact = require_session_artifact(self._session_repository, session_id, artifact_id)
        updated_artifact, text = ensure_session_artifact_text_ready(self._session_repository, session_id, artifact)
        hits = collect_text_hits(text=text, query=query, top_k=top_k, window_chars=window_chars)
        payload = {
            "artifact_id": updated_artifact.artifact_id,
            "title": updated_artifact.title,
            "query": query,
            "hit_count": len(hits),
            "hits": hits,
        }
        return ToolExecutionResult(
            tool_name="session_search_artifact",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


def _normalize_artifact_title(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ToolExecutionError("'title' must be a non-empty string.")
    title = raw.strip().replace("/", "_").replace("\\", "_")
    if not title:
        raise ToolExecutionError("'title' must be a non-empty string.")
    return title


def _require_text_content(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ToolExecutionError("'content' must be a non-empty string.")
    return raw


def _parse_text_artifact_kind(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ToolExecutionError("'kind' must be a string.")
    normalized = raw.strip().lower()
    if normalized not in {"pasted_text", "generated_file"}:
        raise ToolExecutionError("'kind' must be pasted_text or generated_file.")
    return normalized


def _parse_text_media_type(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ToolExecutionError("'media_type' must be a string.")
    normalized = raw.strip().lower()
    if normalized not in {"text/plain", "text/markdown"}:
        raise ToolExecutionError("'media_type' must be text/plain or text/markdown.")
    return normalized


def _optional_text(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ToolExecutionError("'description' must be a string.")
    normalized = raw.strip()
    return normalized or None


def _estimate_tokens_from_text(text: str) -> int:
    if not text:
        return 1
    return max(1, (len(text) + 3) // 4)
