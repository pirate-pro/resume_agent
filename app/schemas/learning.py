"""HTTP schemas for learning plan endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "LearningPlanCreateRequest",
    "LearningPlanUpdateRequest",
    "LearningPlanView",
    "LearningTaskCreateRequest",
    "LearningTaskStateUpdateRequest",
    "LearningTaskUpdateRequest",
    "LearningTaskView",
    "ProgressCheckinCreateRequest",
    "ProgressCheckinUpdateRequest",
    "ProgressCheckinView",
    "ReviewScheduleCreateRequest",
    "ReviewScheduleUpdateRequest",
    "ReviewScheduleView",
    "WeaknessTrackerCreateRequest",
    "WeaknessTrackerUpdateRequest",
    "WeaknessTrackerView",
]


class LearningRecordMetaView(BaseModel):
    status: str
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class LearningPlanView(LearningRecordMetaView):
    learning_plan_id: str
    title: str
    description: str = ""
    plan_type: str = "custom"
    target_application_id: str | None = None
    target_role: str = ""
    target_company: str = ""
    start_date: datetime | None = None
    end_date: datetime | None = None
    priority: str = "medium"
    goals: list[str] = Field(default_factory=list)
    focus_skill_tags: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    weakness_ids: list[str] = Field(default_factory=list)
    review_schedule_ids: list[str] = Field(default_factory=list)
    progress_summary: str = ""


class LearningTaskView(LearningRecordMetaView):
    learning_task_id: str
    title: str
    learning_plan_id: str | None = None
    description: str = ""
    task_type: str = "custom"
    priority: str = "medium"
    state: str = "todo"
    skill_tags: list[str] = Field(default_factory=list)
    estimated_minutes: int = 0
    planned_start_date: datetime | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None
    resource_refs: list[str] = Field(default_factory=list)
    question_refs: list[str] = Field(default_factory=list)
    note_refs: list[str] = Field(default_factory=list)
    output_artifact_id: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    progress_notes: str = ""


class ProgressCheckinView(LearningRecordMetaView):
    checkin_id: str
    learning_plan_id: str | None = None
    learning_task_id: str | None = None
    checkin_date: datetime | None = None
    minutes_spent: int = 0
    progress_state: str = "in_progress"
    summary: str = ""
    blockers: list[str] = Field(default_factory=list)
    confidence: str = "medium"
    next_action: str = ""
    note_refs: list[str] = Field(default_factory=list)


class WeaknessTrackerView(LearningRecordMetaView):
    weakness_id: str
    title: str
    description: str = ""
    weakness_type: str = "other"
    severity: str = "medium"
    state: str = "open"
    skill_tags: list[str] = Field(default_factory=list)
    target_application_ids: list[str] = Field(default_factory=list)
    source_report_ids: list[str] = Field(default_factory=list)
    related_task_ids: list[str] = Field(default_factory=list)
    related_note_ids: list[str] = Field(default_factory=list)
    last_observed_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_summary: str = ""


class ReviewScheduleView(LearningRecordMetaView):
    review_schedule_id: str
    title: str
    learning_plan_id: str | None = None
    learning_task_id: str | None = None
    weakness_id: str | None = None
    review_type: str = "custom"
    review_at: datetime | None = None
    interval_days: int = 0
    state: str = "scheduled"
    resource_refs: list[str] = Field(default_factory=list)
    question_refs: list[str] = Field(default_factory=list)
    note_refs: list[str] = Field(default_factory=list)
    last_reviewed_at: datetime | None = None
    next_review_at: datetime | None = None
    summary: str = ""


class LearningPlanCreateRequest(BaseModel):
    learning_plan_id: str | None = None
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    title: str
    description: str = ""
    plan_type: str = "custom"
    target_application_id: str | None = None
    target_role: str = ""
    target_company: str = ""
    start_date: datetime | None = None
    end_date: datetime | None = None
    priority: str = "medium"
    goals: list[str] = Field(default_factory=list)
    focus_skill_tags: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    weakness_ids: list[str] = Field(default_factory=list)
    review_schedule_ids: list[str] = Field(default_factory=list)
    progress_summary: str = ""


class LearningPlanUpdateRequest(BaseModel):
    source_artifact_id: str | None = None
    evidence_refs: list[str] | None = None
    title: str | None = None
    description: str | None = None
    plan_type: str | None = None
    target_application_id: str | None = None
    target_role: str | None = None
    target_company: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    priority: str | None = None
    goals: list[str] | None = None
    focus_skill_tags: list[str] | None = None
    task_ids: list[str] | None = None
    weakness_ids: list[str] | None = None
    review_schedule_ids: list[str] | None = None
    progress_summary: str | None = None


class LearningTaskCreateRequest(BaseModel):
    learning_task_id: str | None = None
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    title: str
    learning_plan_id: str | None = None
    description: str = ""
    task_type: str = "custom"
    priority: str = "medium"
    state: str = "todo"
    skill_tags: list[str] = Field(default_factory=list)
    estimated_minutes: int = 0
    planned_start_date: datetime | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None
    resource_refs: list[str] = Field(default_factory=list)
    question_refs: list[str] = Field(default_factory=list)
    note_refs: list[str] = Field(default_factory=list)
    output_artifact_id: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    progress_notes: str = ""


class LearningTaskUpdateRequest(BaseModel):
    source_artifact_id: str | None = None
    evidence_refs: list[str] | None = None
    title: str | None = None
    learning_plan_id: str | None = None
    description: str | None = None
    task_type: str | None = None
    priority: str | None = None
    state: str | None = None
    skill_tags: list[str] | None = None
    estimated_minutes: int | None = None
    planned_start_date: datetime | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None
    resource_refs: list[str] | None = None
    question_refs: list[str] | None = None
    note_refs: list[str] | None = None
    output_artifact_id: str | None = None
    success_criteria: list[str] | None = None
    progress_notes: str | None = None


class LearningTaskStateUpdateRequest(BaseModel):
    state: str
    completed_at: datetime | None = None


class ProgressCheckinCreateRequest(BaseModel):
    checkin_id: str | None = None
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    learning_plan_id: str | None = None
    learning_task_id: str | None = None
    checkin_date: datetime | None = None
    minutes_spent: int = 0
    progress_state: str = "in_progress"
    summary: str = ""
    blockers: list[str] = Field(default_factory=list)
    confidence: str = "medium"
    next_action: str = ""
    note_refs: list[str] = Field(default_factory=list)


class ProgressCheckinUpdateRequest(BaseModel):
    source_artifact_id: str | None = None
    evidence_refs: list[str] | None = None
    learning_plan_id: str | None = None
    learning_task_id: str | None = None
    checkin_date: datetime | None = None
    minutes_spent: int | None = None
    progress_state: str | None = None
    summary: str | None = None
    blockers: list[str] | None = None
    confidence: str | None = None
    next_action: str | None = None
    note_refs: list[str] | None = None


class WeaknessTrackerCreateRequest(BaseModel):
    weakness_id: str | None = None
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    title: str
    description: str = ""
    weakness_type: str = "other"
    severity: str = "medium"
    state: str = "open"
    skill_tags: list[str] = Field(default_factory=list)
    target_application_ids: list[str] = Field(default_factory=list)
    source_report_ids: list[str] = Field(default_factory=list)
    related_task_ids: list[str] = Field(default_factory=list)
    related_note_ids: list[str] = Field(default_factory=list)
    last_observed_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_summary: str = ""


class WeaknessTrackerUpdateRequest(BaseModel):
    source_artifact_id: str | None = None
    evidence_refs: list[str] | None = None
    title: str | None = None
    description: str | None = None
    weakness_type: str | None = None
    severity: str | None = None
    state: str | None = None
    skill_tags: list[str] | None = None
    target_application_ids: list[str] | None = None
    source_report_ids: list[str] | None = None
    related_task_ids: list[str] | None = None
    related_note_ids: list[str] | None = None
    last_observed_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_summary: str | None = None


class ReviewScheduleCreateRequest(BaseModel):
    review_schedule_id: str | None = None
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    title: str
    learning_plan_id: str | None = None
    learning_task_id: str | None = None
    weakness_id: str | None = None
    review_type: str = "custom"
    review_at: datetime | None = None
    interval_days: int = 0
    state: str = "scheduled"
    resource_refs: list[str] = Field(default_factory=list)
    question_refs: list[str] = Field(default_factory=list)
    note_refs: list[str] = Field(default_factory=list)
    last_reviewed_at: datetime | None = None
    next_review_at: datetime | None = None
    summary: str = ""


class ReviewScheduleUpdateRequest(BaseModel):
    source_artifact_id: str | None = None
    evidence_refs: list[str] | None = None
    title: str | None = None
    learning_plan_id: str | None = None
    learning_task_id: str | None = None
    weakness_id: str | None = None
    review_type: str | None = None
    review_at: datetime | None = None
    interval_days: int | None = None
    state: str | None = None
    resource_refs: list[str] | None = None
    question_refs: list[str] | None = None
    note_refs: list[str] | None = None
    last_reviewed_at: datetime | None = None
    next_review_at: datetime | None = None
    summary: str | None = None

