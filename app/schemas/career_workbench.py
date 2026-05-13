"""HTTP schemas for the career workbench endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.career import (
    CareerApplicationView,
    CareerProfileView,
    JDAnalysisView,
    JobFitReportView,
    ResumeProfileView,
    ResumeVersionView,
)
from app.schemas.learning import LearningPlanView, LearningTaskView, ReviewScheduleView, WeaknessTrackerView

__all__ = [
    "CareerApplicationSummaryView",
    "CareerApplicationWorkbenchView",
    "CareerLearningSummaryView",
    "CareerLinkedAssetView",
    "CareerNoteSummaryView",
    "CareerReadinessView",
    "CareerSuggestedActionView",
    "CareerTimelineItemView",
    "CareerWorkbenchCountsView",
    "CareerWorkbenchListView",
]


class CareerReadinessView(BaseModel):
    score: int | None = None
    level: str = "unknown"
    recommendation: str = "unknown"
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    missing_materials: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class CareerLinkedAssetView(BaseModel):
    type: str
    id: str
    title: str
    subtitle: str = ""
    status: str = "active"
    updated_at: datetime | None = None
    preview_artifact_id: str | None = None
    source_session_id: str | None = None
    is_current: bool = False
    actions: list[str] = Field(default_factory=list)


class CareerTimelineItemView(BaseModel):
    type: str
    title: str
    subtitle: str = ""
    occurred_at: datetime
    source_type: str
    source_id: str


class CareerSuggestedActionView(BaseModel):
    action_type: str
    label: str
    prompt_intent: str
    priority: str = "medium"
    enabled: bool = True
    reason: str = ""


class CareerNoteSummaryView(BaseModel):
    note_id: str
    title: str
    summary: str = ""
    status: str = "active"
    updated_at: datetime
    note_type: str = "note"
    source_artifact_id: str | None = None
    related_application_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class CareerLearningSummaryView(BaseModel):
    plans: list[LearningPlanView] = Field(default_factory=list)
    tasks: list[LearningTaskView] = Field(default_factory=list)
    weaknesses: list[WeaknessTrackerView] = Field(default_factory=list)
    reviews: list[ReviewScheduleView] = Field(default_factory=list)
    open_task_count: int = 0
    done_task_count: int = 0
    high_weakness_count: int = 0


class CareerApplicationSummaryView(BaseModel):
    application: CareerApplicationView
    readiness: CareerReadinessView
    linked_asset_count: int = 0
    note_count: int = 0
    learning_task_count: int = 0
    updated_at: datetime


class CareerWorkbenchCountsView(BaseModel):
    applications: int = 0
    active_applications: int = 0
    notes: int = 0
    learning_tasks: int = 0
    resume_versions: int = 0


class CareerWorkbenchListView(BaseModel):
    applications: list[CareerApplicationSummaryView] = Field(default_factory=list)
    active_application_id: str | None = None
    counts: CareerWorkbenchCountsView = Field(default_factory=CareerWorkbenchCountsView)
    updated_at: datetime | None = None


class CareerApplicationWorkbenchView(BaseModel):
    application: CareerApplicationView
    resume_profile: ResumeProfileView | None = None
    career_profile: CareerProfileView | None = None
    jd_analysis: JDAnalysisView | None = None
    job_fit_report: JobFitReportView | None = None
    resume_versions: list[ResumeVersionView] = Field(default_factory=list)
    readiness: CareerReadinessView
    linked_assets: list[CareerLinkedAssetView] = Field(default_factory=list)
    notes: list[CareerNoteSummaryView] = Field(default_factory=list)
    learning: CareerLearningSummaryView
    timeline: list[CareerTimelineItemView] = Field(default_factory=list)
    suggested_actions: list[CareerSuggestedActionView] = Field(default_factory=list)
