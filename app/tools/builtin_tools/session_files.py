"""Built-in tools for uploaded session files."""

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
from app.tools.builtin_tools.session_file_helpers import (
    collect_text_hits,
    decide_file_access_plan,
    ensure_session_file_text_ready,
    require_session_file,
    serialize_file_listing,
)


class SessionListFilesTool:
    """List uploaded files for current session."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_list_files",
            description="List uploaded files in current session, including active status and parse status.",
            parameters_schema={
                "type": "object",
                "properties": {},
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        session_id = run_context.session_id
        if not isinstance(arguments, dict):
            raise ToolExecutionError("Tool arguments must be an object.")
        files = self._session_repository.list_session_files(session_id)
        active_file_ids = self._session_repository.get_active_file_ids(session_id)
        active_set = set(active_file_ids)
        payload = {
            "session_id": session_id,
            "active_file_ids": active_file_ids,
            "files": [serialize_file_listing(item, active_file_ids=active_set) for item in files],
        }
        return ToolExecutionResult(
            tool_name="session_list_files",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class SessionReadFileTool:
    """Read session file text with lazy parse."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_read_file",
            description=(
                "Read text content from an uploaded session file by file_id. "
                "If file text is not parsed yet, parse lazily then read."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "offset": {"type": "integer", "default": 0, "minimum": 0},
                    "max_chars": {"type": "integer", "default": 3000, "minimum": 200, "maximum": 12000},
                },
                "required": ["file_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        session_id = run_context.session_id
        file_id = require_non_empty_argument(arguments, "file_id")
        offset = parse_non_negative_int(arguments.get("offset", 0), field_name="offset")
        max_chars = parse_positive_int(arguments.get("max_chars", 3000), field_name="max_chars")
        max_chars = min(max_chars, 12000)
        file_record = require_session_file(self._session_repository, session_id, file_id)
        updated_file, text = ensure_session_file_text_ready(self._session_repository, session_id, file_record)
        snippet = text[offset : offset + max_chars] if offset < len(text) else ""
        payload = {
            "file_id": updated_file.file_id,
            "filename": updated_file.filename,
            "media_type": updated_file.media_type,
            "status": updated_file.status,
            "total_chars": len(text),
            "offset": offset,
            "returned_chars": len(snippet),
            "truncated": offset + max_chars < len(text),
            "content": snippet,
        }
        return ToolExecutionResult(
            tool_name="session_read_file",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class SessionPlanFileAccessTool:
    """Plan a recommended file reading strategy from metadata."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_plan_file_access",
            description=(
                "Return recommended reading strategy for one uploaded session file "
                "based on metadata and optional user_goal."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "user_goal": {
                        "type": "string",
                        "description": (
                            "Optional user intent hint, e.g. summarize, find_fact, quote_exact, compare, troubleshoot."
                        ),
                    },
                },
                "required": ["file_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        session_id = run_context.session_id
        file_id = require_non_empty_argument(arguments, "file_id")
        raw_goal = arguments.get("user_goal")
        user_goal = raw_goal.strip() if isinstance(raw_goal, str) and raw_goal.strip() else None

        file_record = require_session_file(self._session_repository, session_id, file_id)
        plan = decide_file_access_plan(file_record=file_record, user_goal=user_goal)
        payload = {
            "file_id": file_record.file_id,
            "filename": file_record.filename,
            "media_type": file_record.media_type,
            "status": file_record.status,
            "size_bytes": file_record.size_bytes,
            "parsed_char_count": file_record.parsed_char_count,
            "parsed_token_estimate": file_record.parsed_token_estimate,
            "user_goal": user_goal,
            "plan": plan,
        }
        return ToolExecutionResult(
            tool_name="session_plan_file_access",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class SessionSearchFileTool:
    """Search keyword in parsed text for one uploaded file."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_search_file",
            description=(
                "Search keyword in one uploaded session file by file_id. "
                "Return snippet hits with nearby context."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 3, "minimum": 1, "maximum": 8},
                    "window_chars": {"type": "integer", "default": 160, "minimum": 40, "maximum": 800},
                },
                "required": ["file_id", "query"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        session_id = run_context.session_id
        file_id = require_non_empty_argument(arguments, "file_id")
        query = require_non_empty_argument(arguments, "query")
        top_k = min(parse_positive_int(arguments.get("top_k", 3), field_name="top_k"), 8)
        window_chars = min(parse_positive_int(arguments.get("window_chars", 160), field_name="window_chars"), 800)

        file_record = require_session_file(self._session_repository, session_id, file_id)
        updated_file, text = ensure_session_file_text_ready(self._session_repository, session_id, file_record)
        hits = collect_text_hits(text=text, query=query, top_k=top_k, window_chars=window_chars)
        payload = {
            "file_id": updated_file.file_id,
            "filename": updated_file.filename,
            "query": query,
            "hit_count": len(hits),
            "hits": hits,
        }
        return ToolExecutionResult(
            tool_name="session_search_file",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )
