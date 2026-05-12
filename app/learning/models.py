"""Domain models for learning plans and progress tracking."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Self, TypeVar

from app.core.errors import ValidationError
from app.core.time import normalize_app_datetime

__all__ = [
    "ConfidenceLevel",
    "LearningPlan",
    "LearningPlanType",
    "LearningPriority",
    "LearningRecordStatus",
    "LearningTask",
    "LearningTaskState",
    "LearningTaskType",
    "ProgressCheckin",
    "ProgressState",
    "ReviewSchedule",
    "ReviewState",
    "ReviewType",
    "WeaknessSeverity",
    "WeaknessState",
    "WeaknessTracker",
    "WeaknessType",
    "validate_artifact_id",
    "validate_checkin_id",
    "validate_evidence_refs",
    "validate_learning_plan_id",
    "validate_learning_task_id",
    "validate_optional_artifact_id",
    "validate_optional_application_id",
    "validate_optional_learning_plan_id",
    "validate_optional_learning_task_id",
    "validate_optional_weakness_id",
    "validate_review_schedule_id",
    "validate_session_id",
    "validate_weakness_id",
]

_EnumT = TypeVar("_EnumT", bound=Enum)


class LearningRecordStatus(str, Enum):
    """Lifecycle status for learning records."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class LearningPlanType(str, Enum):
    """Supported learning plan categories."""

    CAREER_GAP = "career_gap"
    INTERVIEW_PREP = "interview_prep"
    SKILL_BUILD = "skill_build"
    REVIEW = "review"
    CUSTOM = "custom"


class LearningPriority(str, Enum):
    """Supported learning priority levels."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class LearningTaskType(str, Enum):
    """Supported task types."""

    READ_RESOURCE = "read_resource"
    PRACTICE_QUESTION = "practice_question"
    WRITE_ANSWER = "write_answer"
    REVISE_RESUME = "revise_resume"
    MOCK_INTERVIEW = "mock_interview"
    REVIEW_NOTE = "review_note"
    CUSTOM = "custom"


class LearningTaskState(str, Enum):
    """Execution state for one learning task."""

    TODO = "todo"
    DOING = "doing"
    BLOCKED = "blocked"
    DONE = "done"
    SKIPPED = "skipped"


class ProgressState(str, Enum):
    """Progress state captured by one checkin."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class ConfidenceLevel(str, Enum):
    """Self-reported confidence level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class WeaknessType(str, Enum):
    """Supported weakness categories."""

    SKILL_GAP = "skill_gap"
    PROJECT_GAP = "project_gap"
    INTERVIEW_GAP = "interview_gap"
    RESUME_GAP = "resume_gap"
    HABIT = "habit"
    CONFIDENCE = "confidence"
    OTHER = "other"


class WeaknessSeverity(str, Enum):
    """Supported weakness severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class WeaknessState(str, Enum):
    """Lifecycle state for a tracked weakness."""

    OPEN = "open"
    IMPROVING = "improving"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class ReviewType(str, Enum):
    """Supported review schedule types."""

    SPACED_REPETITION = "spaced_repetition"
    INTERVIEW_REHEARSAL = "interview_rehearsal"
    RESUME_REVIEW = "resume_review"
    PROJECT_DRILL = "project_drill"
    CUSTOM = "custom"


class ReviewState(str, Enum):
    """Execution state for a review schedule."""

    SCHEDULED = "scheduled"
    DONE = "done"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


