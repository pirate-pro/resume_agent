"""HTTP schemas for external career knowledge endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "CompanyProfileCreateRequest",
    "CompanyProfileUpdateRequest",
    "CompanyProfileView",
    "ExperiencePostCreateRequest",
    "ExperiencePostUpdateRequest",
    "ExperiencePostView",
    "ExternalResourceCreateRequest",
    "ExternalResourceUpdateRequest",
    "ExternalResourceView",
    "InterviewQuestionCreateRequest",
    "InterviewQuestionUpdateRequest",
    "InterviewQuestionView",
    "SkillRequirementCreateRequest",
    "SkillRequirementUpdateRequest",
    "SkillRequirementView",
]


class KnowledgeRecordMetaView(BaseModel):
    status: str
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ExternalResourceView(KnowledgeRecordMetaView):
    resource_id: str
    title: str
    resource_type: str
    url: str | None = None
    provider: str = ""
    company: str = ""
    position: str = ""
    target_roles: list[str] = Field(default_factory=list)
    skill_tags: list[str] = Field(default_factory=list)
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    raw_artifact_id: str | None = None
    related_application_ids: list[str] = Field(default_factory=list)
    related_note_ids: list[str] = Field(default_factory=list)


class ExperiencePostView(KnowledgeRecordMetaView):
    experience_id: str
    source_resource_id: str | None = None
    company: str = ""
    position: str = ""
    seniority: str = ""
    interview_rounds: list[Any] = Field(default_factory=list)
    interview_process: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    outcome: str = ""
    difficulty: str = "unknown"
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    related_application_ids: list[str] = Field(default_factory=list)
    related_note_ids: list[str] = Field(default_factory=list)


class InterviewQuestionView(KnowledgeRecordMetaView):
    question_id: str
    question_text: str
    question_type: str
    difficulty: str = "unknown"
    skill_tags: list[str] = Field(default_factory=list)
    company: str = ""
    position: str = ""
    source_resource_id: str | None = None
    source_experience_id: str | None = None
    answer_outline: str = ""
    evaluation_points: list[str] = Field(default_factory=list)
    common_pitfalls: list[str] = Field(default_factory=list)
    related_application_ids: list[str] = Field(default_factory=list)
    related_note_ids: list[str] = Field(default_factory=list)


class CompanyProfileView(KnowledgeRecordMetaView):
    company_id: str
    company_name: str
    aliases: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    hiring_signals: list[str] = Field(default_factory=list)
    interview_style: str = ""
    common_questions: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)
    summary: str = ""


class SkillRequirementView(KnowledgeRecordMetaView):
    skill_requirement_id: str
    skill_name: str
    category: str
    level: str
    description: str = ""
    assessment_points: list[str] = Field(default_factory=list)
    role_tags: list[str] = Field(default_factory=list)
    company_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)


class ExternalResourceCreateRequest(BaseModel):
    resource_id: str | None = None
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    title: str
    resource_type: str = "other"
    url: str | None = None
    provider: str = ""
    company: str = ""
    position: str = ""
    target_roles: list[str] = Field(default_factory=list)
    skill_tags: list[str] = Field(default_factory=list)
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    raw_artifact_id: str | None = None
    related_application_ids: list[str] = Field(default_factory=list)
    related_note_ids: list[str] = Field(default_factory=list)


class ExternalResourceUpdateRequest(BaseModel):
    source_artifact_id: str | None = None
    evidence_refs: list[str] | None = None
    title: str | None = None
    resource_type: str | None = None
    url: str | None = None
    provider: str | None = None
    company: str | None = None
    position: str | None = None
    target_roles: list[str] | None = None
    skill_tags: list[str] | None = None
    summary: str | None = None
    key_points: list[str] | None = None
    raw_artifact_id: str | None = None
    related_application_ids: list[str] | None = None
    related_note_ids: list[str] | None = None


class ExperiencePostCreateRequest(BaseModel):
    experience_id: str | None = None
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    source_resource_id: str | None = None
    company: str = ""
    position: str = ""
    seniority: str = ""
    interview_rounds: list[Any] = Field(default_factory=list)
    interview_process: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    outcome: str = ""
    difficulty: str = "unknown"
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    related_application_ids: list[str] = Field(default_factory=list)
    related_note_ids: list[str] = Field(default_factory=list)


class ExperiencePostUpdateRequest(BaseModel):
    source_artifact_id: str | None = None
    evidence_refs: list[str] | None = None
    source_resource_id: str | None = None
    company: str | None = None
    position: str | None = None
    seniority: str | None = None
    interview_rounds: list[Any] | None = None
    interview_process: list[str] | None = None
    questions: list[str] | None = None
    outcome: str | None = None
    difficulty: str | None = None
    summary: str | None = None
    tags: list[str] | None = None
    related_application_ids: list[str] | None = None
    related_note_ids: list[str] | None = None


class InterviewQuestionCreateRequest(BaseModel):
    question_id: str | None = None
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    question_text: str
    question_type: str = "other"
    difficulty: str = "unknown"
    skill_tags: list[str] = Field(default_factory=list)
    company: str = ""
    position: str = ""
    source_resource_id: str | None = None
    source_experience_id: str | None = None
    answer_outline: str = ""
    evaluation_points: list[str] = Field(default_factory=list)
    common_pitfalls: list[str] = Field(default_factory=list)
    related_application_ids: list[str] = Field(default_factory=list)
    related_note_ids: list[str] = Field(default_factory=list)


class InterviewQuestionUpdateRequest(BaseModel):
    source_artifact_id: str | None = None
    evidence_refs: list[str] | None = None
    question_text: str | None = None
    question_type: str | None = None
    difficulty: str | None = None
    skill_tags: list[str] | None = None
    company: str | None = None
    position: str | None = None
    source_resource_id: str | None = None
    source_experience_id: str | None = None
    answer_outline: str | None = None
    evaluation_points: list[str] | None = None
    common_pitfalls: list[str] | None = None
    related_application_ids: list[str] | None = None
    related_note_ids: list[str] | None = None


class CompanyProfileCreateRequest(BaseModel):
    company_id: str | None = None
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    company_name: str
    aliases: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    hiring_signals: list[str] = Field(default_factory=list)
    interview_style: str = ""
    common_questions: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)
    summary: str = ""


class CompanyProfileUpdateRequest(BaseModel):
    source_artifact_id: str | None = None
    evidence_refs: list[str] | None = None
    company_name: str | None = None
    aliases: list[str] | None = None
    industries: list[str] | None = None
    target_roles: list[str] | None = None
    hiring_signals: list[str] | None = None
    interview_style: str | None = None
    common_questions: list[str] | None = None
    resource_ids: list[str] | None = None
    question_ids: list[str] | None = None
    summary: str | None = None


class SkillRequirementCreateRequest(BaseModel):
    skill_requirement_id: str | None = None
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    skill_name: str
    category: str = "other"
    level: str = "working"
    description: str = ""
    assessment_points: list[str] = Field(default_factory=list)
    role_tags: list[str] = Field(default_factory=list)
    company_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)


class SkillRequirementUpdateRequest(BaseModel):
    source_artifact_id: str | None = None
    evidence_refs: list[str] | None = None
    skill_name: str | None = None
    category: str | None = None
    level: str | None = None
    description: str | None = None
    assessment_points: list[str] | None = None
    role_tags: list[str] | None = None
    company_ids: list[str] | None = None
    resource_ids: list[str] | None = None
    question_ids: list[str] | None = None
