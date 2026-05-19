"""Built-in read-only tools for product-context retrieval."""

from __future__ import annotations

import json
from typing import Any, cast

from app.core.errors import ToolExecutionError, ValidationError
from app.domain.models import RunContext, ToolDefinition, ToolExecutionResult
from app.retrieval.models import RetrievalQuery, RetrievalSourceType, validate_source_type
from app.retrieval.service import RetrievalService
from app.tools.builtin_tools.common import validate_context

__all__ = [
    "RetrievalContextPackTool",
    "RetrievalSearchTool",
]

_RETRIEVAL_ARGUMENT_FIELDS = {
    "query",
    "source_types",
    "related_application_id",
    "top_k",
    "max_chars",
    "include_archived",
}
_SOURCE_TYPE_GROUP_ALIASES = {
    "career": (
        RetrievalSourceType.CAREER_APPLICATION,
        RetrievalSourceType.RESUME_PROFILE,
        RetrievalSourceType.CAREER_PROFILE,
        RetrievalSourceType.JD_ANALYSIS,
        RetrievalSourceType.JOB_FIT_REPORT,
        RetrievalSourceType.RESUME_VERSION,
    ),
    "notes": (
        RetrievalSourceType.NOTE,
        RetrievalSourceType.NOTE_COLLECTION,
    ),
    "knowledge": (
        RetrievalSourceType.EXTERNAL_RESOURCE,
        RetrievalSourceType.EXPERIENCE_POST,
        RetrievalSourceType.INTERVIEW_QUESTION,
        RetrievalSourceType.COMPANY_PROFILE,
        RetrievalSourceType.SKILL_REQUIREMENT,
    ),
    "learning": (
        RetrievalSourceType.LEARNING_PLAN,
        RetrievalSourceType.LEARNING_TASK,
        RetrievalSourceType.PROGRESS_CHECKIN,
        RetrievalSourceType.WEAKNESS_TRACKER,
        RetrievalSourceType.REVIEW_SCHEDULE,
    ),
    "artifacts": (RetrievalSourceType.SESSION_ARTIFACT,),
    "artifact": (RetrievalSourceType.SESSION_ARTIFACT,),
    "application": (RetrievalSourceType.CAREER_APPLICATION,),
    "applications": (RetrievalSourceType.CAREER_APPLICATION,),
    "resume": (RetrievalSourceType.RESUME_PROFILE,),
    "resumes": (RetrievalSourceType.RESUME_PROFILE,),
    "profile": (RetrievalSourceType.CAREER_PROFILE,),
    "jd": (RetrievalSourceType.JD_ANALYSIS,),
    "jds": (RetrievalSourceType.JD_ANALYSIS,),
    "fit": (RetrievalSourceType.JOB_FIT_REPORT,),
    "fit_report": (RetrievalSourceType.JOB_FIT_REPORT,),
    "fit_reports": (RetrievalSourceType.JOB_FIT_REPORT,),
    "career_resume_profile": (RetrievalSourceType.RESUME_PROFILE,),
    "career_career_profile": (RetrievalSourceType.CAREER_PROFILE,),
    "career_jd_analysis": (RetrievalSourceType.JD_ANALYSIS,),
    "career_job_fit_report": (RetrievalSourceType.JOB_FIT_REPORT,),
    "career_resume_version": (RetrievalSourceType.RESUME_VERSION,),
    "resume_profiles": (RetrievalSourceType.RESUME_PROFILE,),
    "career_profiles": (RetrievalSourceType.CAREER_PROFILE,),
    "jd_analyses": (RetrievalSourceType.JD_ANALYSIS,),
    "job_fit_reports": (RetrievalSourceType.JOB_FIT_REPORT,),
    "resume_versions": (RetrievalSourceType.RESUME_VERSION,),
    "weakness": (RetrievalSourceType.WEAKNESS_TRACKER,),
    "weaknesses": (RetrievalSourceType.WEAKNESS_TRACKER,),
    "learning_weakness": (RetrievalSourceType.WEAKNESS_TRACKER,),
    "learning_weaknesses": (RetrievalSourceType.WEAKNESS_TRACKER,),
    "learning_weakness_tracker": (RetrievalSourceType.WEAKNESS_TRACKER,),
    "learning_weakness_trackers": (RetrievalSourceType.WEAKNESS_TRACKER,),
}