_ID_PATTERNS = {
    "application_id": re.compile(r"^application_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "artifact_id": re.compile(r"^artifact_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "career_profile_id": re.compile(r"^career_profile_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "checkin_id": re.compile(r"^checkin_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "company_id": re.compile(r"^company_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "experience_id": re.compile(r"^experience_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "fit_id": re.compile(r"^fit_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "jd_id": re.compile(r"^(jd|jd_analysis)_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "learning_plan_id": re.compile(r"^learning_plan_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "learning_task_id": re.compile(r"^learning_task_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "note_id": re.compile(r"^note_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "question_id": re.compile(r"^question_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "resource_id": re.compile(r"^resource_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "resume_profile_id": re.compile(r"^resume_profile_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "resume_version_id": re.compile(r"^resume_version_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "review_schedule_id": re.compile(r"^review_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "session_ref": re.compile(r"^sess_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "skill_requirement_id": re.compile(r"^skill_req_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    "weakness_id": re.compile(r"^weakness_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
}
_EVIDENCE_REF_PATTERNS = (
    _ID_PATTERNS["application_id"],
    _ID_PATTERNS["artifact_id"],
    _ID_PATTERNS["career_profile_id"],
    _ID_PATTERNS["checkin_id"],
    _ID_PATTERNS["company_id"],
    _ID_PATTERNS["experience_id"],
    _ID_PATTERNS["fit_id"],
    _ID_PATTERNS["jd_id"],
    _ID_PATTERNS["learning_plan_id"],
    _ID_PATTERNS["learning_task_id"],
    _ID_PATTERNS["note_id"],
    _ID_PATTERNS["question_id"],
    _ID_PATTERNS["resource_id"],
    _ID_PATTERNS["resume_profile_id"],
    _ID_PATTERNS["resume_version_id"],
    _ID_PATTERNS["review_schedule_id"],
    _ID_PATTERNS["session_ref"],
    _ID_PATTERNS["skill_requirement_id"],
    _ID_PATTERNS["weakness_id"],
)
_RESOURCE_REF_PATTERNS = (
    _ID_PATTERNS["resource_id"],
    _ID_PATTERNS["skill_requirement_id"],
    _ID_PATTERNS["artifact_id"],
    _ID_PATTERNS["experience_id"],
    _ID_PATTERNS["company_id"],
)
_SOURCE_REPORT_PATTERNS = (
    _ID_PATTERNS["fit_id"],
    _ID_PATTERNS["jd_id"],
    _ID_PATTERNS["artifact_id"],
)


@dataclass(slots=True)
class LearningPlan:
    """A user-visible learning plan for one career goal."""

    learning_plan_id: str
    status: LearningRecordStatus | str
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    title: str
    description: str = ""
    plan_type: LearningPlanType | str = LearningPlanType.CUSTOM
    target_application_id: str | None = None
    target_role: str = ""
    target_company: str = ""
    start_date: datetime | None = None
    end_date: datetime | None = None
    priority: LearningPriority | str = LearningPriority.MEDIUM
    goals: list[str] = field(default_factory=list)
    focus_skill_tags: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    weakness_ids: list[str] = field(default_factory=list)
    review_schedule_ids: list[str] = field(default_factory=list)
    progress_summary: str = ""

    def __post_init__(self) -> None:
        self.learning_plan_id = validate_learning_plan_id(self.learning_plan_id)
        _normalize_record_metadata(self)
        self.title = _normalize_text("title", self.title, allow_empty=False)
        self.description = _normalize_text("description", self.description, allow_empty=True)
        self.plan_type = _normalize_enum("plan_type", self.plan_type, LearningPlanType)
        self.target_application_id = validate_optional_application_id(
            "target_application_id",
            self.target_application_id,
        )
        self.target_role = _normalize_text("target_role", self.target_role, allow_empty=True)
        self.target_company = _normalize_text("target_company", self.target_company, allow_empty=True)
        self.start_date = _normalize_optional_datetime("start_date", self.start_date)
        self.end_date = _normalize_optional_datetime("end_date", self.end_date)
        if self.start_date is not None and self.end_date is not None and self.end_date < self.start_date:
            raise ValidationError("end_date cannot be earlier than start_date.")
        self.priority = _normalize_enum("priority", self.priority, LearningPriority)
        self.goals = _normalize_string_list("goals", self.goals)
        self.focus_skill_tags = _normalize_string_list("focus_skill_tags", self.focus_skill_tags)
        self.task_ids = _normalize_id_list("task_ids", self.task_ids, "learning_task_id")
        self.weakness_ids = _normalize_id_list("weakness_ids", self.weakness_ids, "weakness_id")
        self.review_schedule_ids = _normalize_id_list(
            "review_schedule_ids",
            self.review_schedule_ids,
            "review_schedule_id",
        )
        self.progress_summary = _normalize_text("progress_summary", self.progress_summary, allow_empty=True)

    def copy(self) -> Self:
        return type(self)(
            learning_plan_id=self.learning_plan_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            title=self.title,
            description=self.description,
            plan_type=self.plan_type,
            target_application_id=self.target_application_id,
            target_role=self.target_role,
            target_company=self.target_company,
            start_date=self.start_date,
            end_date=self.end_date,
            priority=self.priority,
            goals=list(self.goals),
            focus_skill_tags=list(self.focus_skill_tags),
            task_ids=list(self.task_ids),
            weakness_ids=list(self.weakness_ids),
            review_schedule_ids=list(self.review_schedule_ids),
            progress_summary=self.progress_summary,
        )


@dataclass(slots=True)
class LearningTask:
    """A concrete task inside a learning plan."""

    learning_task_id: str
    status: LearningRecordStatus | str
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    title: str
    learning_plan_id: str | None = None
    description: str = ""
    task_type: LearningTaskType | str = LearningTaskType.CUSTOM
    priority: LearningPriority | str = LearningPriority.MEDIUM
    state: LearningTaskState | str = LearningTaskState.TODO
    skill_tags: list[str] = field(default_factory=list)
    estimated_minutes: int = 0
    planned_start_date: datetime | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None
    resource_refs: list[str] = field(default_factory=list)
    question_refs: list[str] = field(default_factory=list)
    note_refs: list[str] = field(default_factory=list)
    output_artifact_id: str | None = None
    success_criteria: list[str] = field(default_factory=list)
    progress_notes: str = ""

    def __post_init__(self) -> None:
        self.learning_task_id = validate_learning_task_id(self.learning_task_id)
        _normalize_record_metadata(self)
        self.title = _normalize_text("title", self.title, allow_empty=False)
        self.learning_plan_id = validate_optional_learning_plan_id("learning_plan_id", self.learning_plan_id)
        self.description = _normalize_text("description", self.description, allow_empty=True)
        self.task_type = _normalize_enum("task_type", self.task_type, LearningTaskType)
        self.priority = _normalize_enum("priority", self.priority, LearningPriority)
        self.state = _normalize_enum("state", self.state, LearningTaskState)
        self.skill_tags = _normalize_string_list("skill_tags", self.skill_tags)
        self.estimated_minutes = _normalize_non_negative_int("estimated_minutes", self.estimated_minutes)
        self.planned_start_date = _normalize_optional_datetime("planned_start_date", self.planned_start_date)
        self.due_date = _normalize_optional_datetime("due_date", self.due_date)
        self.completed_at = _normalize_optional_datetime("completed_at", self.completed_at)
        self.resource_refs = _normalize_ref_list("resource_refs", self.resource_refs, _RESOURCE_REF_PATTERNS)
        self.question_refs = _normalize_id_list("question_refs", self.question_refs, "question_id")
        self.note_refs = _normalize_id_list("note_refs", self.note_refs, "note_id")
        self.output_artifact_id = validate_optional_artifact_id("output_artifact_id", self.output_artifact_id)
        self.success_criteria = _normalize_string_list("success_criteria", self.success_criteria)
        self.progress_notes = _normalize_text("progress_notes", self.progress_notes, allow_empty=True)

    def copy(self) -> Self:
        return type(self)(
            learning_task_id=self.learning_task_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            title=self.title,
            learning_plan_id=self.learning_plan_id,
            description=self.description,
            task_type=self.task_type,
            priority=self.priority,
            state=self.state,
            skill_tags=list(self.skill_tags),
            estimated_minutes=self.estimated_minutes,
            planned_start_date=self.planned_start_date,
            due_date=self.due_date,
            completed_at=self.completed_at,
            resource_refs=list(self.resource_refs),
            question_refs=list(self.question_refs),
            note_refs=list(self.note_refs),
            output_artifact_id=self.output_artifact_id,
            success_criteria=list(self.success_criteria),
            progress_notes=self.progress_notes,
        )


@dataclass(slots=True)
class ProgressCheckin:
    """One learning progress checkin."""

    checkin_id: str
    status: LearningRecordStatus | str
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    learning_plan_id: str | None = None
    learning_task_id: str | None = None
    checkin_date: datetime | None = None
    minutes_spent: int = 0
    progress_state: ProgressState | str = ProgressState.IN_PROGRESS
    summary: str = ""
    blockers: list[str] = field(default_factory=list)
    confidence: ConfidenceLevel | str = ConfidenceLevel.MEDIUM
    next_action: str = ""
    note_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.checkin_id = validate_checkin_id(self.checkin_id)
        _normalize_record_metadata(self)
        self.learning_plan_id = validate_optional_learning_plan_id("learning_plan_id", self.learning_plan_id)
        self.learning_task_id = validate_optional_learning_task_id("learning_task_id", self.learning_task_id)
        self.checkin_date = _normalize_optional_datetime("checkin_date", self.checkin_date)
        self.minutes_spent = _normalize_non_negative_int("minutes_spent", self.minutes_spent)
        self.progress_state = _normalize_enum("progress_state", self.progress_state, ProgressState)
        self.summary = _normalize_text("summary", self.summary, allow_empty=True)
        self.blockers = _normalize_string_list("blockers", self.blockers)
        self.confidence = _normalize_enum("confidence", self.confidence, ConfidenceLevel)
        self.next_action = _normalize_text("next_action", self.next_action, allow_empty=True)
        self.note_refs = _normalize_id_list("note_refs", self.note_refs, "note_id")

    def copy(self) -> Self:
        return type(self)(
            checkin_id=self.checkin_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            learning_plan_id=self.learning_plan_id,
            learning_task_id=self.learning_task_id,
            checkin_date=self.checkin_date,
            minutes_spent=self.minutes_spent,
            progress_state=self.progress_state,
            summary=self.summary,
            blockers=list(self.blockers),
            confidence=self.confidence,
            next_action=self.next_action,
            note_refs=list(self.note_refs),
        )


@dataclass(slots=True)
class WeaknessTracker:
    """A tracked capability weakness that can improve over time."""

    weakness_id: str
    status: LearningRecordStatus | str
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    title: str
    description: str = ""
    weakness_type: WeaknessType | str = WeaknessType.OTHER
    severity: WeaknessSeverity | str = WeaknessSeverity.MEDIUM
    state: WeaknessState | str = WeaknessState.OPEN
    skill_tags: list[str] = field(default_factory=list)
    target_application_ids: list[str] = field(default_factory=list)
    source_report_ids: list[str] = field(default_factory=list)
    related_task_ids: list[str] = field(default_factory=list)
    related_note_ids: list[str] = field(default_factory=list)
    last_observed_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_summary: str = ""

    def __post_init__(self) -> None:
        self.weakness_id = validate_weakness_id(self.weakness_id)
        _normalize_record_metadata(self)
        self.title = _normalize_text("title", self.title, allow_empty=False)
        self.description = _normalize_text("description", self.description, allow_empty=True)
        self.weakness_type = _normalize_enum("weakness_type", self.weakness_type, WeaknessType)
        self.severity = _normalize_enum("severity", self.severity, WeaknessSeverity)
        self.state = _normalize_enum("state", self.state, WeaknessState)
        self.skill_tags = _normalize_string_list("skill_tags", self.skill_tags)
        self.target_application_ids = _normalize_id_list(
            "target_application_ids",
            self.target_application_ids,
            "application_id",
        )
        self.source_report_ids = _normalize_ref_list(
            "source_report_ids",
            self.source_report_ids,
            _SOURCE_REPORT_PATTERNS,
        )
        self.related_task_ids = _normalize_id_list("related_task_ids", self.related_task_ids, "learning_task_id")
        self.related_note_ids = _normalize_id_list("related_note_ids", self.related_note_ids, "note_id")
        self.last_observed_at = _normalize_optional_datetime("last_observed_at", self.last_observed_at)
        self.resolved_at = _normalize_optional_datetime("resolved_at", self.resolved_at)
        self.resolution_summary = _normalize_text("resolution_summary", self.resolution_summary, allow_empty=True)

    def copy(self) -> Self:
        return type(self)(
            weakness_id=self.weakness_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            title=self.title,
            description=self.description,
            weakness_type=self.weakness_type,
            severity=self.severity,
            state=self.state,
            skill_tags=list(self.skill_tags),
            target_application_ids=list(self.target_application_ids),
            source_report_ids=list(self.source_report_ids),
            related_task_ids=list(self.related_task_ids),
            related_note_ids=list(self.related_note_ids),
            last_observed_at=self.last_observed_at,
            resolved_at=self.resolved_at,
            resolution_summary=self.resolution_summary,
        )


@dataclass(slots=True)
class ReviewSchedule:
    """A scheduled review item for spaced preparation."""

    review_schedule_id: str
    status: LearningRecordStatus | str
    source_session_id: str
    source_artifact_id: str | None
    evidence_refs: list[str]
    created_at: datetime
    updated_at: datetime
    title: str
    learning_plan_id: str | None = None
    learning_task_id: str | None = None
    weakness_id: str | None = None
    review_type: ReviewType | str = ReviewType.CUSTOM
    review_at: datetime | None = None
    interval_days: int = 0
    state: ReviewState | str = ReviewState.SCHEDULED
    resource_refs: list[str] = field(default_factory=list)
    question_refs: list[str] = field(default_factory=list)
    note_refs: list[str] = field(default_factory=list)
    last_reviewed_at: datetime | None = None
    next_review_at: datetime | None = None
    summary: str = ""

    def __post_init__(self) -> None:
        self.review_schedule_id = validate_review_schedule_id(self.review_schedule_id)
        _normalize_record_metadata(self)
        self.title = _normalize_text("title", self.title, allow_empty=False)
        self.learning_plan_id = validate_optional_learning_plan_id("learning_plan_id", self.learning_plan_id)
        self.learning_task_id = validate_optional_learning_task_id("learning_task_id", self.learning_task_id)
        self.weakness_id = validate_optional_weakness_id("weakness_id", self.weakness_id)
        self.review_type = _normalize_enum("review_type", self.review_type, ReviewType)
        self.review_at = _normalize_optional_datetime("review_at", self.review_at)
        self.interval_days = _normalize_non_negative_int("interval_days", self.interval_days)
        self.state = _normalize_enum("state", self.state, ReviewState)
        self.resource_refs = _normalize_ref_list("resource_refs", self.resource_refs, _RESOURCE_REF_PATTERNS)
        self.question_refs = _normalize_id_list("question_refs", self.question_refs, "question_id")
        self.note_refs = _normalize_id_list("note_refs", self.note_refs, "note_id")
        self.last_reviewed_at = _normalize_optional_datetime("last_reviewed_at", self.last_reviewed_at)
        self.next_review_at = _normalize_optional_datetime("next_review_at", self.next_review_at)
        self.summary = _normalize_text("summary", self.summary, allow_empty=True)

    def copy(self) -> Self:
        return type(self)(
            review_schedule_id=self.review_schedule_id,
            status=self.status,
            source_session_id=self.source_session_id,
            source_artifact_id=self.source_artifact_id,
            evidence_refs=list(self.evidence_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
            title=self.title,
            learning_plan_id=self.learning_plan_id,
            learning_task_id=self.learning_task_id,
            weakness_id=self.weakness_id,
            review_type=self.review_type,
            review_at=self.review_at,
            interval_days=self.interval_days,
            state=self.state,
            resource_refs=list(self.resource_refs),
            question_refs=list(self.question_refs),
            note_refs=list(self.note_refs),
            last_reviewed_at=self.last_reviewed_at,
            next_review_at=self.next_review_at,
            summary=self.summary,
        )


def validate_learning_plan_id(value: str) -> str:
    return _validate_id("learning_plan_id", value, "learning_plan_id")


def validate_learning_task_id(value: str) -> str:
    return _validate_id("learning_task_id", value, "learning_task_id")


def validate_checkin_id(value: str) -> str:
    return _validate_id("checkin_id", value, "checkin_id")


def validate_weakness_id(value: str) -> str:
    return _validate_id("weakness_id", value, "weakness_id")


def validate_review_schedule_id(value: str) -> str:
    return _validate_id("review_schedule_id", value, "review_schedule_id")


def validate_session_id(value: str) -> str:
    return _validate_id("source_session_id", value, "session_ref")


def validate_artifact_id(value: str) -> str:
    return _validate_id("artifact_id", value, "artifact_id")


def validate_optional_artifact_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_id(field_name, value, "artifact_id")


def validate_optional_application_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_id(field_name, value, "application_id")


def validate_optional_learning_plan_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_id(field_name, value, "learning_plan_id")


def validate_optional_learning_task_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_id(field_name, value, "learning_task_id")


def validate_optional_weakness_id(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_id(field_name, value, "weakness_id")


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
    record.status = _normalize_enum("status", record.status, LearningRecordStatus)
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


def _normalize_optional_datetime(field_name: str, value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _normalize_datetime(field_name, value)


def _normalize_non_negative_int(field_name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field_name} must be an integer.")
    if value < 0:
        raise ValidationError(f"{field_name} cannot be negative.")
    return value


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


def _normalize_ref_list(field_name: str, values: list[str], patterns: tuple[re.Pattern[str], ...]) -> list[str]:
    refs = _normalize_string_list(field_name, values)
    output: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if not any(pattern.fullmatch(ref) for pattern in patterns):
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

