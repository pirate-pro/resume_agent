"""Built-in tools for session artifacts."""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from app.core.errors import StorageError
from app.core.errors import ToolExecutionError
from app.core.errors import ValidationError
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
        existing_artifact = _find_same_run_generated_artifact(
            self._session_repository,
            context=run_context,
            title=title,
            kind=kind,
        )
        if existing_artifact is not None:
            artifact = _update_text_artifact(
                self._session_repository,
                artifact=existing_artifact,
                title=title,
                content=content,
                kind=kind,
                media_type=media_type,
                description=description,
            )
            payload = _text_artifact_payload(artifact)
            payload["idempotent_update"] = True
            payload["message"] = "已更新同一 run 内已存在的同类 generated_file artifact，避免重复创建。"
            return ToolExecutionResult(
                tool_name="session_create_text_artifact",
                success=True,
                content=json.dumps(payload, ensure_ascii=False),
            )

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
        payload = _text_artifact_payload(artifact)
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

        artifact = self._session_repository.get_session_artifact(session_id, artifact_id)
        if artifact is None:
            return _artifact_not_found_result(
                "session_read_artifact",
                self._session_repository,
                session_id,
                artifact_id,
            )
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
        artifact = self._session_repository.get_session_artifact(session_id, artifact_id)
        if artifact is None:
            return _artifact_not_found_result(
                "session_plan_artifact_access",
                self._session_repository,
                session_id,
                artifact_id,
            )
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

        artifact = self._session_repository.get_session_artifact(session_id, artifact_id)
        if artifact is None:
            return _artifact_not_found_result(
                "session_search_artifact",
                self._session_repository,
                session_id,
                artifact_id,
            )
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


def _find_same_run_generated_artifact(
    session_repository: SessionRepository,
    *,
    context: RunContext,
    title: str,
    kind: str,
) -> SessionArtifact | None:
    if kind != "generated_file":
        return None
    purpose = _generated_report_purpose(title)
    if purpose is None:
        return None
    try:
        events = session_repository.list_run_events(context.session_id, context.agent_id, context.run_id)
    except (StorageError, ValidationError):
        return None
    for event in reversed(events):
        if event.type != "tool_result":
            continue
        payload = event.payload
        if payload.get("tool_name") != "session_create_text_artifact" or payload.get("success") is not True:
            continue
        raw_content = payload.get("content")
        if not isinstance(raw_content, str):
            continue
        try:
            content_payload = json.loads(raw_content)
        except ValueError:
            continue
        if not isinstance(content_payload, dict):
            continue
        artifact_id = content_payload.get("artifact_id")
        prior_title = content_payload.get("title")
        if not isinstance(artifact_id, str) or not isinstance(prior_title, str):
            continue
        if _generated_report_purpose(prior_title) != purpose:
            continue
        artifact = session_repository.get_session_artifact(context.session_id, artifact_id)
        if artifact is None:
            continue
        if artifact.owner_agent_id != context.agent_id or artifact.kind != "generated_file":
            continue
        return artifact
    return None


def _update_text_artifact(
    session_repository: SessionRepository,
    *,
    artifact: SessionArtifact,
    title: str,
    content: str,
    kind: str,
    media_type: str,
    description: str | None,
) -> SessionArtifact:
    root = session_repository.get_session_root_path(artifact.session_id).resolve()
    storage_path = (root / artifact.storage_relpath).resolve()
    text_path = (root / artifact.text_relpath).resolve() if artifact.text_relpath else storage_path
    if not storage_path.is_relative_to(root) or not text_path.is_relative_to(root):
        raise ToolExecutionError("Existing artifact path escapes session root.")
    try:
        storage_path.write_text(content, encoding="utf-8")
        text_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ToolExecutionError(f"Failed to update existing text artifact: {exc}") from exc

    now = app_now()
    updated = SessionArtifact(
        artifact_id=artifact.artifact_id,
        session_id=artifact.session_id,
        kind=kind,
        title=title,
        description=description,
        media_type=media_type,
        size_bytes=storage_path.stat().st_size,
        status="ready",
        visibility=artifact.visibility,
        owner_agent_id=artifact.owner_agent_id,
        source_type=artifact.source_type,
        source_event_id=artifact.source_event_id,
        created_at=artifact.created_at,
        updated_at=now,
        storage_relpath=artifact.storage_relpath,
        text_relpath=artifact.text_relpath,
        error=None,
        text_char_count=len(content),
        token_estimate=_estimate_tokens_from_text(content),
        parsed_at=now,
    )
    session_repository.add_or_update_session_artifact(updated)
    return updated


def _text_artifact_payload(artifact: SessionArtifact) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "title": artifact.title,
        "kind": artifact.kind,
        "media_type": artifact.media_type,
        "text_char_count": artifact.text_char_count,
        "token_estimate": artifact.token_estimate,
        "owner_agent_id": artifact.owner_agent_id,
    }


def _generated_report_purpose(title: str) -> str | None:
    normalized = _artifact_title_key(title)
    if "简历" in normalized and ("诊断" in normalized or "画像" in normalized) and "报告" in normalized:
        return "resume_diagnosis_report"
    if ("岗位" in normalized or "职位" in normalized or "匹配" in normalized or "fit" in normalized) and "报告" in normalized:
        return "job_fit_report"
    if ("岗位" in normalized or "职位" in normalized or "jd" in normalized) and "分析" in normalized and "报告" in normalized:
        return "jd_analysis_report"
    if "定制" in normalized and "简历" in normalized:
        return "resume_version"
    return None


def _artifact_title_key(title: str) -> str:
    normalized = title.strip().casefold()
    normalized = re.sub(r"\.(md|markdown|txt)$", "", normalized)
    return re.sub(r"[\s_\-—:：|｜/\\（）()【】\[\].。]+", "", normalized)


def _artifact_not_found_result(
    tool_name: str,
    session_repository: SessionRepository,
    session_id: str,
    artifact_id: str,
) -> ToolExecutionResult:
    artifacts = session_repository.list_session_artifacts(session_id)
    payload = {
        "artifact_id": artifact_id,
        "found": False,
        "message": f"Session artifact not found: {artifact_id}",
        "available_artifact_ids": [
            item.artifact_id
            for item in artifacts
            if item.visibility == "session_shared"
        ],
        "hint": "Call session_list_artifacts and retry with an exact current-session artifact_id.",
    }
    return ToolExecutionResult(tool_name=tool_name, success=True, content=json.dumps(payload, ensure_ascii=False))


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
