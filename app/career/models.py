"""Domain models for durable career product assets."""

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
    "CareerApplication",
    "CareerProfile",
    "CareerRecordStatus",
    "JDAnalysis",
    "JobFitReport",
    "ResumeProfile",
    "ResumeVersion",
    "validate_application_id",
    "validate_artifact_id",
    "validate_career_profile_id",
    "validate_evidence_refs",
    "validate_fit_id",
    "validate_jd_id",
    "validate_resume_profile_id",
    "validate_resume_version_id",
    "validate_session_id",
]


class CareerRecordStatus(str, Enum):
    """Lifecycle status for career product records."""

    ACTIVE = "active"
    ARCHIVED = "archived"


_ID_PATTERNS = {
    "application_id": re.compile(r"^application_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "artifact_id": re.compile(r"^artifact_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "career_profile_id": re.compile(r"^career_profile_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "fit_id": re.compile(r"^fit_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "jd_id": re.compile(r"^jd_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "note_id": re.compile(r"^note_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "resume_profile_id": re.compile(r"^resume_profile_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "resume_version_id": re.compile(r"^resume_version_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "session_ref": re.compile(r"^sess_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
}
_EVIDENCE_REF_PATTERNS = (
    _ID_PATTERNS["application_id"],
    _ID_PATTERNS["artifact_id"],
    _ID_PATTERNS["career_profile_id"],
    _ID_PATTERNS["fit_id"],
    _ID_PATTERNS["jd_id"],
    _ID_PATTERNS["note_id"],
    _ID_PATTERNS["resume_profile_id"],
    _ID_PATTERNS["resume_version_id"],
    _ID_PATTERNS["session_ref"],
)
_RECOMMENDATIONS = {"recommended", "cautious", "not_recommended"}
_APPLICATION_STAGES = {
    "draft",
    "analyzing",
    "ready_to_apply",
    "applied",
    "interviewing",
    "offer",
    "rejected",
    "paused",
}
_APPLICATION_PRIORITIES = {"high", "medium", "low"}


@dataclass(slots=True)
class ResumeProfile:
    """Structured product record extracted from a resume artifact."""

    resume_profile_id: str
    status: CareerRecordStatus
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    basic_info: dict[str, Any] = field(default_factory=dict)
    education: list[Any] = field(default_factory=list)
    work_experience: list[Any] = field(default_factory=list)
    project_experience: list[Any] = field(default_factory=list)
    skills: list[Any] = field(default_factory=list)
    certificates: list[Any] = field(default_factory=list)
    awards: list[Any] = field(default_factory=list)
    self_evaluation: str = ""
    raw_text_artifact_id: str | None = None
    diagnosis_artifact_id: str | None = None
    diagnosis: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.resume_profile_id = validate_resume_profile_id(self.resume_profile_id)
        _normalize_record_metadata(self)
        self.basic_info = _normalize_json_dict("basic_info", self.basic_info)
        self.education = _normalize_json_list("education", self.education)
        self.work_experience = _normalize_json_list("work_experience", self.work_experience)
        self.project_experience = _normalize_json_list("project_experience", self.project_experience)
        self.skills = _normalize_json_list("skills", self.skills)
        self.certificates = _normalize_json_list("certificates", self.certificates)
        self.awards = _normalize_json_list("awards", self.awards)
        self.self_evaluation = _normalize_text("self_evaluation", self.self_evaluation, allow_empty=True)
        self.raw_text_artifact_id = _normalize_optional_artifact_id("raw_text_artifact_id", self.raw_text_artifact_id)
        self.diagnosis_artifact_id = _normalize_optional_artifact_id(
            "diagnosis_artifact_id",
            self.diagnosis_artifact_id,
        )
        self.diagnosis = _normalize_json_dict("diagnosis", self.diagnosis)

    def copy(self) -> Self:
        return type(self)(
            resume_profile_id=self.resume_profile_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            basic_info=dict(self.basic_info),
            education=list(self.education),
            work_experience=list(self.work_experience),
            project_experience=list(self.project_experience),
            skills=list(self.skills),
            certificates=list(self.certificates),
            awards=list(self.awards),
            self_evaluation=self.self_evaluation,
            raw_text_artifact_id=self.raw_text_artifact_id,
            diagnosis_artifact_id=self.diagnosis_artifact_id,
            diagnosis=dict(self.diagnosis),
        )


@dataclass(slots=True)
class CareerProfile:
    """User-visible, editable career profile product record."""

    career_profile_id: str
    status: CareerRecordStatus
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    career_goal: str = ""
    target_roles: list[str] = field(default_factory=list)
    preferred_industries: list[str] = field(default_factory=list)
    preferred_cities: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    education_summary: str = ""
    experience_summary: str = ""
    resume_issues: list[str] = field(default_factory=list)
    interview_weaknesses: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.career_profile_id = validate_career_profile_id(self.career_profile_id)
        _normalize_record_metadata(self)
        self.career_goal = _normalize_text("career_goal", self.career_goal, allow_empty=True)
        self.target_roles = _normalize_string_list("target_roles", self.target_roles)
        self.preferred_industries = _normalize_string_list("preferred_industries", self.preferred_industries)
        self.preferred_cities = _normalize_string_list("preferred_cities", self.preferred_cities)
        self.strengths = _normalize_string_list("strengths", self.strengths)
        self.weaknesses = _normalize_string_list("weaknesses", self.weaknesses)
        self.skills = _normalize_string_list("skills", self.skills)
        self.interests = _normalize_string_list("interests", self.interests)
        self.education_summary = _normalize_text("education_summary", self.education_summary, allow_empty=True)
        self.experience_summary = _normalize_text("experience_summary", self.experience_summary, allow_empty=True)
        self.resume_issues = _normalize_string_list("resume_issues", self.resume_issues)
        self.interview_weaknesses = _normalize_string_list("interview_weaknesses", self.interview_weaknesses)

    def copy(self) -> Self:
        return type(self)(
            career_profile_id=self.career_profile_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            career_goal=self.career_goal,
            target_roles=list(self.target_roles),
            preferred_industries=list(self.preferred_industries),
            preferred_cities=list(self.preferred_cities),
            strengths=list(self.strengths),
            weaknesses=list(self.weaknesses),
            skills=list(self.skills),
            interests=list(self.interests),
            education_summary=self.education_summary,
            experience_summary=self.experience_summary,
            resume_issues=list(self.resume_issues),
            interview_weaknesses=list(self.interview_weaknesses),
        )


@dataclass(slots=True)
class JDAnalysis:
    """Structured analysis for one JD artifact."""

    jd_analysis_id: str
    status: CareerRecordStatus
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    company: str = ""
    position: str = ""
    seniority: str = ""
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    risk_signals: list[str] = field(default_factory=list)
    interview_focus: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.jd_analysis_id = validate_jd_id(self.jd_analysis_id)
        _normalize_record_metadata(self)
        self.company = _normalize_text("company", self.company, allow_empty=True)
        self.position = _normalize_text("position", self.position, allow_empty=True)
        self.seniority = _normalize_text("seniority", self.seniority, allow_empty=True)
        self.required_skills = _normalize_string_list("required_skills", self.required_skills)
        self.preferred_skills = _normalize_string_list("preferred_skills", self.preferred_skills)
        self.responsibilities = _normalize_string_list("responsibilities", self.responsibilities)
        self.keywords = _normalize_string_list("keywords", self.keywords)
        self.risk_signals = _normalize_string_list("risk_signals", self.risk_signals)
        self.interview_focus = _normalize_string_list("interview_focus", self.interview_focus)

    def copy(self) -> Self:
        return type(self)(
            jd_analysis_id=self.jd_analysis_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            company=self.company,
            position=self.position,
            seniority=self.seniority,
            required_skills=list(self.required_skills),
            preferred_skills=list(self.preferred_skills),
            responsibilities=list(self.responsibilities),
            keywords=list(self.keywords),
            risk_signals=list(self.risk_signals),
            interview_focus=list(self.interview_focus),
        )


@dataclass(slots=True)
class JobFitReport:
    """One fit analysis between a resume/profile and a JD."""

    job_fit_report_id: str
    status: CareerRecordStatus
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    jd_analysis_id: str
    resume_profile_id: str
    career_profile_id: str
    overall_score: int = 0
    score_breakdown: dict[str, int] = field(default_factory=dict)
    matched_evidence: list[Any] = field(default_factory=list)
    gaps: list[Any] = field(default_factory=list)
    resume_optimization_direction: list[Any] = field(default_factory=list)
    interview_preparation_focus: list[Any] = field(default_factory=list)
    recommendation: str = "cautious"
    report_artifact_id: str | None = None

    def __post_init__(self) -> None:
        self.job_fit_report_id = validate_fit_id(self.job_fit_report_id)
        _normalize_record_metadata(self)
        self.jd_analysis_id = validate_jd_id(self.jd_analysis_id)
        self.resume_profile_id = validate_resume_profile_id(self.resume_profile_id)
        self.career_profile_id = validate_career_profile_id(self.career_profile_id)
        self.overall_score = _normalize_score("overall_score", self.overall_score)
        self.score_breakdown = _normalize_score_breakdown(self.score_breakdown)
        self.matched_evidence = _normalize_json_list("matched_evidence", self.matched_evidence)
        self.gaps = _normalize_json_list("gaps", self.gaps)
        self.resume_optimization_direction = _normalize_json_list(
            "resume_optimization_direction",
            self.resume_optimization_direction,
        )
        self.interview_preparation_focus = _normalize_json_list(
            "interview_preparation_focus",
            self.interview_preparation_focus,
        )
        self.recommendation = _normalize_recommendation(self.recommendation)
        self.report_artifact_id = _normalize_optional_artifact_id("report_artifact_id", self.report_artifact_id)

    def copy(self) -> Self:
        return type(self)(
            job_fit_report_id=self.job_fit_report_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            jd_analysis_id=self.jd_analysis_id,
            resume_profile_id=self.resume_profile_id,
            career_profile_id=self.career_profile_id,
            overall_score=self.overall_score,
            score_breakdown=dict(self.score_breakdown),
            matched_evidence=list(self.matched_evidence),
            gaps=list(self.gaps),
            resume_optimization_direction=list(self.resume_optimization_direction),
            interview_preparation_focus=list(self.interview_preparation_focus),
            recommendation=self.recommendation,
            report_artifact_id=self.report_artifact_id,
        )


@dataclass(slots=True)
class ResumeVersion:
    """A generated resume version targeting a role or JD."""

    resume_version_id: str
    status: CareerRecordStatus
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    base_resume_profile_id: str
    target_jd_analysis_id: str | None
    title: str
    format: str
    artifact_id: str
    change_summary: list[str] = field(default_factory=list)
    keyword_strategy: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.resume_version_id = validate_resume_version_id(self.resume_version_id)
        _normalize_record_metadata(self)
        self.base_resume_profile_id = validate_resume_profile_id(self.base_resume_profile_id)
        self.target_jd_analysis_id = _normalize_optional_id(
            "target_jd_analysis_id",
            self.target_jd_analysis_id,
            "jd_id",
        )
        self.title = _require_non_empty("title", self.title)
        self.format = _require_non_empty("format", self.format).lower()
        if self.format not in {"markdown"}:
            raise ValidationError("format must be markdown.")
        self.artifact_id = validate_artifact_id(self.artifact_id)
        self.change_summary = _normalize_string_list("change_summary", self.change_summary)
        self.keyword_strategy = _normalize_string_list("keyword_strategy", self.keyword_strategy)
        self.risk_notes = _normalize_string_list("risk_notes", self.risk_notes)

    def copy(self) -> Self:
        return type(self)(
            resume_version_id=self.resume_version_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            base_resume_profile_id=self.base_resume_profile_id,
            target_jd_analysis_id=self.target_jd_analysis_id,
            title=self.title,
            format=self.format,
            artifact_id=self.artifact_id,
            change_summary=list(self.change_summary),
            keyword_strategy=list(self.keyword_strategy),
            risk_notes=list(self.risk_notes),
        )


@dataclass(slots=True)
class CareerApplication:
    """A user-visible project for one target job application."""

    application_id: str
    status: CareerRecordStatus
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    company: str = ""
    position: str = ""
    location: str = ""
    job_url: str = ""
    stage: str = "draft"
    priority: str = "medium"
    resume_profile_id: str | None = None
    career_profile_id: str | None = None
    jd_analysis_id: str | None = None
    job_fit_report_id: str | None = None
    resume_version_ids: list[str] = field(default_factory=list)
    summary: str = ""
    next_actions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        self.application_id = validate_application_id(self.application_id)
        _normalize_record_metadata(self)
        self.company = _normalize_text("company", self.company, allow_empty=True)
        self.position = _normalize_text("position", self.position, allow_empty=True)
        self.location = _normalize_text("location", self.location, allow_empty=True)
        self.job_url = _normalize_text("job_url", self.job_url, allow_empty=True)
        self.stage = _normalize_application_stage(self.stage)
        self.priority = _normalize_application_priority(self.priority)
        self.resume_profile_id = _normalize_optional_id(
            "resume_profile_id",
            self.resume_profile_id,
            "resume_profile_id",
        )
        self.career_profile_id = _normalize_optional_id(
            "career_profile_id",
            self.career_profile_id,
            "career_profile_id",
        )
        self.jd_analysis_id = _normalize_optional_id("jd_analysis_id", self.jd_analysis_id, "jd_id")
        self.job_fit_report_id = _normalize_optional_id(
            "job_fit_report_id",
            self.job_fit_report_id,
            "fit_id",
        )
        self.resume_version_ids = _normalize_resume_version_ids(self.resume_version_ids)
        self.summary = _normalize_text("summary", self.summary, allow_empty=True)
        self.next_actions = _normalize_string_list("next_actions", self.next_actions)
        self.risks = _normalize_string_list("risks", self.risks)
        self.notes = _normalize_text("notes", self.notes, allow_empty=True)

    def copy(self) -> Self:
        return type(self)(
            application_id=self.application_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            company=self.company,
            position=self.position,
            location=self.location,
            job_url=self.job_url,
            stage=self.stage,
            priority=self.priority,
            resume_profile_id=self.resume_profile_id,
            career_profile_id=self.career_profile_id,
            jd_analysis_id=self.jd_analysis_id,
            job_fit_report_id=self.job_fit_report_id,
            resume_version_ids=list(self.resume_version_ids),
            summary=self.summary,
            next_actions=list(self.next_actions),
            risks=list(self.risks),
            notes=self.notes,
        )


def _normalize_record_metadata(record: object) -> None:
    status = getattr(record, "status")
    source_session_id = getattr(record, "source_session_id")
    source_artifact_id = getattr(record, "source_artifact_id")
    evidence_refs = getattr(record, "evidence_refs")
    created_at = getattr(record, "created_at")
    updated_at = getattr(record, "updated_at")

    setattr(record, "status", _normalize_status(status))
    setattr(record, "source_session_id", validate_session_id(source_session_id))
    normalized_source_artifact_id = _normalize_optional_artifact_id("source_artifact_id", source_artifact_id)
    setattr(record, "source_artifact_id", normalized_source_artifact_id)
    normalized_evidence_refs = validate_evidence_refs(evidence_refs)
    if normalized_source_artifact_id is None and not normalized_evidence_refs:
        raise ValidationError("evidence_refs are required when source_artifact_id is missing.")
    setattr(record, "evidence_refs", normalized_evidence_refs)
    normalized_created_at = _normalize_datetime("created_at", created_at)
    normalized_updated_at = _normalize_datetime("updated_at", updated_at)
    if normalized_updated_at < normalized_created_at:
        raise ValidationError("updated_at cannot be earlier than created_at.")
    setattr(record, "created_at", normalized_created_at)
    setattr(record, "updated_at", normalized_updated_at)


def _normalize_status(value: CareerRecordStatus | str) -> CareerRecordStatus:
    if isinstance(value, CareerRecordStatus):
        return value
    if isinstance(value, str):
        try:
            return CareerRecordStatus(value.strip().lower())
        except ValueError as exc:
            raise ValidationError(f"status is invalid: {value}") from exc
    raise ValidationError("status must be a string.")


def validate_artifact_id(value: str) -> str:
    return _validate_id("artifact_id", value, "artifact_id")


def validate_application_id(value: str) -> str:
    return _validate_id("application_id", value, "application_id")


def validate_career_profile_id(value: str) -> str:
    return _validate_id("career_profile_id", value, "career_profile_id")


def validate_fit_id(value: str) -> str:
    return _validate_id("job_fit_report_id", value, "fit_id")


def validate_jd_id(value: str) -> str:
    return _validate_id("jd_analysis_id", value, "jd_id")


def validate_resume_profile_id(value: str) -> str:
    return _validate_id("resume_profile_id", value, "resume_profile_id")


def validate_resume_version_id(value: str) -> str:
    return _validate_id("resume_version_id", value, "resume_version_id")


def validate_session_id(value: str) -> str:
    return _validate_id("source_session_id", value, "session_ref")


def _validate_id(field_name: str, value: str, pattern_name: str) -> str:
    normalized = _require_non_empty(field_name, value)
    pattern = _ID_PATTERNS[pattern_name]
    if not pattern.fullmatch(normalized):
        raise ValidationError(f"{field_name} has invalid format: {normalized}")
    return normalized


def _normalize_optional_id(field_name: str, value: str | None, pattern_name: str) -> str | None:
    if value is None:
        return None
    if pattern_name == "jd_id":
        return validate_jd_id(value)
    return _validate_id(field_name, value, pattern_name)


def _normalize_resume_version_ids(values: list[str]) -> list[str]:
    ids = _normalize_string_list("resume_version_ids", values)
    return [validate_resume_version_id(item) for item in ids]


def _normalize_optional_artifact_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return validate_artifact_id(value)


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


def _require_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _normalize_text(field_name: str, value: str, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string.")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return normalized


def _normalize_datetime(field_name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationError(f"{field_name} must be datetime.")
    return normalize_app_datetime(value)


def _normalize_string_list(field_name: str, values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(f"{field_name} must be a list.")
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = _require_non_empty(field_name, raw)
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _normalize_json_dict(field_name: str, value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{field_name} must be a dictionary.")
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValidationError(f"{field_name} keys must be non-empty strings.")
        normalized[key] = item
    _ensure_json_serializable(field_name, normalized)
    return normalized


def _normalize_json_list(field_name: str, value: list[Any]) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list.")
    _ensure_json_serializable(field_name, value)
    return list(value)


def _ensure_json_serializable(field_name: str, value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be JSON-serializable.") from exc


def _normalize_score(field_name: str, value: int) -> int:
    if not isinstance(value, int):
        raise ValidationError(f"{field_name} must be an integer.")
    if value < 0 or value > 100:
        raise ValidationError(f"{field_name} must be in range 0..100.")
    return value


def _normalize_score_breakdown(value: dict[str, int]) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValidationError("score_breakdown must be a dictionary.")
    output: dict[str, int] = {}
    for raw_key, raw_score in value.items():
        key = _require_non_empty("score_breakdown key", raw_key)
        output[key] = _normalize_score("score_breakdown value", raw_score)
    return output


def _normalize_recommendation(value: str) -> str:
    normalized = _require_non_empty("recommendation", value).lower()
    if normalized not in _RECOMMENDATIONS:
        raise ValidationError(f"recommendation is invalid: {normalized}")
    return normalized


def _normalize_application_stage(value: str) -> str:
    normalized = _require_non_empty("stage", value).lower()
    if normalized not in _APPLICATION_STAGES:
        raise ValidationError(f"stage is invalid: {normalized}")
    return normalized


def _normalize_application_priority(value: str) -> str:
    normalized = _require_non_empty("priority", value).lower()
    if normalized not in _APPLICATION_PRIORITIES:
        raise ValidationError(f"priority is invalid: {normalized}")
    return normalized
