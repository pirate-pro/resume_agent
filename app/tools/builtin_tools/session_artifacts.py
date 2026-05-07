"""Built-in tools for session artifacts."""

from __future__ import annotations

import json
from typing import Any

from app.core.errors import ToolExecutionError
from app.domain.models import RunContext, ToolDefinition, ToolExecutionResult
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
