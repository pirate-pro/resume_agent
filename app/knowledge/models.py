"""Domain models for external career knowledge assets."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Self, TypeVar

from app.core.errors import ValidationError
from app.core.time import normalize_app_datetime

__all__ = [
    "CompanyProfile",
    "ExperiencePost",
    "ExternalResource",
    "InterviewDifficulty",
    "InterviewQuestion",
    "KnowledgeRecordStatus",
    "QuestionType",
    "ResourceType",
    "SkillCategory",
    "SkillLevel",
    "SkillRequirement",
    "validate_artifact_id",
    "validate_company_id",
    "validate_evidence_refs",
    "validate_experience_id",
    "validate_optional_artifact_id",
    "validate_optional_company_id",
    "validate_optional_experience_id",
    "validate_optional_resource_id",
    "validate_question_id",
    "validate_resource_id",
    "validate_session_id",
    "validate_skill_requirement_id",
]

_EnumT = TypeVar("_EnumT", bound=Enum)


class KnowledgeRecordStatus(str, Enum):
    """Lifecycle status for knowledge records."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class ResourceType(str, Enum):
    """Supported external resource types."""

    LINK = "link"
    PASTED_TEXT = "pasted_text"
    UPLOADED_FILE = "uploaded_file"
    ARTICLE = "article"
    COURSE = "course"
    VIDEO = "video"
    REPO = "repo"
    BOOK = "book"
    OTHER = "other"


class InterviewDifficulty(str, Enum):
    """Interview question or experience difficulty."""

    UNKNOWN = "unknown"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class QuestionType(str, Enum):
    """Supported interview question types."""

    BEHAVIORAL = "behavioral"
    TECHNICAL = "technical"
    SYSTEM_DESIGN = "system_design"
    CODING = "coding"
    PROJECT_DEEP_DIVE = "project_deep_dive"
    HR = "hr"
    COMPANY_SPECIFIC = "company_specific"
    OTHER = "other"


class SkillCategory(str, Enum):
    """Supported skill requirement categories."""

    LANGUAGE = "language"
    FRAMEWORK = "framework"
    DATABASE = "database"
    SYSTEM_DESIGN = "system_design"
    AI = "ai"
    RAG = "rag"
    AGENT = "agent"
    DEVOPS = "devops"
    TESTING = "testing"
    SOFT_SKILL = "soft_skill"
    OTHER = "other"


class SkillLevel(str, Enum):
    """Supported skill requirement levels."""

    AWARENESS = "awareness"
    BASIC = "basic"
    WORKING = "working"
    STRONG = "strong"
    EXPERT = "expert"


