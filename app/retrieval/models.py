"""Domain models for product-context retrieval."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Self

from app.core.errors import ValidationError
from app.core.time import normalize_app_datetime, to_app_iso

__all__ = [
    "ContextPack",
    "RetrievalHit",
    "RetrievalQuery",
    "RetrievalSourceRef",
    "RetrievalSourceType",
    "group_for_source_type",
    "validate_source_type",
]


class RetrievalSourceType(str, Enum):
    """Supported source record types for retrieval hits."""

    CAREER_APPLICATION = "career_application"
    RESUME_PROFILE = "resume_profile"
    CAREER_PROFILE = "career_profile"
    JD_ANALYSIS = "jd_analysis"
    JOB_FIT_REPORT = "job_fit_report"
    RESUME_VERSION = "resume_version"
    NOTE = "note"
    NOTE_COLLECTION = "note_collection"
    EXTERNAL_RESOURCE = "external_resource"
    EXPERIENCE_POST = "experience_post"
    INTERVIEW_QUESTION = "interview_question"
    COMPANY_PROFILE = "company_profile"
    SKILL_REQUIREMENT = "skill_requirement"
    LEARNING_PLAN = "learning_plan"
    LEARNING_TASK = "learning_task"
    PROGRESS_CHECKIN = "progress_checkin"
    WEAKNESS_TRACKER = "weakness_tracker"
    REVIEW_SCHEDULE = "review_schedule"
    SESSION_ARTIFACT = "session_artifact"


_SOURCE_GROUPS = {
    RetrievalSourceType.CAREER_APPLICATION: "career",
    RetrievalSourceType.RESUME_PROFILE: "career",
    RetrievalSourceType.CAREER_PROFILE: "career",
    RetrievalSourceType.JD_ANALYSIS: "career",
    RetrievalSourceType.JOB_FIT_REPORT: "career",
    RetrievalSourceType.RESUME_VERSION: "career",
    RetrievalSourceType.NOTE: "notes",
    RetrievalSourceType.NOTE_COLLECTION: "notes",
    RetrievalSourceType.EXTERNAL_RESOURCE: "knowledge",
    RetrievalSourceType.EXPERIENCE_POST: "knowledge",
    RetrievalSourceType.INTERVIEW_QUESTION: "knowledge",
    RetrievalSourceType.COMPANY_PROFILE: "knowledge",
    RetrievalSourceType.SKILL_REQUIREMENT: "knowledge",
    RetrievalSourceType.LEARNING_PLAN: "learning",
    RetrievalSourceType.LEARNING_TASK: "learning",
    RetrievalSourceType.PROGRESS_CHECKIN: "learning",
    RetrievalSourceType.WEAKNESS_TRACKER: "learning",
    RetrievalSourceType.REVIEW_SCHEDULE: "learning",
    RetrievalSourceType.SESSION_ARTIFACT: "artifacts",
}
_SESSION_ID_PATTERN = re.compile(r"^sess_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_ARTIFACT_ID_PATTERN = re.compile(r"^artifact_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,160}$")
_GROUP_NAMES = ("career", "notes", "knowledge", "learning", "artifacts")


@dataclass(slots=True)
class RetrievalSourceRef:
    """Typed reference to the source record behind one retrieval hit."""

    source_type: RetrievalSourceType | str
    source_id: str
    source_session_id: str | None = None
    artifact_id: str | None = None

    def __post_init__(self) -> None:
        self.source_type = validate_source_type(self.source_type)
        self.source_id = _normalize_source_id(self.source_id)
        self.source_session_id = _normalize_optional_session_id("source_session_id", self.source_session_id)
        self.artifact_id = _normalize_optional_artifact_id("artifact_id", self.artifact_id)

    def copy(self) -> Self:
        return type(self)(
            source_type=self.source_type,
            source_id=self.source_id,
            source_session_id=self.source_session_id,
            artifact_id=self.artifact_id,
        )

    def to_payload(self) -> dict[str, Any]:
        source_type = validate_source_type(self.source_type)
        return {
            "artifact_id": self.artifact_id,
            "source_id": self.source_id,
            "source_session_id": self.source_session_id,
            "source_type": source_type.value,
        }


@dataclass(slots=True)
class RetrievalHit:
    """One ranked, traceable retrieval match."""

    source: RetrievalSourceRef
    title: str
    summary: str
    snippet: str
    tags: list[str]
    score: float
    match_reason: str
    updated_at: datetime
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.source, RetrievalSourceRef):
            raise ValidationError("source must be RetrievalSourceRef.")
        self.source = self.source.copy()
        self.title = _normalize_text("title", self.title, allow_empty=False)
        self.summary = _normalize_text("summary", self.summary, allow_empty=True)
        self.snippet = _normalize_text("snippet", self.snippet, allow_empty=True)
        self.tags = _normalize_string_list("tags", self.tags)
        self.score = _normalize_score(self.score)
        self.match_reason = _normalize_text("match_reason", self.match_reason, allow_empty=True)
        self.updated_at = _normalize_datetime("updated_at", self.updated_at)
        self.evidence_refs = _normalize_string_list("evidence_refs", self.evidence_refs)
        self.metadata = _normalize_metadata(self.metadata)

    def copy(self) -> Self:
        return type(self)(
            source=self.source.copy(),
            title=self.title,
            summary=self.summary,
            snippet=self.snippet,
            tags=list(self.tags),
            score=self.score,
            match_reason=self.match_reason,
            updated_at=self.updated_at,
            evidence_refs=list(self.evidence_refs),
            metadata=deepcopy(self.metadata),
        )

    def content_length(self) -> int:
        return len(self.title) + len(self.summary) + len(self.snippet)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "evidence_refs": list(self.evidence_refs),
            "match_reason": self.match_reason,
            "score": self.score,
            "snippet": self.snippet,
            "source": self.source.to_payload(),
            "summary": self.summary,
            "tags": list(self.tags),
            "title": self.title,
            "updated_at": to_app_iso(self.updated_at),
        }
        if self.metadata:
            payload["metadata"] = deepcopy(self.metadata)
        return payload


@dataclass(slots=True)
class RetrievalQuery:
    """Normalized input for retrieval search and context packing."""

    query: str
    session_id: str
    source_types: list[Any] = field(default_factory=list)
    related_application_id: str | None = None
    top_k: int = 8
    max_chars: int = 12000
    max_snippet_chars: int = 1200
    per_source_type_limit: int = 3
    include_archived: bool = False

    def __post_init__(self) -> None:
        self.query = _normalize_text("query", self.query, allow_empty=True)
        self.session_id = _normalize_session_id("session_id", self.session_id)
        self.source_types = _normalize_source_types(self.source_types)
        self.related_application_id = _normalize_optional_safe_id(
            "related_application_id",
            self.related_application_id,
        )
        self.top_k = _normalize_int_range("top_k", self.top_k, min_value=1, max_value=50)
        self.max_chars = _normalize_int_range("max_chars", self.max_chars, min_value=200, max_value=50000)
        self.max_snippet_chars = _normalize_int_range(
            "max_snippet_chars",
            self.max_snippet_chars,
            min_value=80,
            max_value=5000,
        )
        self.per_source_type_limit = _normalize_int_range(
            "per_source_type_limit",
            self.per_source_type_limit,
            min_value=1,
            max_value=20,
        )
        if not isinstance(self.include_archived, bool):
            raise ValidationError("include_archived must be bool.")

    def allows(self, source_type: RetrievalSourceType) -> bool:
        return not self.source_types or source_type in self.source_types


@dataclass(slots=True)
class ContextPack:
    """Budgeted retrieval context prepared for agent consumption."""

    query: str
    hits: list[RetrievalHit]
    grouped_context: dict[str, list[RetrievalHit]]
    citations: list[RetrievalSourceRef]
    omitted: list[RetrievalHit] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.query = _normalize_text("query", self.query, allow_empty=True)
        self.hits = _normalize_hits("hits", self.hits)
        self.grouped_context = _normalize_grouped_context(self.grouped_context)
        self.citations = _normalize_citations(self.citations)
        self.omitted = _normalize_hits("omitted", self.omitted)

    def to_payload(self) -> dict[str, Any]:
        return {
            "citations": [citation.to_payload() for citation in self.citations],
            "grouped_context": {
                group: [hit.to_payload() for hit in hits]
                for group, hits in self.grouped_context.items()
            },
            "hits": [hit.to_payload() for hit in self.hits],
            "omitted": [hit.to_payload() for hit in self.omitted],
            "query": self.query,
        }


def validate_source_type(value: RetrievalSourceType | str) -> RetrievalSourceType:
    if isinstance(value, RetrievalSourceType):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        try:
            return RetrievalSourceType(normalized)
        except ValueError as exc:
            raise ValidationError(f"source_type is invalid: {value}") from exc
    raise ValidationError("source_type must be a string.")


def group_for_source_type(source_type: RetrievalSourceType | str) -> str:
    return _SOURCE_GROUPS[validate_source_type(source_type)]


def _normalize_source_id(value: str) -> str:
    normalized = _normalize_text("source_id", value, allow_empty=False)
    if "/" in normalized or "\\" in normalized or ".." in normalized:
        raise ValidationError("source_id must not contain path segments.")
    if not _SAFE_ID_PATTERN.fullmatch(normalized):
        raise ValidationError(f"source_id has invalid format: {normalized}")
    return normalized


def _normalize_session_id(field_name: str, value: str) -> str:
    normalized = _normalize_text(field_name, value, allow_empty=False)
    if not _SESSION_ID_PATTERN.fullmatch(normalized):
        raise ValidationError(f"{field_name} has invalid format: {normalized}")
    return normalized


def _normalize_optional_session_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _normalize_session_id(field_name, value)


def _normalize_optional_artifact_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _normalize_text(field_name, value, allow_empty=False)
    if not _ARTIFACT_ID_PATTERN.fullmatch(normalized):
        raise ValidationError(f"{field_name} has invalid format: {normalized}")
    return normalized


def _normalize_source_types(values: list[RetrievalSourceType | str]) -> list[RetrievalSourceType]:
    if not isinstance(values, list):
        raise ValidationError("source_types must be a list.")
    output: list[RetrievalSourceType] = []
    seen: set[RetrievalSourceType] = set()
    for raw in values:
        source_type = validate_source_type(raw)
        if source_type in seen:
            continue
        output.append(source_type)
        seen.add(source_type)
    return output


def _normalize_optional_safe_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _normalize_text(field_name, value, allow_empty=False)
    if "/" in normalized or "\\" in normalized or ".." in normalized:
        raise ValidationError(f"{field_name} must not contain path segments.")
    if not re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,160}$").fullmatch(normalized):
        raise ValidationError(f"{field_name} has invalid format: {normalized}")
    return normalized


def _normalize_text(field_name: str, value: str, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string.")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return normalized


def _normalize_string_list(field_name: str, values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(f"{field_name} must be a list.")
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = _normalize_text(field_name, raw, allow_empty=False)
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _normalize_metadata(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("metadata must be dict.")
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError("metadata must be JSON serializable.") from exc
    return deepcopy(value)


def _normalize_score(value: float) -> float:
    if not isinstance(value, int | float):
        raise ValidationError("score must be a number.")
    normalized = float(value)
    if normalized < 0 or normalized > 1:
        raise ValidationError("score must be in range 0..1.")
    return round(normalized, 4)


def _normalize_datetime(field_name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationError(f"{field_name} must be datetime.")
    return normalize_app_datetime(value)


def _normalize_int_range(field_name: str, value: int, *, min_value: int, max_value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{field_name} must be int.")
    if value < min_value or value > max_value:
        raise ValidationError(f"{field_name} must be in range {min_value}..{max_value}.")
    return value


def _normalize_hits(field_name: str, values: list[RetrievalHit]) -> list[RetrievalHit]:
    if not isinstance(values, list):
        raise ValidationError(f"{field_name} must be a list.")
    output: list[RetrievalHit] = []
    for raw in values:
        if not isinstance(raw, RetrievalHit):
            raise ValidationError(f"{field_name} entries must be RetrievalHit.")
        output.append(raw.copy())
    return output


def _normalize_grouped_context(values: dict[str, list[RetrievalHit]]) -> dict[str, list[RetrievalHit]]:
    if not isinstance(values, dict):
        raise ValidationError("grouped_context must be a dict.")
    output: dict[str, list[RetrievalHit]] = {group: [] for group in _GROUP_NAMES}
    for raw_group, hits in values.items():
        group = _normalize_text("group", str(raw_group), allow_empty=False)
        if group not in output:
            raise ValidationError(f"grouped_context contains invalid group: {group}")
        output[group] = _normalize_hits(f"grouped_context.{group}", hits)
    return output


def _normalize_citations(values: list[RetrievalSourceRef]) -> list[RetrievalSourceRef]:
    if not isinstance(values, list):
        raise ValidationError("citations must be a list.")
    output: list[RetrievalSourceRef] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for raw in values:
        if not isinstance(raw, RetrievalSourceRef):
            raise ValidationError("citations entries must be RetrievalSourceRef.")
        item = raw.copy()
        key = (validate_source_type(item.source_type).value, item.source_id, item.source_session_id, item.artifact_id)
        if key in seen:
            continue
        output.append(item)
        seen.add(key)
    return output
