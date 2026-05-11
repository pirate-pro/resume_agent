"""HTTP response presenters for API DTOs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, cast

from app.career.models import CareerApplication, CareerProfile, JDAnalysis, JobFitReport, ResumeProfile, ResumeVersion
from app.domain.models import EventRecord, MemoryItem, SessionMeta
from app.schemas.chat import (
    AnswerArtifactView,
    EventView,
    MemoryView,
    SessionListItem,
    SessionMessage,
    SkillSummaryView,
    ToolCallView,
)
from app.schemas.career import (
    CareerApplicationView,
    CareerProfileView,
    JDAnalysisView,
    JobFitReportView,
    ResumeProfileView,
    ResumeVersionView,
)
from app.services.answer_normalizer import AnswerFormat, LayoutHint, RenderHint, SourceKind

__all__ = [
    "career_application_view",
    "career_profile_view",
    "event_view",
    "jd_analysis_view",
    "job_fit_report_view",
    "memory_view",
    "resume_profile_view",
    "resume_version_view",
    "session_item_view",
    "session_message_view",
    "skill_summary_view",
]

_ANSWER_FORMATS = {"plain_text", "markdown", "code", "markdown_source"}
_RENDER_HINTS = {"plain", "markdown_document", "markdown_source", "code_block", "large_document"}
_LAYOUT_HINTS = {"brief", "paragraph", "bullets", "steps"}
_SOURCE_KINDS = {"direct_answer", "generated_document", "file_content", "summary"}


class SkillSummaryLike(Protocol):
    name: str
    description: str


def session_item_view(item: SessionMeta) -> SessionListItem:
    return SessionListItem(
        session_id=item.session_id,
        title=item.title,
        created_at=item.created_at,
        updated_at=item.updated_at,
        is_pinned=item.is_pinned,
        pinned_at=item.pinned_at,
    )


def skill_summary_view(item: SkillSummaryLike) -> SkillSummaryView:
    return SkillSummaryView(name=item.name, description=item.description)


def event_view(item: EventRecord) -> EventView:
    return EventView(
        event_id=item.event_id,
        session_id=item.session_id,
        agent_id=item.agent_id,
        run_id=item.run_id,
        parent_run_id=item.parent_run_id,
        event_version=item.event_version,
        type=item.type,
        payload=item.payload,
        created_at=item.created_at,
    )


def memory_view(item: MemoryItem) -> MemoryView:
    return MemoryView(memory_id=item.memory_id, content=item.content, tags=item.tags)


def resume_profile_view(item: ResumeProfile) -> ResumeProfileView:
    return ResumeProfileView(
        resume_profile_id=item.resume_profile_id,
        **_career_meta(item),
        basic_info=item.basic_info,
        education=item.education,
        work_experience=item.work_experience,
        project_experience=item.project_experience,
        skills=item.skills,
        certificates=item.certificates,
        awards=item.awards,
        self_evaluation=item.self_evaluation,
        raw_text_artifact_id=item.raw_text_artifact_id,
        diagnosis_artifact_id=item.diagnosis_artifact_id,
        diagnosis=item.diagnosis,
    )


def career_profile_view(item: CareerProfile) -> CareerProfileView:
    return CareerProfileView(
        career_profile_id=item.career_profile_id,
        **_career_meta(item),
        career_goal=item.career_goal,
        target_roles=item.target_roles,
        preferred_industries=item.preferred_industries,
        preferred_cities=item.preferred_cities,
        strengths=item.strengths,
        weaknesses=item.weaknesses,
        skills=item.skills,
        interests=item.interests,
        education_summary=item.education_summary,
        experience_summary=item.experience_summary,
        resume_issues=item.resume_issues,
        interview_weaknesses=item.interview_weaknesses,
    )


def jd_analysis_view(item: JDAnalysis) -> JDAnalysisView:
    return JDAnalysisView(
        jd_analysis_id=item.jd_analysis_id,
        **_career_meta(item),
        company=item.company,
        position=item.position,
        seniority=item.seniority,
        required_skills=item.required_skills,
        preferred_skills=item.preferred_skills,
        responsibilities=item.responsibilities,
        keywords=item.keywords,
        risk_signals=item.risk_signals,
        interview_focus=item.interview_focus,
    )


def job_fit_report_view(item: JobFitReport) -> JobFitReportView:
    return JobFitReportView(
        job_fit_report_id=item.job_fit_report_id,
        **_career_meta(item),
        jd_analysis_id=item.jd_analysis_id,
        resume_profile_id=item.resume_profile_id,
        career_profile_id=item.career_profile_id,
        overall_score=item.overall_score,
        score_breakdown=item.score_breakdown,
        matched_evidence=item.matched_evidence,
        gaps=item.gaps,
        resume_optimization_direction=item.resume_optimization_direction,
        interview_preparation_focus=item.interview_preparation_focus,
        recommendation=item.recommendation,
        report_artifact_id=item.report_artifact_id,
    )


def resume_version_view(item: ResumeVersion) -> ResumeVersionView:
    return ResumeVersionView(
        resume_version_id=item.resume_version_id,
        **_career_meta(item),
        base_resume_profile_id=item.base_resume_profile_id,
        target_jd_analysis_id=item.target_jd_analysis_id,
        title=item.title,
        format=item.format,
        artifact_id=item.artifact_id,
        change_summary=item.change_summary,
        keyword_strategy=item.keyword_strategy,
        risk_notes=item.risk_notes,
    )


def career_application_view(item: CareerApplication) -> CareerApplicationView:
    return CareerApplicationView(
        application_id=item.application_id,
        **_career_meta(item),
        company=item.company,
        position=item.position,
        location=item.location,
        job_url=item.job_url,
        stage=item.stage,
        priority=item.priority,
        resume_profile_id=item.resume_profile_id,
        career_profile_id=item.career_profile_id,
        jd_analysis_id=item.jd_analysis_id,
        job_fit_report_id=item.job_fit_report_id,
        resume_version_ids=item.resume_version_ids,
        summary=item.summary,
        next_actions=item.next_actions,
        risks=item.risks,
        notes=item.notes,
    )


def session_message_view(raw: Mapping[str, object]) -> SessionMessage:
    return SessionMessage(
        role=str(raw.get("role", "")),
        content=str(raw.get("content", "")),
        answer_format=cast(AnswerFormat, _enum_text(raw.get("answer_format"), _ANSWER_FORMATS, "plain_text")),
        render_hint=cast(RenderHint, _enum_text(raw.get("render_hint"), _RENDER_HINTS, "plain")),
        layout_hint=cast(LayoutHint, _enum_text(raw.get("layout_hint"), _LAYOUT_HINTS, "paragraph")),
        source_kind=cast(SourceKind, _enum_text(raw.get("source_kind"), _SOURCE_KINDS, "direct_answer")),
        artifacts=_artifact_views(raw.get("artifacts")),
        tool_calls=_tool_call_views(raw.get("tool_calls")),
        created_at=_optional_datetime(raw.get("created_at")),
    )


def _artifact_views(raw: object) -> list[AnswerArtifactView]:
    rows = raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)) else []
    return [
        AnswerArtifactView(
            type=str(item.get("type", "")),
            path=str(item.get("path", "")),
            role=str(item.get("role", "")),
        )
        for item in rows
        if isinstance(item, Mapping)
    ]


def _tool_call_views(raw: object) -> list[ToolCallView]:
    rows = raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)) else []
    return [
        ToolCallView(
            name=str(item.get("name", "")),
            arguments=_dict_value(item.get("arguments")),
        )
        for item in rows
        if isinstance(item, Mapping)
    ]


def _dict_value(raw: object) -> dict[str, Any]:
    return {str(k): v for k, v in raw.items()} if isinstance(raw, Mapping) else {}


def _career_meta(
    item: ResumeProfile | CareerProfile | JDAnalysis | JobFitReport | ResumeVersion | CareerApplication,
) -> dict[str, Any]:
    return {
        "status": item.status.value,
        "source_session_id": item.source_session_id,
        "source_artifact_id": item.source_artifact_id,
        "evidence_refs": item.evidence_refs,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _enum_text(raw: object, allowed: set[str], default: str) -> str:
    text = str(raw or "").strip()
    return text if text in allowed else default


def _optional_datetime(raw: object) -> datetime | None:
    return raw if isinstance(raw, datetime) else None
