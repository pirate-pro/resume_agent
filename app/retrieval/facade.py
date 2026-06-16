"""Shared facade for retrieval tool adapters."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, cast

from app.core.errors import ValidationError
from app.retrieval.models import RetrievalQuery, RetrievalSourceType, validate_source_type
from app.retrieval.service import RetrievalService

__all__ = [
    "RetrievalPrincipal",
    "RetrievalToolInput",
    "build_retrieval_query",
    "retrieval_context_pack_payload",
    "retrieval_search_payload",
    "retrieval_tool_input_from_arguments",
    "retrieval_tool_parameters_schema",
]

_DEFAULT_EXTERNAL_SESSION_ID = "sess_external_no_session"
_RETRIEVAL_ARGUMENT_FIELDS = {
    "query",
    "source_types",
    "related_application_id",
    "top_k",
    "max_chars",
    "include_archived",
}
_PATH_FIELDS = {"path", "file_path", "workspace_path", "absolute_path", "relative_path"}
_STORE_OWNED_FIELDS = {"created_at", "updated_at", "source_session_id", "status", "session_id"}
_NON_APPLICATION_REF_PREFIXES = (
    "artifact_",
    "career_profile_",
    "fit_",
    "jd_",
    "job_fit_report_",
    "learning_task_",
    "note_",
    "resume_profile_",
    "resume_version_",
)
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
    "match_report": (RetrievalSourceType.JOB_FIT_REPORT,),
    "match_reports": (RetrievalSourceType.JOB_FIT_REPORT,),
    "career_resume_profile": (RetrievalSourceType.RESUME_PROFILE,),
    "career_career_profile": (RetrievalSourceType.CAREER_PROFILE,),
    "career_jd_analysis": (RetrievalSourceType.JD_ANALYSIS,),
    "career_job_fit_report": (RetrievalSourceType.JOB_FIT_REPORT,),
    "career_match_report": (RetrievalSourceType.JOB_FIT_REPORT,),
    "career_match_reports": (RetrievalSourceType.JOB_FIT_REPORT,),
    "career_project": (RetrievalSourceType.CAREER_APPLICATION,),
    "career_projects": (RetrievalSourceType.CAREER_APPLICATION,),
    "career_application_project": (RetrievalSourceType.CAREER_APPLICATION,),
    "career_application_projects": (RetrievalSourceType.CAREER_APPLICATION,),
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
_RETRIEVAL_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
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
}


@dataclass(slots=True)
class RetrievalPrincipal:
    """Server-owned retrieval caller context."""

    session_id: str | None
    owner_user_id: str = "user_local"
    workspace_id: str = "workspace_default"


@dataclass(slots=True)
class RetrievalToolInput:
    """Normalized retrieval tool input surface."""

    query: str
    source_types: list[Any] = field(default_factory=list)
    related_application_id: str | None = None
    top_k: int = 8
    max_chars: int = 12000
    include_archived: bool = False


def retrieval_tool_parameters_schema() -> dict[str, Any]:
    """Return the JSON schema shared by built-in and MCP retrieval tools."""

    return deepcopy(_RETRIEVAL_TOOL_PARAMETERS_SCHEMA)


def retrieval_tool_input_from_arguments(arguments: dict[str, Any]) -> RetrievalToolInput:
    """Validate raw tool arguments and return a typed retrieval input."""

    args = _require_arguments(arguments)
    return RetrievalToolInput(
        query=_required_string(args.get("query"), field_name="query"),
        source_types=_source_types(args.get("source_types")),
        related_application_id=_optional_related_application_id(args.get("related_application_id")),
        top_k=_optional_int(args.get("top_k"), field_name="top_k", default=8),
        max_chars=_optional_int(args.get("max_chars"), field_name="max_chars", default=12000),
        include_archived=_optional_bool(args.get("include_archived")),
    )


def build_retrieval_query(tool_input: RetrievalToolInput, *, principal: RetrievalPrincipal) -> RetrievalQuery:
    """Build a service-level retrieval query from a tool input and server-owned context."""

    source_types = _source_types(tool_input.source_types)
    if principal.session_id is None and RetrievalSourceType.SESSION_ARTIFACT.value in source_types:
        raise ValidationError("session_artifact retrieval requires an app session.")
    if principal.session_id is None and not source_types:
        source_types = [
            source_type.value
            for source_type in RetrievalSourceType
            if source_type != RetrievalSourceType.SESSION_ARTIFACT
        ]
    return RetrievalQuery(
        query=_required_string(tool_input.query, field_name="query"),
        session_id=principal.session_id or _DEFAULT_EXTERNAL_SESSION_ID,
        source_types=source_types,
        related_application_id=_optional_related_application_id(tool_input.related_application_id),
        top_k=_optional_int(tool_input.top_k, field_name="top_k", default=8),
        max_chars=_optional_int(tool_input.max_chars, field_name="max_chars", default=12000),
        include_archived=_optional_bool(tool_input.include_archived),
    )


def retrieval_search_payload(
    retrieval_service: RetrievalService,
    tool_input: RetrievalToolInput,
    *,
    principal: RetrievalPrincipal,
    include_session_id: bool = False,
) -> dict[str, Any]:
    """Return the structured payload for a retrieval search tool call."""

    request = build_retrieval_query(tool_input, principal=principal)
    hits = retrieval_service.search(request)
    payload: dict[str, Any] = {
        "query": request.query,
        "count": len(hits),
        "hits": [hit.to_payload() for hit in hits],
    }
    if include_session_id:
        payload["session_id"] = request.session_id
    return payload


def retrieval_context_pack_payload(
    retrieval_service: RetrievalService,
    tool_input: RetrievalToolInput,
    *,
    principal: RetrievalPrincipal,
    include_session_id: bool = False,
) -> dict[str, Any]:
    """Return the structured payload for a retrieval context pack tool call."""

    request = build_retrieval_query(tool_input, principal=principal)
    pack = retrieval_service.build_context_pack(request)
    pack_payload = pack.to_payload(compact_grouped_context=True, compact_omitted=True)
    grouped = pack_payload["grouped_context"]
    payload: dict[str, Any] = {
        "query": request.query,
        "count": len(pack.hits),
        "context_char_count": pack.context_char_count(),
        "max_chars": request.max_chars,
        "omitted_count": len(pack.omitted),
        "group_counts": {group: len(items) for group, items in grouped.items()},
        "context_pack": pack_payload,
    }
    if include_session_id:
        payload["session_id"] = request.session_id
    return payload


def _require_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValidationError("Tool arguments must be an object.")
    for key in arguments:
        if not isinstance(key, str) or not key.strip():
            raise ValidationError("Tool argument keys must be non-empty strings.")
        normalized_key = key.strip()
        if normalized_key in _PATH_FIELDS:
            raise ValidationError(f"Path arguments are not allowed: {key}")
        if normalized_key in _STORE_OWNED_FIELDS:
            raise ValidationError(f"Store-owned fields are not accepted: {key}")
        if normalized_key not in _RETRIEVAL_ARGUMENT_FIELDS:
            allowed_text = ", ".join(sorted(_RETRIEVAL_ARGUMENT_FIELDS))
            raise ValidationError(f"Unsupported argument field: {key}. Allowed fields: {allowed_text}")
    return arguments


def _required_string(raw: Any, *, field_name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError(f"'{field_name}' must be a non-empty string.")
    return raw.strip()


def _optional_string(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValidationError("optional string argument must be a string.")
    normalized = raw.strip()
    return normalized or None


def _optional_related_application_id(raw: Any) -> str | None:
    normalized = _optional_string(raw)
    if normalized is None:
        return None
    if normalized.startswith("application_"):
        return normalized
    if normalized.startswith(_NON_APPLICATION_REF_PREFIXES):
        return None
    raise ValidationError("'related_application_id' must be an application_* id.")


def _source_types(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str) and raw.strip():
        raw = [raw.strip()]
    if not isinstance(raw, list):
        raise ValidationError("'source_types' must be a list of strings.")
    output: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError("each 'source_types' item must be a non-empty string.")
        normalized_item = item.strip().lower()
        source_types = _SOURCE_TYPE_GROUP_ALIASES.get(normalized_item)
        if source_types is None:
            source_types = (validate_source_type(item),)
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
        raise ValidationError(f"'{field_name}' must be an integer.")
    return cast(int, raw)


def _optional_bool(raw: Any) -> bool:
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise ValidationError("'include_archived' must be a boolean.")
    return raw
