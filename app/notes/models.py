"""Domain models for user-visible note assets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Self

from app.core.errors import ValidationError
from app.core.time import normalize_app_datetime

__all__ = [
    "Note",
    "NoteCollection",
    "NoteCollectionKind",
    "NoteRecordStatus",
    "NoteSourceRef",
    "NoteSourceType",
    "validate_artifact_id",
    "validate_collection_id",
    "validate_evidence_refs",
    "validate_note_id",
    "validate_optional_artifact_id",
    "validate_optional_collection_id",
    "validate_optional_related_application_id",
    "validate_session_id",
    "validate_source_refs",
]


class NoteRecordStatus(str, Enum):
    """Lifecycle status for note records."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class NoteCollectionKind(str, Enum):
    """Supported note collection categories."""

    GENERAL = "general"
    CAREER_PROJECT = "career_project"
    INTERVIEW = "interview"
    LEARNING = "learning"
    RESUME = "resume"
    RESOURCE = "resource"


class NoteSourceType(str, Enum):
    """Supported structured source reference types."""

    ARTIFACT = "artifact"
    CAREER_APPLICATION = "career_application"
    RESUME_PROFILE = "resume_profile"
    CAREER_PROFILE = "career_profile"
    JD_ANALYSIS = "jd_analysis"
    JOB_FIT_REPORT = "job_fit_report"
    RESUME_VERSION = "resume_version"
    CHAT_MESSAGE = "chat_message"
    MANUAL = "manual"