class RetrievalSearchTool:
    """Search read-only product context and current-session artifacts."""

    def __init__(self, retrieval_service: RetrievalService) -> None:
        self._retrieval_service = retrieval_service

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="retrieval_search",
            description=(
                "Search read-only Career, Note, Knowledge, Learning, and current SessionArtifact context. "
                "Use when the user refers to previous/saved/recent records without giving ids. "
                "This tool never writes products, files, or memory."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "source_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional source type filters. Accepts concrete types such as career_application, "
                            "note, learning_task, group aliases like career/notes/knowledge/learning/artifacts, "
                            "and common career aliases like career_job_fit_report."
                        ),
                    },
                    "related_application_id": {"type": "string"},
                    "top_k": {"type": "integer", "default": 8, "minimum": 1, "maximum": 50},
                    "max_chars": {"type": "integer", "default": 12000, "minimum": 200, "maximum": 50000},
                    "include_archived": {"type": "boolean", "default": False},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        request = _retrieval_query_from_arguments(arguments, run_context=run_context)
        hits = self._retrieval_service.search(request)
        payload = {
            "query": request.query,
            "session_id": run_context.session_id,
            "count": len(hits),
            "hits": [hit.to_payload() for hit in hits],
        }
        return ToolExecutionResult(
            tool_name="retrieval_search",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class RetrievalContextPackTool:
    """Build a grouped, budgeted context pack for agent consumption."""

    def __init__(self, retrieval_service: RetrievalService) -> None:
        self._retrieval_service = retrieval_service

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="retrieval_context_pack",
            description=(
                "Build a read-only, budgeted context pack grouped by Career, Note, Knowledge, Learning, "
                "and current SessionArtifact sources. Use before answering questions that depend on "
                "saved product context. This tool never writes products, files, or memory."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "source_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional source type filters. Accepts concrete types such as career_application, "
                            "note, learning_task, group aliases like career/notes/knowledge/learning/artifacts, "
                            "and common career aliases like career_job_fit_report."
                        ),
                    },
                    "related_application_id": {"type": "string"},
                    "top_k": {"type": "integer", "default": 8, "minimum": 1, "maximum": 50},
                    "max_chars": {"type": "integer", "default": 12000, "minimum": 200, "maximum": 50000},
                    "include_archived": {"type": "boolean", "default": False},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        request = _retrieval_query_from_arguments(arguments, run_context=run_context)
        pack = self._retrieval_service.build_context_pack(request)
        pack_payload = pack.to_payload(compact_grouped_context=True, compact_omitted=True)
        grouped = pack_payload["grouped_context"]
        payload = {
            "query": request.query,
            "session_id": run_context.session_id,
            "count": len(pack.hits),
            "context_char_count": pack.context_char_count(),
            "max_chars": request.max_chars,
            "omitted_count": len(pack.omitted),
            "group_counts": {group: len(items) for group, items in grouped.items()},
            "context_pack": pack_payload,
        }
        return ToolExecutionResult(
            tool_name="retrieval_context_pack",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


def _retrieval_query_from_arguments(arguments: dict[str, Any], *, run_context: RunContext) -> RetrievalQuery:
    args = _require_arguments(arguments)
    try:
        return RetrievalQuery(
            query=_required_string(args.get("query"), field_name="query"),
            session_id=run_context.session_id,
            source_types=_source_types(args.get("source_types")),
            related_application_id=_optional_string(args.get("related_application_id")),
            top_k=_optional_int(args.get("top_k"), field_name="top_k", default=8),
            max_chars=_optional_int(args.get("max_chars"), field_name="max_chars", default=12000),
            include_archived=_optional_bool(args.get("include_archived")),
        )
    except ValidationError as exc:
        raise ToolExecutionError(str(exc)) from exc


def _require_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ToolExecutionError("Tool arguments must be an object.")
    path_fields = {"path", "file_path", "workspace_path", "absolute_path", "relative_path"}
    store_owned_fields = {"created_at", "updated_at", "source_session_id", "status", "session_id"}
    for key in arguments:
        if not isinstance(key, str) or not key.strip():
            raise ToolExecutionError("Tool argument keys must be non-empty strings.")
        normalized_key = key.strip()
        if normalized_key in path_fields:
            raise ToolExecutionError(f"Path arguments are not allowed: {key}")
        if normalized_key in store_owned_fields:
            raise ToolExecutionError(f"Store-owned fields are not accepted: {key}")
        if normalized_key not in _RETRIEVAL_ARGUMENT_FIELDS:
            allowed_text = ", ".join(sorted(_RETRIEVAL_ARGUMENT_FIELDS))
            raise ToolExecutionError(f"Unsupported argument field: {key}. Allowed fields: {allowed_text}")
    return arguments


def _required_string(raw: Any, *, field_name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ToolExecutionError(f"'{field_name}' must be a non-empty string.")
    return raw.strip()


def _optional_string(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ToolExecutionError("optional string argument must be a string.")
    normalized = raw.strip()
    return normalized or None


def _source_types(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str) and raw.strip():
        raw = [raw.strip()]
    if not isinstance(raw, list):
        raise ToolExecutionError("'source_types' must be a list of strings.")
    output: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ToolExecutionError("each 'source_types' item must be a non-empty string.")
        normalized_item = item.strip().lower()
        source_types = _SOURCE_TYPE_GROUP_ALIASES.get(normalized_item)
        if source_types is None:
            try:
                source_types = (validate_source_type(item),)
            except ValidationError as exc:
                raise ToolExecutionError(str(exc)) from exc
        for source_type in source_types:
            if source_type.value in seen:
                continue
            output.append(source_type.value)
            seen.add(source_type.value)
    return output


def _optional_int(raw: Any, *, field_name: str, default: int) -> int:
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ToolExecutionError(f"'{field_name}' must be an integer.")
    return cast(int, raw)


def _optional_bool(raw: Any) -> bool:
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise ToolExecutionError("'include_archived' must be a boolean.")
    return raw