_ID_PATTERNS = {
    "application_id": re.compile(r"^application_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "artifact_id": re.compile(r"^artifact_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "career_profile_id": re.compile(r"^career_profile_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "company_id": re.compile(r"^company_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "experience_id": re.compile(r"^experience_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "fit_id": re.compile(r"^fit_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "jd_id": re.compile(r"^(jd|jd_analysis)_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "note_id": re.compile(r"^note_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "question_id": re.compile(r"^question_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "resource_id": re.compile(r"^resource_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "resume_profile_id": re.compile(r"^resume_profile_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "session_ref": re.compile(r"^sess_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "skill_requirement_id": re.compile(r"^skill_req_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
}
_EVIDENCE_REF_PATTERNS = (
    _ID_PATTERNS["application_id"],
    _ID_PATTERNS["artifact_id"],
    _ID_PATTERNS["career_profile_id"],
    _ID_PATTERNS["company_id"],
    _ID_PATTERNS["experience_id"],
    _ID_PATTERNS["fit_id"],
    _ID_PATTERNS["jd_id"],
    _ID_PATTERNS["note_id"],
    _ID_PATTERNS["question_id"],
    _ID_PATTERNS["resource_id"],
    _ID_PATTERNS["resume_profile_id"],
    _ID_PATTERNS["session_ref"],
    _ID_PATTERNS["skill_requirement_id"],
)


@dataclass(slots=True)
class ExternalResource:
    """A user-visible external resource saved for career preparation."""

    resource_id: str
    status: KnowledgeRecordStatus
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    title: str
    resource_type: ResourceType | str
    url: str | None = None
    provider: str = ""
    company: str = ""
    position: str = ""
    target_roles: list[str] = field(default_factory=list)
    skill_tags: list[str] = field(default_factory=list)
    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    raw_artifact_id: str | None = None
    related_application_ids: list[str] = field(default_factory=list)
    related_note_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.resource_id = validate_resource_id(self.resource_id)
        _normalize_record_metadata(self)
        self.title = _normalize_text("title", self.title, allow_empty=False)
        self.resource_type = _normalize_enum("resource_type", self.resource_type, ResourceType)
        self.url = _normalize_optional_text("url", self.url)
        self.provider = _normalize_text("provider", self.provider, allow_empty=True)
        self.company = _normalize_text("company", self.company, allow_empty=True)
        self.position = _normalize_text("position", self.position, allow_empty=True)
        self.target_roles = _normalize_string_list("target_roles", self.target_roles)
        self.skill_tags = _normalize_string_list("skill_tags", self.skill_tags)
        self.summary = _normalize_text("summary", self.summary, allow_empty=True)
        self.key_points = _normalize_string_list("key_points", self.key_points)
        self.raw_artifact_id = validate_optional_artifact_id("raw_artifact_id", self.raw_artifact_id)
        self.related_application_ids = _normalize_id_list(
            "related_application_ids",
            self.related_application_ids,
            "application_id",
        )
        self.related_note_ids = _normalize_id_list("related_note_ids", self.related_note_ids, "note_id")

    def copy(self) -> Self:
        return type(self)(
            resource_id=self.resource_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            title=self.title,
            resource_type=self.resource_type,
            url=self.url,
            provider=self.provider,
            company=self.company,
            position=self.position,
            target_roles=list(self.target_roles),
            skill_tags=list(self.skill_tags),
            summary=self.summary,
            key_points=list(self.key_points),
            raw_artifact_id=self.raw_artifact_id,
            related_application_ids=list(self.related_application_ids),
            related_note_ids=list(self.related_note_ids),
        )


@dataclass(slots=True)
class ExperiencePost:
    """A structured interview experience post."""

    experience_id: str
    status: KnowledgeRecordStatus
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    source_resource_id: str | None = None
    company: str = ""
    position: str = ""
    seniority: str = ""
    interview_rounds: list[Any] = field(default_factory=list)
    interview_process: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    outcome: str = ""
    difficulty: InterviewDifficulty | str = InterviewDifficulty.UNKNOWN
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    related_application_ids: list[str] = field(default_factory=list)
    related_note_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.experience_id = validate_experience_id(self.experience_id)
        _normalize_record_metadata(self)
        self.source_resource_id = validate_optional_resource_id("source_resource_id", self.source_resource_id)
        self.company = _normalize_text("company", self.company, allow_empty=True)
        self.position = _normalize_text("position", self.position, allow_empty=True)
        self.seniority = _normalize_text("seniority", self.seniority, allow_empty=True)
        self.interview_rounds = _normalize_json_list("interview_rounds", self.interview_rounds)
        self.interview_process = _normalize_string_list("interview_process", self.interview_process)
        self.questions = _normalize_string_list("questions", self.questions)
        self.outcome = _normalize_text("outcome", self.outcome, allow_empty=True)
        self.difficulty = _normalize_enum("difficulty", self.difficulty, InterviewDifficulty)
        self.summary = _normalize_text("summary", self.summary, allow_empty=True)
        self.tags = _normalize_string_list("tags", self.tags)
        self.related_application_ids = _normalize_id_list(
            "related_application_ids",
            self.related_application_ids,
            "application_id",
        )
        self.related_note_ids = _normalize_id_list("related_note_ids", self.related_note_ids, "note_id")

    def copy(self) -> Self:
        return type(self)(
            experience_id=self.experience_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            source_resource_id=self.source_resource_id,
            company=self.company,
            position=self.position,
            seniority=self.seniority,
            interview_rounds=deepcopy(self.interview_rounds),
            interview_process=list(self.interview_process),
            questions=list(self.questions),
            outcome=self.outcome,
            difficulty=self.difficulty,
            summary=self.summary,
            tags=list(self.tags),
            related_application_ids=list(self.related_application_ids),
            related_note_ids=list(self.related_note_ids),
        )


@dataclass(slots=True)
class InterviewQuestion:
    """A reusable interview question record."""

    question_id: str
    status: KnowledgeRecordStatus
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    question_text: str
    question_type: QuestionType | str
    difficulty: InterviewDifficulty | str = InterviewDifficulty.UNKNOWN
    skill_tags: list[str] = field(default_factory=list)
    company: str = ""
    position: str = ""
    source_resource_id: str | None = None
    source_experience_id: str | None = None
    answer_outline: str = ""
    evaluation_points: list[str] = field(default_factory=list)
    common_pitfalls: list[str] = field(default_factory=list)
    related_application_ids: list[str] = field(default_factory=list)
    related_note_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.question_id = validate_question_id(self.question_id)
        _normalize_record_metadata(self)
        self.question_text = _normalize_text("question_text", self.question_text, allow_empty=False)
        self.question_type = _normalize_enum("question_type", self.question_type, QuestionType)
        self.difficulty = _normalize_enum("difficulty", self.difficulty, InterviewDifficulty)
        self.skill_tags = _normalize_string_list("skill_tags", self.skill_tags)
        self.company = _normalize_text("company", self.company, allow_empty=True)
        self.position = _normalize_text("position", self.position, allow_empty=True)
        self.source_resource_id = validate_optional_resource_id("source_resource_id", self.source_resource_id)
        self.source_experience_id = validate_optional_experience_id(
            "source_experience_id",
            self.source_experience_id,
        )
        self.answer_outline = _normalize_text("answer_outline", self.answer_outline, allow_empty=True)
        self.evaluation_points = _normalize_string_list("evaluation_points", self.evaluation_points)
        self.common_pitfalls = _normalize_string_list("common_pitfalls", self.common_pitfalls)
        self.related_application_ids = _normalize_id_list(
            "related_application_ids",
            self.related_application_ids,
            "application_id",
        )
        self.related_note_ids = _normalize_id_list("related_note_ids", self.related_note_ids, "note_id")

    def copy(self) -> Self:
        return type(self)(
            question_id=self.question_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            question_text=self.question_text,
            question_type=self.question_type,
            difficulty=self.difficulty,
            skill_tags=list(self.skill_tags),
            company=self.company,
            position=self.position,
            source_resource_id=self.source_resource_id,
            source_experience_id=self.source_experience_id,
            answer_outline=self.answer_outline,
            evaluation_points=list(self.evaluation_points),
            common_pitfalls=list(self.common_pitfalls),
            related_application_ids=list(self.related_application_ids),
            related_note_ids=list(self.related_note_ids),
        )


@dataclass(slots=True)
class CompanyProfile:
    """A public career-preparation profile for one company."""

    company_id: str
    status: KnowledgeRecordStatus
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    company_name: str
    aliases: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    target_roles: list[str] = field(default_factory=list)
    hiring_signals: list[str] = field(default_factory=list)
    interview_style: str = ""
    common_questions: list[str] = field(default_factory=list)
    resource_ids: list[str] = field(default_factory=list)
    question_ids: list[str] = field(default_factory=list)
    summary: str = ""

    def __post_init__(self) -> None:
        self.company_id = validate_company_id(self.company_id)
        _normalize_record_metadata(self)
        self.company_name = _normalize_text("company_name", self.company_name, allow_empty=False)
        self.aliases = _normalize_string_list("aliases", self.aliases)
        self.industries = _normalize_string_list("industries", self.industries)
        self.target_roles = _normalize_string_list("target_roles", self.target_roles)
        self.hiring_signals = _normalize_string_list("hiring_signals", self.hiring_signals)
        self.interview_style = _normalize_text("interview_style", self.interview_style, allow_empty=True)
        self.common_questions = _normalize_string_list("common_questions", self.common_questions)
        self.resource_ids = _normalize_id_list("resource_ids", self.resource_ids, "resource_id")
        self.question_ids = _normalize_id_list("question_ids", self.question_ids, "question_id")
        self.summary = _normalize_text("summary", self.summary, allow_empty=True)

    def copy(self) -> Self:
        return type(self)(
            company_id=self.company_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            company_name=self.company_name,
            aliases=list(self.aliases),
            industries=list(self.industries),
            target_roles=list(self.target_roles),
            hiring_signals=list(self.hiring_signals),
            interview_style=self.interview_style,
            common_questions=list(self.common_questions),
            resource_ids=list(self.resource_ids),
            question_ids=list(self.question_ids),
            summary=self.summary,
        )


@dataclass(slots=True)
class SkillRequirement:
    """A reusable target-role skill requirement."""

    skill_requirement_id: str
    status: KnowledgeRecordStatus
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    skill_name: str
    category: SkillCategory | str
    level: SkillLevel | str
    description: str = ""
    assessment_points: list[str] = field(default_factory=list)
    role_tags: list[str] = field(default_factory=list)
    company_ids: list[str] = field(default_factory=list)
    resource_ids: list[str] = field(default_factory=list)
    question_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.skill_requirement_id = validate_skill_requirement_id(self.skill_requirement_id)
        _normalize_record_metadata(self)
        self.skill_name = _normalize_text("skill_name", self.skill_name, allow_empty=False)
        self.category = _normalize_enum("category", self.category, SkillCategory)
        self.level = _normalize_enum("level", self.level, SkillLevel)
        self.description = _normalize_text("description", self.description, allow_empty=True)
        self.assessment_points = _normalize_string_list("assessment_points", self.assessment_points)
        self.role_tags = _normalize_string_list("role_tags", self.role_tags)
        self.company_ids = _normalize_id_list("company_ids", self.company_ids, "company_id")
        self.resource_ids = _normalize_id_list("resource_ids", self.resource_ids, "resource_id")
        self.question_ids = _normalize_id_list("question_ids", self.question_ids, "question_id")

    def copy(self) -> Self:
        return type(self)(
            skill_requirement_id=self.skill_requirement_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            skill_name=self.skill_name,
            category=self.category,
            level=self.level,
            description=self.description,
            assessment_points=list(self.assessment_points),
            role_tags=list(self.role_tags),
            company_ids=list(self.company_ids),
            resource_ids=list(self.resource_ids),
            question_ids=list(self.question_ids),
        )


def validate_resource_id(value: str) -> str:
    return _validate_id("resource_id", value, "resource_id")


def validate_experience_id(value: str) -> str:
    return _validate_id("experience_id", value, "experience_id")


def validate_question_id(value: str) -> str:
    return _validate_id("question_id", value, "question_id")


def validate_company_id(value: str) -> str:
    return _validate_id("company_id", value, "company_id")


def validate_skill_requirement_id(value: str) -> str:
    return _validate_id("skill_requirement_id", value, "skill_requirement_id")


def validate_session_id(value: str) -> str:
    return _validate_id("source_session_id", value, "session_ref")


def validate_artifact_id(value: str) -> str:
    return _validate_id("artifact_id", value, "artifact_id")


def validate_optional_artifact_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_id(field_name, value, "artifact_id")


def validate_optional_resource_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_id(field_name, value, "resource_id")


def validate_optional_experience_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_id(field_name, value, "experience_id")


def validate_optional_company_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_id(field_name, value, "company_id")


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


def _normalize_record_metadata(record: Any) -> None:
    record.status = _normalize_enum("status", record.status, KnowledgeRecordStatus)
    record.source_session_id = validate_session_id(record.source_session_id)
    record.source_artifact_id = validate_optional_artifact_id("source_artifact_id", record.source_artifact_id)
    record.evidence_refs = validate_evidence_refs(record.evidence_refs)
    record.created_at = _normalize_datetime("created_at", record.created_at)
    record.updated_at = _normalize_datetime("updated_at", record.updated_at)
    if record.updated_at < record.created_at:
        raise ValidationError("updated_at cannot be earlier than created_at.")


def _validate_id(field_name: str, value: str, pattern_name: str) -> str:
    normalized = _normalize_text(field_name, value, allow_empty=False)
    pattern = _ID_PATTERNS[pattern_name]
    if not pattern.fullmatch(normalized):
        raise ValidationError(f"{field_name} has invalid format: {normalized}")
    return normalized


def _normalize_enum(field_name: str, value: _EnumT | str, enum_type: type[_EnumT]) -> _EnumT:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        try:
            return enum_type(normalized)
        except ValueError as exc:
            raise ValidationError(f"{field_name} is invalid: {value}") from exc
    raise ValidationError(f"{field_name} must be a string.")


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


def _normalize_optional_text(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _normalize_text(field_name, value, allow_empty=True)
    return normalized or None


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


def _normalize_json_list(field_name: str, values: list[Any]) -> list[Any]:
    if not isinstance(values, list):
        raise ValidationError(f"{field_name} must be a list.")
    output = deepcopy(values)
    _ensure_json_serializable(field_name, output)
    return output


def _normalize_id_list(field_name: str, values: list[str], pattern_name: str) -> list[str]:
    refs = _normalize_string_list(field_name, values)
    output: list[str] = []
    seen: set[str] = set()
    pattern = _ID_PATTERNS[pattern_name]
    for ref in refs:
        if not pattern.fullmatch(ref):
            raise ValidationError(f"{field_name} contains invalid reference format: {ref}")
        if ref in seen:
            continue
        output.append(ref)
        seen.add(ref)
    return output


def _ensure_json_serializable(field_name: str, value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be JSON-serializable.") from exc
