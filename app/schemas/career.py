"""HTTP response schemas for career product endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "CareerApplicationUpdateRequest",
    "CareerApplicationView",
    "CareerProfileView",
    "JDAnalysisView",
    "JobFitReportView",
    "ResumeProfileView",
    "ResumeVersionDraftAcceptRequest",
    "ResumeVersionDraftAcceptResponse",
    "ResumeVersionDraftGenerateRequest",
    "ResumeVersionDraftGenerateResponse",
    "ResumeVersionDraftView",
    "ResumeVersionView",
]


class CareerRecordMetaView(BaseModel):
    status: str
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ResumeProfileView(CareerRecordMetaView):
    resume_profile_id: str
    basic_info: dict[str, Any] = Field(default_factory=dict)
    education: list[Any] = Field(default_factory=list)
    work_experience: list[Any] = Field(default_factory=list)
    project_experience: list[Any] = Field(default_factory=list)
    skills: list[Any] = Field(default_factory=list)
    certificates: list[Any] = Field(default_factory=list)
    awards: list[Any] = Field(default_factory=list)
    self_evaluation: str = ""
    raw_text_artifact_id: str | None = None
    diagnosis_artifact_id: str | None = None
    diagnosis: dict[str, Any] = Field(default_factory=dict)


class CareerProfileView(CareerRecordMetaView):
    career_profile_id: str
    career_goal: str = ""
    target_roles: list[str] = Field(default_factory=list)
    preferred_industries: list[str] = Field(default_factory=list)
    preferred_cities: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    education_summary: str = ""
    experience_summary: str = ""
    resume_issues: list[str] = Field(default_factory=list)
    interview_weaknesses: list[str] = Field(default_factory=list)


class JDAnalysisView(CareerRecordMetaView):
    jd_analysis_id: str
    company: str = ""
    position: str = ""
    seniority: str = ""
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)
    interview_focus: list[str] = Field(default_factory=list)


class JobFitReportView(CareerRecordMetaView):
    job_fit_report_id: str
    jd_analysis_id: str
    resume_profile_id: str
    career_profile_id: str
    overall_score: int = 0
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    matched_evidence: list[Any] = Field(default_factory=list)
    gaps: list[Any] = Field(default_factory=list)
    resume_optimization_direction: list[Any] = Field(default_factory=list)
    interview_preparation_focus: list[Any] = Field(default_factory=list)
    recommendation: str = "cautious"
    report_artifact_id: str | None = None


class ResumeVersionView(CareerRecordMetaView):
    resume_version_id: str
    base_resume_profile_id: str
    target_jd_analysis_id: str | None = None
    title: str
    format: str
    artifact_id: str
    change_summary: list[str] = Field(default_factory=list)
    keyword_strategy: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class ResumeVersionDraftView(CareerRecordMetaView):
    resume_version_draft_id: str
    base_resume_profile_id: str
    target_jd_analysis_id: str | None = None
    application_id: str | None = None
    job_fit_report_id: str | None = None
    title: str
    format: str
    markdown: str
    change_summary: list[str] = Field(default_factory=list)
    keyword_strategy: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    draft_source: str = "deterministic"
    accepted_resume_version_id: str | None = None


class ResumeVersionDraftGenerateRequest(BaseModel):
    application_id: str | None = None
    resume_profile_id: str | None = None
    base_resume_version_id: str | None = None
    target_jd_analysis_id: str | None = None
    job_fit_report_id: str | None = None
    title: str | None = None
    strategy: list[str] = Field(default_factory=list)


class ResumeVersionDraftGenerateResponse(BaseModel):
    draft: ResumeVersionDraftView


class ResumeVersionDraftAcceptRequest(BaseModel):
    title: str | None = None
    markdown: str | None = None
    link_application: bool = True


class ResumeVersionDraftAcceptResponse(BaseModel):
    draft: ResumeVersionDraftView
    resume_version: ResumeVersionView


class CareerApplicationView(CareerRecordMetaView):
    application_id: str
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
    resume_version_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    next_actions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    notes: str = ""


class CareerApplicationUpdateRequest(BaseModel):
    stage: str | None = None
    priority: str | None = None
    summary: str | None = None
    next_actions: list[str] | None = None
    risks: list[str] | None = None
    notes: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    source_artifact_id: str | None = None