_ID_PATTERNS = {
    "application_id": re.compile(r"^application_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "artifact_id": re.compile(r"^artifact_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "career_profile_id": re.compile(r"^career_profile_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "chat_message_id": re.compile(r"^(chat_message|message|msg)_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "collection_id": re.compile(r"^collection_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "fit_id": re.compile(r"^fit_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "jd_id": re.compile(r"^(jd|jd_analysis)_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "note_id": re.compile(r"^note_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "resume_profile_id": re.compile(r"^resume_profile_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "resume_version_id": re.compile(r"^resume_version_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "session_ref": re.compile(r"^sess_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
}
_EVIDENCE_REF_PATTERNS = (
    _ID_PATTERNS["application_id"],
    _ID_PATTERNS["artifact_id"],
    _ID_PATTERNS["career_profile_id"],
    _ID_PATTERNS["collection_id"],
    _ID_PATTERNS["fit_id"],
    _ID_PATTERNS["jd_id"],
    _ID_PATTERNS["note_id"],
    _ID_PATTERNS["resume_profile_id"],
    _ID_PATTERNS["resume_version_id"],
    _ID_PATTERNS["session_ref"],
)
_SOURCE_TYPE_PATTERNS = {
    NoteSourceType.ARTIFACT: _ID_PATTERNS["artifact_id"],
    NoteSourceType.CAREER_APPLICATION: _ID_PATTERNS["application_id"],
    NoteSourceType.RESUME_PROFILE: _ID_PATTERNS["resume_profile_id"],
    NoteSourceType.CAREER_PROFILE: _ID_PATTERNS["career_profile_id"],
    NoteSourceType.JD_ANALYSIS: _ID_PATTERNS["jd_id"],
    NoteSourceType.JOB_FIT_REPORT: _ID_PATTERNS["fit_id"],
    NoteSourceType.RESUME_VERSION: _ID_PATTERNS["resume_version_id"],
    NoteSourceType.CHAT_MESSAGE: _ID_PATTERNS["chat_message_id"],
}


@dataclass(slots=True)
class NoteSourceRef:
    """Structured source reference for a note."""

    source_type: NoteSourceType | str
    source_id: str | None = None
    source_session_id: str | None = None
    title: str = ""
    quote: str = ""

    def __post_init__(self) -> None:
        self.source_type = _normalize_source_type(self.source_type)
        self.source_id = _normalize_source_id(self.source_type, self.source_id)
        self.source_session_id = _normalize_optional_session_id("source_session_id", self.source_session_id)
        self.title = _normalize_text("title", self.title, allow_empty=True)
        self.quote = _normalize_text("quote", self.quote, allow_empty=True)

    def copy(self) -> Self:
        return type(self)(
            source_type=self.source_type,
            source_id=self.source_id,
            source_session_id=self.source_session_id,
            title=self.title,
            quote=self.quote,
        )


@dataclass(slots=True)
class NoteCollection:
    """A user-visible collection for grouping notes."""

    collection_id: str
    status: NoteRecordStatus
    source_session_id: str
    created_at: datetime
    updated_at: datetime
    name: str
    description: str = ""
    kind: NoteCollectionKind = NoteCollectionKind.GENERAL
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.collection_id = validate_collection_id(self.collection_id)
        self.status = _normalize_status(self.status)
        self.source_session_id = validate_session_id(self.source_session_id)
        self.created_at = _normalize_datetime("created_at", self.created_at)
        self.updated_at = _normalize_datetime("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at cannot be earlier than created_at.")
        self.name = _normalize_text("name", self.name, allow_empty=False)
        self.description = _normalize_text("description", self.description, allow_empty=True)
        self.kind = _normalize_collection_kind(self.kind)
        self.tags = _normalize_string_list("tags", self.tags)

    def copy(self) -> Self:
        return type(self)(
            collection_id=self.collection_id,
            status=self.status,
            source_session_id=self.source_session_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
            name=self.name,
            description=self.description,
            kind=self.kind,
            tags=list(self.tags),
        )


@dataclass(slots=True)
class Note:
    """A user-visible, editable note product record."""

    note_id: str
    status: NoteRecordStatus
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    title: str
    body_markdown: str
    body_format: str = "markdown"
    collection_id: str | None = None
    tags: list[str] = field(default_factory=list)
    source_refs: list[NoteSourceRef] = field(default_factory=list)
    related_application_id: str | None = None
    summary: str = ""

    def __post_init__(self) -> None:
        self.note_id = validate_note_id(self.note_id)
        self.status = _normalize_status(self.status)
        self.source_session_id = validate_session_id(self.source_session_id)
        self.source_artifact_id = validate_optional_artifact_id("source_artifact_id", self.source_artifact_id)
        self.evidence_refs = validate_evidence_refs(self.evidence_refs)
        self.created_at = _normalize_datetime("created_at", self.created_at)
        self.updated_at = _normalize_datetime("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at cannot be earlier than created_at.")
        self.title = _normalize_text("title", self.title, allow_empty=False)
        self.body_markdown = _normalize_text("body_markdown", self.body_markdown, allow_empty=False)
        self.body_format = _normalize_body_format(self.body_format)
        self.collection_id = validate_optional_collection_id("collection_id", self.collection_id)
        self.tags = _normalize_string_list("tags", self.tags)
        self.source_refs = validate_source_refs(self.source_refs)
        self.related_application_id = validate_optional_related_application_id(
            "related_application_id",
            self.related_application_id,
        )
        self.summary = _normalize_text("summary", self.summary, allow_empty=True)

    def copy(self) -> Self:
        return type(self)(
            note_id=self.note_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            title=self.title,
            body_markdown=self.body_markdown,
            body_format=self.body_format,
            collection_id=self.collection_id,
            tags=list(self.tags),
            source_refs=[source_ref.copy() for source_ref in self.source_refs],
            related_application_id=self.related_application_id,
            summary=self.summary,
        )


def validate_note_id(value: str) -> str:
    return _validate_id("note_id", value, "note_id")


def validate_collection_id(value: str) -> str:
    return _validate_id("collection_id", value, "collection_id")


def validate_session_id(value: str) -> str:
    return _validate_id("source_session_id", value, "session_ref")


def validate_artifact_id(value: str) -> str:
    return _validate_id("artifact_id", value, "artifact_id")


def validate_optional_artifact_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_id(field_name, value, "artifact_id")


def validate_optional_collection_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_id(field_name, value, "collection_id")


def validate_optional_related_application_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_id(field_name, value, "application_id")


def validate_evidence_refs(values: list[str]) -> list[str]:
    refs = _normalize_string_list("evidence_refs", values)
    output: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if not any(pattern.fullmatch(ref) for pattern in _EVIDENCE_REF_PATTERNS):
            raise ValidationError(f"evidence_refs contains invalid reference format: {ref}")
        if ref in seen:
            continue
        output.append(ref)
        seen.add(ref)
    return output


def validate_source_refs(values: list[NoteSourceRef]) -> list[NoteSourceRef]:
    if not isinstance(values, list):
        raise ValidationError("source_refs must be a list.")
    output: list[NoteSourceRef] = []
    seen: set[tuple[str, str | None, str | None, str, str]] = set()
    for raw in values:
        if not isinstance(raw, NoteSourceRef):
            raise ValidationError("source_refs values must be NoteSourceRef.")
        source_ref = raw.copy()
        source_type = _source_type_value(source_ref.source_type)
        key = (
            source_type,
            source_ref.source_id,
            source_ref.source_session_id,
            source_ref.title,
            source_ref.quote,
        )
        if key in seen:
            continue
        output.append(source_ref)
        seen.add(key)
    return output


def _validate_id(field_name: str, value: str, pattern_name: str) -> str:
    normalized = _normalize_text(field_name, value, allow_empty=False)
    pattern = _ID_PATTERNS[pattern_name]
    if not pattern.fullmatch(normalized):
        raise ValidationError(f"{field_name} has invalid format: {normalized}")
    return normalized


def _normalize_status(value: NoteRecordStatus | str) -> NoteRecordStatus:
    if isinstance(value, NoteRecordStatus):
        return value
    if isinstance(value, str):
        try:
            return NoteRecordStatus(value.strip().lower())
        except ValueError as exc:
            raise ValidationError(f"status is invalid: {value}") from exc
    raise ValidationError("status must be a string.")


def _normalize_collection_kind(value: NoteCollectionKind | str) -> NoteCollectionKind:
    if isinstance(value, NoteCollectionKind):
        return value
    if isinstance(value, str):
        try:
            return NoteCollectionKind(value.strip().lower())
        except ValueError as exc:
            raise ValidationError(f"kind is invalid: {value}") from exc
    raise ValidationError("kind must be a string.")


def _normalize_source_type(value: NoteSourceType | str) -> NoteSourceType:
    if isinstance(value, NoteSourceType):
        return value
    if isinstance(value, str):
        try:
            return NoteSourceType(value.strip().lower())
        except ValueError as exc:
            raise ValidationError(f"source_type is invalid: {value}") from exc
    raise ValidationError("source_type must be a string.")


def _normalize_source_id(source_type: NoteSourceType | str, value: str | None) -> str | None:
    normalized_source_type = _normalize_source_type(source_type)
    if normalized_source_type == NoteSourceType.MANUAL:
        if value is None:
            return None
        return _normalize_text("source_id", value, allow_empty=True) or None
    if value is None:
        raise ValidationError("source_id is required unless source_type is manual.")
    normalized = _normalize_text("source_id", value, allow_empty=False)
    pattern = _SOURCE_TYPE_PATTERNS[normalized_source_type]
    if not pattern.fullmatch(normalized):
        raise ValidationError(f"source_id has invalid format for {normalized_source_type.value}: {normalized}")
    return normalized


def _normalize_optional_session_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_id(field_name, value, "session_ref")


def _normalize_body_format(value: str) -> str:
    normalized = _normalize_text("body_format", value, allow_empty=False).lower()
    if normalized != "markdown":
        raise ValidationError("body_format must be markdown.")
    return normalized


def _normalize_datetime(field_name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationError(f"{field_name} must be datetime.")
    return normalize_app_datetime(value)


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
    _ensure_json_serializable(field_name, output)
    return output


def _ensure_json_serializable(field_name: str, value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be JSON-serializable.") from exc


def _source_type_value(value: NoteSourceType | str) -> str:
    if isinstance(value, NoteSourceType):
        return value.value
    return value
