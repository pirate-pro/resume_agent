"""HTTP response presenters for API DTOs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, cast

from app.career.models import CareerApplication, CareerProfile, JDAnalysis, JobFitReport, ResumeProfile, ResumeVersion
from app.career.workbench import (
    CareerApplicationSummary,
    CareerApplicationWorkbench,
    CareerLearningSummary,
    CareerLinkedAsset,
    CareerNoteSummary,
    CareerReadiness,
    CareerSuggestedAction,
    CareerTimelineItem,
    CareerWorkbenchCounts,
    CareerWorkbenchList,
)
from app.domain.models import EventRecord, MemoryItem, SessionMeta
from app.knowledge.models import (
    CompanyProfile,
    ExperiencePost,
    ExternalResource,
    InterviewQuestion,
    SkillRequirement,
)
from app.learning.models import LearningPlan, LearningTask, ProgressCheckin, ReviewSchedule, WeaknessTracker
from app.notes.models import Note, NoteCollection, NoteSourceRef, NoteType
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
from app.schemas.career_workbench import (
    CareerApplicationSummaryView,
    CareerApplicationWorkbenchView,
    CareerLearningSummaryView,
    CareerLinkedAssetView,
    CareerNoteSummaryView,
    CareerReadinessView,
    CareerSuggestedActionView,
    CareerTimelineItemView,
    CareerWorkbenchCountsView,
    CareerWorkbenchListView,
)
from app.schemas.knowledge import (
    CompanyProfileView,
    ExperiencePostView,
    ExternalResourceView,
    InterviewQuestionView,
    SkillRequirementView,
)
from app.schemas.learning import (
    LearningPlanView,
    LearningTaskView,
    ProgressCheckinView,
    ReviewScheduleView,
    WeaknessTrackerView,
)
from app.schemas.notes import NoteCollectionView, NoteSourceRefPayload, NoteView
from app.services.answer_normalizer import AnswerFormat, LayoutHint, RenderHint, SourceKind

__all__ = [
    "career_application_view",
    "career_application_summary_view",
    "career_application_workbench_view",
    "career_learning_summary_view",
    "career_linked_asset_view",
    "career_note_summary_view",
    "career_profile_view",
    "career_readiness_view",
    "career_suggested_action_view",
    "career_timeline_item_view",
    "career_workbench_counts_view",
    "career_workbench_list_view",
    "company_profile_view",
    "event_view",
    "experience_post_view",
    "external_resource_view",
    "interview_question_view",
    "jd_analysis_view",
    "job_fit_report_view",
    "learning_plan_view",
    "learning_task_view",
    "memory_view",
    "note_collection_view",
    "note_view",
    "progress_checkin_view",
    "review_schedule_view",
    "resume_profile_view",
    "resume_version_view",
    "session_item_view",
    "session_message_view",
    "skill_summary_view",
    "skill_requirement_view",
    "weakness_tracker_view",
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


def career_readiness_view(item: CareerReadiness) -> CareerReadinessView:
    return CareerReadinessView(
        score=item.score,
        level=item.level,
        recommendation=item.recommendation,
        summary=item.summary,
        strengths=item.strengths,
        risks=item.risks,
        missing_materials=item.missing_materials,
        next_actions=item.next_actions,
    )


def career_linked_asset_view(item: CareerLinkedAsset) -> CareerLinkedAssetView:
    return CareerLinkedAssetView(
        type=item.type,
        id=item.id,
        title=item.title,
        subtitle=item.subtitle,
        status=item.status,
        updated_at=item.updated_at,
        preview_artifact_id=item.preview_artifact_id,
        source_session_id=item.source_session_id,
        is_current=item.is_current,
        actions=item.actions,
    )


def career_timeline_item_view(item: CareerTimelineItem) -> CareerTimelineItemView:
    return CareerTimelineItemView(
        type=item.type,
        title=item.title,
        subtitle=item.subtitle,
        occurred_at=item.occurred_at,
        source_type=item.source_type,
        source_id=item.source_id,
    )


def career_suggested_action_view(item: CareerSuggestedAction) -> CareerSuggestedActionView:
    return CareerSuggestedActionView(
        action_type=item.action_type,
        label=item.label,
        prompt_intent=item.prompt_intent,
        priority=item.priority,
        enabled=item.enabled,
        reason=item.reason,
    )


def career_note_summary_view(item: CareerNoteSummary) -> CareerNoteSummaryView:
    return CareerNoteSummaryView(
        note_id=item.note_id,
        title=item.title,
        summary=item.summary,
        status=item.status,
        updated_at=item.updated_at,
        note_type=item.note_type,
        source_artifact_id=item.source_artifact_id,
        related_application_id=item.related_application_id,
        tags=item.tags,
    )


def career_learning_summary_view(item: CareerLearningSummary) -> CareerLearningSummaryView:
    return CareerLearningSummaryView(
        plans=[learning_plan_view(plan) for plan in item.plans],
        tasks=[learning_task_view(task) for task in item.tasks],
        weaknesses=[weakness_tracker_view(weakness) for weakness in item.weaknesses],
        reviews=[review_schedule_view(review) for review in item.reviews],
        open_task_count=item.open_task_count,
        done_task_count=item.done_task_count,
        high_weakness_count=item.high_weakness_count,
    )


def career_application_summary_view(item: CareerApplicationSummary) -> CareerApplicationSummaryView:
    return CareerApplicationSummaryView(
        application=career_application_view(item.application),
        readiness=career_readiness_view(item.readiness),
        linked_asset_count=item.linked_asset_count,
        note_count=item.note_count,
        learning_task_count=item.learning_task_count,
        updated_at=item.updated_at,
    )


def career_workbench_counts_view(item: CareerWorkbenchCounts) -> CareerWorkbenchCountsView:
    return CareerWorkbenchCountsView(
        applications=item.applications,
        active_applications=item.active_applications,
        notes=item.notes,
        learning_tasks=item.learning_tasks,
        resume_versions=item.resume_versions,
    )


def career_workbench_list_view(item: CareerWorkbenchList) -> CareerWorkbenchListView:
    return CareerWorkbenchListView(
        applications=[career_application_summary_view(summary) for summary in item.applications],
        active_application_id=item.active_application_id,
        counts=career_workbench_counts_view(item.counts),
        updated_at=item.updated_at,
    )


def career_application_workbench_view(item: CareerApplicationWorkbench) -> CareerApplicationWorkbenchView:
    return CareerApplicationWorkbenchView(
        application=career_application_view(item.application),
        resume_profile=resume_profile_view(item.resume_profile) if item.resume_profile is not None else None,
        career_profile=career_profile_view(item.career_profile) if item.career_profile is not None else None,
        jd_analysis=jd_analysis_view(item.jd_analysis) if item.jd_analysis is not None else None,
        job_fit_report=job_fit_report_view(item.job_fit_report) if item.job_fit_report is not None else None,
        resume_versions=[resume_version_view(version) for version in item.resume_versions],
        readiness=career_readiness_view(item.readiness),
        linked_assets=[career_linked_asset_view(asset) for asset in item.linked_assets],
        notes=[career_note_summary_view(note) for note in item.notes],
        learning=career_learning_summary_view(item.learning),
        timeline=[career_timeline_item_view(timeline_item) for timeline_item in item.timeline],
        suggested_actions=[career_suggested_action_view(action) for action in item.suggested_actions],
    )


def note_view(item: Note) -> NoteView:
    return NoteView(
        note_id=item.note_id,
        status=item.status.value,
        source_session_id=item.source_session_id,
        source_artifact_id=item.source_artifact_id,
        evidence_refs=item.evidence_refs,
        created_at=item.created_at,
        updated_at=item.updated_at,
        title=item.title,
        body_markdown=item.body_markdown,
        body_format=item.body_format,
        note_type=cast(NoteType, item.note_type).value,
        collection_id=item.collection_id,
        tags=item.tags,
        source_refs=[note_source_ref_view(source_ref) for source_ref in item.source_refs],
        related_application_id=item.related_application_id,
        summary=item.summary,
    )


def note_collection_view(item: NoteCollection) -> NoteCollectionView:
    return NoteCollectionView(
        collection_id=item.collection_id,
        status=item.status.value,
        source_session_id=item.source_session_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        name=item.name,
        description=item.description,
        kind=item.kind.value,
        tags=item.tags,
    )


def note_source_ref_view(item: NoteSourceRef) -> NoteSourceRefPayload:
    source_type = item.source_type.value if not isinstance(item.source_type, str) else item.source_type
    return NoteSourceRefPayload(
        source_type=source_type,
        source_id=item.source_id,
        source_session_id=item.source_session_id,
        title=item.title,
        quote=item.quote,
    )


def external_resource_view(item: ExternalResource) -> ExternalResourceView:
    return ExternalResourceView(
        resource_id=item.resource_id,
        **_knowledge_meta(item),
        title=item.title,
        resource_type=_enum_value(item.resource_type),
        url=item.url,
        provider=item.provider,
        company=item.company,
        position=item.position,
        target_roles=item.target_roles,
        skill_tags=item.skill_tags,
        summary=item.summary,
        key_points=item.key_points,
        raw_artifact_id=item.raw_artifact_id,
        related_application_ids=item.related_application_ids,
        related_note_ids=item.related_note_ids,
    )


def experience_post_view(item: ExperiencePost) -> ExperiencePostView:
    return ExperiencePostView(
        experience_id=item.experience_id,
        **_knowledge_meta(item),
        source_resource_id=item.source_resource_id,
        company=item.company,
        position=item.position,
        seniority=item.seniority,
        interview_rounds=item.interview_rounds,
        interview_process=item.interview_process,
        questions=item.questions,
        outcome=item.outcome,
        difficulty=_enum_value(item.difficulty),
        summary=item.summary,
        tags=item.tags,
        related_application_ids=item.related_application_ids,
        related_note_ids=item.related_note_ids,
    )


def interview_question_view(item: InterviewQuestion) -> InterviewQuestionView:
    return InterviewQuestionView(
        question_id=item.question_id,
        **_knowledge_meta(item),
        question_text=item.question_text,
        question_type=_enum_value(item.question_type),
        difficulty=_enum_value(item.difficulty),
        skill_tags=item.skill_tags,
        company=item.company,
        position=item.position,
        source_resource_id=item.source_resource_id,
        source_experience_id=item.source_experience_id,
        answer_outline=item.answer_outline,
        evaluation_points=item.evaluation_points,
        common_pitfalls=item.common_pitfalls,
        related_application_ids=item.related_application_ids,
        related_note_ids=item.related_note_ids,
    )


def company_profile_view(item: CompanyProfile) -> CompanyProfileView:
    return CompanyProfileView(
        company_id=item.company_id,
        **_knowledge_meta(item),
        company_name=item.company_name,
        aliases=item.aliases,
        industries=item.industries,
        target_roles=item.target_roles,
        hiring_signals=item.hiring_signals,
        interview_style=item.interview_style,
        common_questions=item.common_questions,
        resource_ids=item.resource_ids,
        question_ids=item.question_ids,
        summary=item.summary,
    )


def skill_requirement_view(item: SkillRequirement) -> SkillRequirementView:
    return SkillRequirementView(
        skill_requirement_id=item.skill_requirement_id,
        **_knowledge_meta(item),
        skill_name=item.skill_name,
        category=_enum_value(item.category),
        level=_enum_value(item.level),
        description=item.description,
        assessment_points=item.assessment_points,
        role_tags=item.role_tags,
        company_ids=item.company_ids,
        resource_ids=item.resource_ids,
        question_ids=item.question_ids,
    )


def learning_plan_view(item: LearningPlan) -> LearningPlanView:
    return LearningPlanView(
        learning_plan_id=item.learning_plan_id,
        **_learning_meta(item),
        title=item.title,
        description=item.description,
        plan_type=_enum_value(item.plan_type),
        target_application_id=item.target_application_id,
        target_role=item.target_role,
        target_company=item.target_company,
        start_date=item.start_date,
        end_date=item.end_date,
        priority=_enum_value(item.priority),
        goals=item.goals,
        focus_skill_tags=item.focus_skill_tags,
        task_ids=item.task_ids,
        weakness_ids=item.weakness_ids,
        review_schedule_ids=item.review_schedule_ids,
        progress_summary=item.progress_summary,
    )


def learning_task_view(item: LearningTask) -> LearningTaskView:
    return LearningTaskView(
        learning_task_id=item.learning_task_id,
        **_learning_meta(item),
        title=item.title,
        learning_plan_id=item.learning_plan_id,
        description=item.description,
        task_type=_enum_value(item.task_type),
        priority=_enum_value(item.priority),
        state=_enum_value(item.state),
        skill_tags=item.skill_tags,
        estimated_minutes=item.estimated_minutes,
        planned_start_date=item.planned_start_date,
        due_date=item.due_date,
        completed_at=item.completed_at,
        resource_refs=item.resource_refs,
        question_refs=item.question_refs,
        note_refs=item.note_refs,
        output_artifact_id=item.output_artifact_id,
        success_criteria=item.success_criteria,
        progress_notes=item.progress_notes,
    )


def progress_checkin_view(item: ProgressCheckin) -> ProgressCheckinView:
    return ProgressCheckinView(
        checkin_id=item.checkin_id,
        **_learning_meta(item),
        learning_plan_id=item.learning_plan_id,
        learning_task_id=item.learning_task_id,
        checkin_date=item.checkin_date,
        minutes_spent=item.minutes_spent,
        progress_state=_enum_value(item.progress_state),
        summary=item.summary,
        blockers=item.blockers,
        confidence=_enum_value(item.confidence),
        next_action=item.next_action,
        note_refs=item.note_refs,
    )


def weakness_tracker_view(item: WeaknessTracker) -> WeaknessTrackerView:
    return WeaknessTrackerView(
        weakness_id=item.weakness_id,
        **_learning_meta(item),
        title=item.title,
        description=item.description,
        weakness_type=_enum_value(item.weakness_type),
        severity=_enum_value(item.severity),
        state=_enum_value(item.state),
        skill_tags=item.skill_tags,
        target_application_ids=item.target_application_ids,
        source_report_ids=item.source_report_ids,
        related_task_ids=item.related_task_ids,
        related_note_ids=item.related_note_ids,
        last_observed_at=item.last_observed_at,
        resolved_at=item.resolved_at,
        resolution_summary=item.resolution_summary,
    )


def review_schedule_view(item: ReviewSchedule) -> ReviewScheduleView:
    return ReviewScheduleView(
        review_schedule_id=item.review_schedule_id,
        **_learning_meta(item),
        title=item.title,
        learning_plan_id=item.learning_plan_id,
        learning_task_id=item.learning_task_id,
        weakness_id=item.weakness_id,
        review_type=_enum_value(item.review_type),
        review_at=item.review_at,
        interval_days=item.interval_days,
        state=_enum_value(item.state),
        resource_refs=item.resource_refs,
        question_refs=item.question_refs,
        note_refs=item.note_refs,
        last_reviewed_at=item.last_reviewed_at,
        next_review_at=item.next_review_at,
        summary=item.summary,
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


def _knowledge_meta(
    item: ExternalResource | ExperiencePost | InterviewQuestion | CompanyProfile | SkillRequirement,
) -> dict[str, Any]:
    return {
        "status": item.status.value,
        "source_session_id": item.source_session_id,
        "source_artifact_id": item.source_artifact_id,
        "evidence_refs": item.evidence_refs,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _learning_meta(
    item: LearningPlan | LearningTask | ProgressCheckin | WeaknessTracker | ReviewSchedule,
) -> dict[str, Any]:
    return {
        "status": _enum_value(item.status),
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


def _enum_value(raw: Enum | str) -> str:
    if isinstance(raw, str):
        return raw
    return str(raw.value)
