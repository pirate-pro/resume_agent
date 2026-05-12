"""Read-only adapters from product stores to retrieval hits."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import Enum
from typing import Any

from app.career.store import CareerProductStore
from app.core.errors import SessionNotFoundError, StorageError
from app.domain.models import SessionArtifact
from app.domain.protocols import SessionRepository
from app.knowledge.store import KnowledgeStore
from app.learning.store import LearningStore
from app.notes.store import NoteStore
from app.retrieval.models import RetrievalHit, RetrievalQuery, RetrievalSourceRef, RetrievalSourceType

__all__ = [
    "build_career_hits",
    "build_knowledge_hits",
    "build_learning_hits",
    "build_note_hits",
    "build_session_artifact_hits",
]

_QUERY_TERM_RE = re.compile(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]{2,}")


def build_career_hits(store: CareerProductStore, request: RetrievalQuery) -> list[RetrievalHit]:
    """Build hits from career product records."""

    hits: list[RetrievalHit] = []
    if request.allows(RetrievalSourceType.CAREER_APPLICATION):
        for application in store.list_career_applications(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.CAREER_APPLICATION,
                    source_id=application.application_id,
                    title=_join_non_empty(application.company, application.position) or application.application_id,
                    summary=application.summary,
                    body=_join_lists(application.next_actions, application.risks, [application.notes]),
                    tags=[application.company, application.position, application.stage, application.priority],
                    updated_at=application.updated_at,
                    evidence_refs=application.evidence_refs,
                    source_session_id=application.source_session_id,
                    artifact_id=application.source_artifact_id,
                    related_ids=[
                        application.application_id,
                        application.resume_profile_id,
                        application.career_profile_id,
                        application.jd_analysis_id,
                        application.job_fit_report_id,
                        *application.resume_version_ids,
                    ],
                    priority_terms=[application.company, application.position, application.location],
                )
            )
    if request.allows(RetrievalSourceType.RESUME_PROFILE):
        for resume in store.list_resume_profiles(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.RESUME_PROFILE,
                    source_id=resume.resume_profile_id,
                    title=_profile_title(resume.basic_info, resume.resume_profile_id),
                    summary=_json_summary(resume.diagnosis) or resume.self_evaluation,
                    body=_join_values(resume.skills, resume.project_experience, resume.work_experience),
                    tags=_json_list_to_strings(resume.skills),
                    updated_at=resume.updated_at,
                    evidence_refs=resume.evidence_refs,
                    source_session_id=resume.source_session_id,
                    artifact_id=resume.diagnosis_artifact_id or resume.raw_text_artifact_id or resume.source_artifact_id,
                    related_ids=[resume.resume_profile_id, resume.raw_text_artifact_id, resume.diagnosis_artifact_id],
                )
            )
    if request.allows(RetrievalSourceType.CAREER_PROFILE):
        for career in store.list_career_profiles(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.CAREER_PROFILE,
                    source_id=career.career_profile_id,
                    title=career.career_goal or career.career_profile_id,
                    summary=_join_lists(career.strengths, career.weaknesses, career.resume_issues),
                    body=_join_lists(
                        career.target_roles,
                        career.preferred_industries,
                        career.preferred_cities,
                        career.skills,
                        career.interview_weaknesses,
                        [career.education_summary, career.experience_summary],
                    ),
                    tags=[*career.target_roles, *career.skills, *career.preferred_cities],
                    updated_at=career.updated_at,
                    evidence_refs=career.evidence_refs,
                    source_session_id=career.source_session_id,
                    artifact_id=career.source_artifact_id,
                    related_ids=[career.career_profile_id, *career.evidence_refs],
                    priority_terms=career.target_roles,
                )
            )
    if request.allows(RetrievalSourceType.JD_ANALYSIS):
        for jd in store.list_jd_analyses(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.JD_ANALYSIS,
                    source_id=jd.jd_analysis_id,
                    title=_join_non_empty(jd.company, jd.position) or jd.jd_analysis_id,
                    summary=_join_lists(jd.required_skills, jd.preferred_skills),
                    body=_join_lists(jd.responsibilities, jd.keywords, jd.risk_signals, jd.interview_focus),
                    tags=[jd.company, jd.position, *jd.required_skills, *jd.keywords],
                    updated_at=jd.updated_at,
                    evidence_refs=jd.evidence_refs,
                    source_session_id=jd.source_session_id,
                    artifact_id=jd.source_artifact_id,
                    related_ids=[jd.jd_analysis_id, *jd.evidence_refs],
                    priority_terms=[jd.company, jd.position, *jd.required_skills],
                )
            )
    if request.allows(RetrievalSourceType.JOB_FIT_REPORT):
        for fit in store.list_job_fit_reports(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.JOB_FIT_REPORT,
                    source_id=fit.job_fit_report_id,
                    title=f"匹配报告 {fit.job_fit_report_id}",
                    summary=f"整体匹配度 {fit.overall_score}，建议 {fit.recommendation}",
                    body=_join_values(
                        fit.score_breakdown,
                        fit.matched_evidence,
                        fit.gaps,
                        fit.resume_optimization_direction,
                        fit.interview_preparation_focus,
                    ),
                    tags=[fit.recommendation, *fit.score_breakdown.keys()],
                    updated_at=fit.updated_at,
                    evidence_refs=fit.evidence_refs,
                    source_session_id=fit.source_session_id,
                    artifact_id=fit.report_artifact_id or fit.source_artifact_id,
                    related_ids=[
                        fit.job_fit_report_id,
                        fit.jd_analysis_id,
                        fit.resume_profile_id,
                        fit.career_profile_id,
                        *fit.evidence_refs,
                    ],
                )
            )
    if request.allows(RetrievalSourceType.RESUME_VERSION):
        for version in store.list_resume_versions(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.RESUME_VERSION,
                    source_id=version.resume_version_id,
                    title=version.title,
                    summary=_join_lists(version.change_summary, version.keyword_strategy),
                    body=_join_lists(version.risk_notes, [version.format]),
                    tags=[version.format, *version.keyword_strategy],
                    updated_at=version.updated_at,
                    evidence_refs=version.evidence_refs,
                    source_session_id=version.source_session_id,
                    artifact_id=version.artifact_id,
                    related_ids=[
                        version.resume_version_id,
                        version.base_resume_profile_id,
                        version.target_jd_analysis_id,
                        version.artifact_id,
                        *version.evidence_refs,
                    ],
                )
            )
    return hits


def build_note_hits(store: NoteStore, request: RetrievalQuery) -> list[RetrievalHit]:
    """Build hits from user notes and collections."""

    hits: list[RetrievalHit] = []
    if request.allows(RetrievalSourceType.NOTE):
        notes = store.list_notes(
            include_archived=request.include_archived,
            related_application_id=request.related_application_id,
        )
        for note in notes:
            source_ref_ids = [item.source_id for item in note.source_refs if item.source_id is not None]
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.NOTE,
                    source_id=note.note_id,
                    title=note.title,
                    summary=note.summary,
                    body=note.body_markdown,
                    tags=note.tags,
                    updated_at=note.updated_at,
                    evidence_refs=note.evidence_refs,
                    source_session_id=note.source_session_id,
                    artifact_id=note.source_artifact_id,
                    related_ids=[note.note_id, note.related_application_id, note.collection_id, *source_ref_ids],
                )
            )
    if request.allows(RetrievalSourceType.NOTE_COLLECTION):
        for collection in store.list_collections(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.NOTE_COLLECTION,
                    source_id=collection.collection_id,
                    title=collection.name,
                    summary=collection.description,
                    body=_join_lists(collection.tags, [_enum_value(collection.kind)]),
                    tags=collection.tags,
                    updated_at=collection.updated_at,
                    evidence_refs=[collection.collection_id],
                    source_session_id=collection.source_session_id,
                    artifact_id=None,
                    related_ids=[collection.collection_id],
                )
            )
    return hits


def build_knowledge_hits(store: KnowledgeStore, request: RetrievalQuery) -> list[RetrievalHit]:
    """Build hits from external knowledge records."""

    hits: list[RetrievalHit] = []
    if request.allows(RetrievalSourceType.EXTERNAL_RESOURCE):
        resources = store.list_external_resources(
            include_archived=request.include_archived,
            related_application_id=request.related_application_id,
        )
        for resource in resources:
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.EXTERNAL_RESOURCE,
                    source_id=resource.resource_id,
                    title=resource.title,
                    summary=resource.summary,
                    body=_join_lists(resource.key_points, resource.target_roles, [resource.provider, resource.url or ""]),
                    tags=[resource.company, resource.position, *resource.skill_tags, *resource.target_roles],
                    updated_at=resource.updated_at,
                    evidence_refs=resource.evidence_refs,
                    source_session_id=resource.source_session_id,
                    artifact_id=resource.raw_artifact_id or resource.source_artifact_id,
                    related_ids=[
                        resource.resource_id,
                        *resource.related_application_ids,
                        *resource.related_note_ids,
                        resource.raw_artifact_id,
                    ],
                    priority_terms=[resource.company, resource.position, *resource.skill_tags],
                )
            )
    if request.allows(RetrievalSourceType.EXPERIENCE_POST):
        for experience in store.list_experience_posts(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.EXPERIENCE_POST,
                    source_id=experience.experience_id,
                    title=_join_non_empty(experience.company, experience.position, "面经") or experience.experience_id,
                    summary=experience.summary,
                    body=_join_values(
                        experience.interview_rounds,
                        experience.interview_process,
                        experience.questions,
                        experience.outcome,
                    ),
                    tags=[
                        experience.company,
                        experience.position,
                        experience.seniority,
                        _enum_value(experience.difficulty),
                        *experience.tags,
                    ],
                    updated_at=experience.updated_at,
                    evidence_refs=experience.evidence_refs,
                    source_session_id=experience.source_session_id,
                    artifact_id=experience.source_artifact_id,
                    related_ids=[
                        experience.experience_id,
                        experience.source_resource_id,
                        *experience.related_application_ids,
                        *experience.related_note_ids,
                    ],
                    priority_terms=[experience.company, experience.position, *experience.tags],
                )
            )
    if request.allows(RetrievalSourceType.INTERVIEW_QUESTION):
        for question in store.list_interview_questions(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.INTERVIEW_QUESTION,
                    source_id=question.question_id,
                    title=question.question_text,
                    summary=question.answer_outline,
                    body=_join_lists(question.evaluation_points, question.common_pitfalls),
                    tags=[question.company, question.position, _enum_value(question.question_type), *question.skill_tags],
                    updated_at=question.updated_at,
                    evidence_refs=question.evidence_refs,
                    source_session_id=question.source_session_id,
                    artifact_id=question.source_artifact_id,
                    related_ids=[
                        question.question_id,
                        question.source_resource_id,
                        question.source_experience_id,
                        *question.related_application_ids,
                        *question.related_note_ids,
                    ],
                    priority_terms=[question.company, question.position, *question.skill_tags],
                )
            )
    if request.allows(RetrievalSourceType.COMPANY_PROFILE):
        for company in store.list_company_profiles(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.COMPANY_PROFILE,
                    source_id=company.company_id,
                    title=company.company_name,
                    summary=company.summary,
                    body=_join_lists(
                        company.aliases,
                        company.industries,
                        company.target_roles,
                        company.hiring_signals,
                        company.common_questions,
                        [company.interview_style],
                    ),
                    tags=[company.company_name, *company.aliases, *company.target_roles, *company.industries],
                    updated_at=company.updated_at,
                    evidence_refs=company.evidence_refs,
                    source_session_id=company.source_session_id,
                    artifact_id=company.source_artifact_id,
                    related_ids=[company.company_id, *company.resource_ids, *company.question_ids],
                    priority_terms=[company.company_name, *company.aliases, *company.target_roles],
                )
            )
    if request.allows(RetrievalSourceType.SKILL_REQUIREMENT):
        for skill in store.list_skill_requirements(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.SKILL_REQUIREMENT,
                    source_id=skill.skill_requirement_id,
                    title=skill.skill_name,
                    summary=skill.description,
                    body=_join_lists(skill.assessment_points, skill.role_tags),
                    tags=[skill.skill_name, _enum_value(skill.category), _enum_value(skill.level), *skill.role_tags],
                    updated_at=skill.updated_at,
                    evidence_refs=skill.evidence_refs,
                    source_session_id=skill.source_session_id,
                    artifact_id=skill.source_artifact_id,
                    related_ids=[
                        skill.skill_requirement_id,
                        *skill.company_ids,
                        *skill.resource_ids,
                        *skill.question_ids,
                    ],
                    priority_terms=[skill.skill_name, *skill.role_tags],
                )
            )
    return hits


def build_learning_hits(store: LearningStore, request: RetrievalQuery) -> list[RetrievalHit]:
    """Build hits from learning plans and progress records."""

    hits: list[RetrievalHit] = []
    if request.allows(RetrievalSourceType.LEARNING_PLAN):
        plans = store.list_learning_plans(
            include_archived=request.include_archived,
            target_application_id=request.related_application_id,
        )
        for plan in plans:
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.LEARNING_PLAN,
                    source_id=plan.learning_plan_id,
                    title=plan.title,
                    summary=plan.description or plan.progress_summary,
                    body=_join_lists(plan.goals, plan.focus_skill_tags, [plan.target_role, plan.target_company]),
                    tags=[
                        plan.target_role,
                        plan.target_company,
                        _enum_value(plan.plan_type),
                        _enum_value(plan.priority),
                        *plan.focus_skill_tags,
                    ],
                    updated_at=plan.updated_at,
                    evidence_refs=plan.evidence_refs,
                    source_session_id=plan.source_session_id,
                    artifact_id=plan.source_artifact_id,
                    related_ids=[
                        plan.learning_plan_id,
                        plan.target_application_id,
                        *plan.task_ids,
                        *plan.weakness_ids,
                        *plan.review_schedule_ids,
                    ],
                    priority_terms=[plan.target_role, plan.target_company, *plan.focus_skill_tags],
                )
            )
    if request.allows(RetrievalSourceType.LEARNING_TASK):
        for task in store.list_learning_tasks(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.LEARNING_TASK,
                    source_id=task.learning_task_id,
                    title=task.title,
                    summary=task.description or task.progress_notes,
                    body=_join_lists(
                        task.skill_tags,
                        task.success_criteria,
                        task.resource_refs,
                        task.question_refs,
                        task.note_refs,
                    ),
                    tags=[_enum_value(task.task_type), _enum_value(task.priority), _enum_value(task.state), *task.skill_tags],
                    updated_at=task.updated_at,
                    evidence_refs=task.evidence_refs,
                    source_session_id=task.source_session_id,
                    artifact_id=task.output_artifact_id or task.source_artifact_id,
                    related_ids=[
                        task.learning_task_id,
                        task.learning_plan_id,
                        task.output_artifact_id,
                        *task.resource_refs,
                        *task.question_refs,
                        *task.note_refs,
                        *task.evidence_refs,
                    ],
                    priority_terms=task.skill_tags,
                    state_hint=_enum_value(task.state),
                )
            )
    if request.allows(RetrievalSourceType.PROGRESS_CHECKIN):
        for checkin in store.list_progress_checkins(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.PROGRESS_CHECKIN,
                    source_id=checkin.checkin_id,
                    title=f"学习打卡 {checkin.checkin_id}",
                    summary=checkin.summary,
                    body=_join_lists(checkin.blockers, checkin.note_refs, [checkin.next_action, _enum_value(checkin.confidence)]),
                    tags=[_enum_value(checkin.progress_state), _enum_value(checkin.confidence)],
                    updated_at=checkin.updated_at,
                    evidence_refs=checkin.evidence_refs,
                    source_session_id=checkin.source_session_id,
                    artifact_id=checkin.source_artifact_id,
                    related_ids=[
                        checkin.checkin_id,
                        checkin.learning_plan_id,
                        checkin.learning_task_id,
                        *checkin.note_refs,
                        *checkin.evidence_refs,
                    ],
                    state_hint=_enum_value(checkin.progress_state),
                )
            )
    if request.allows(RetrievalSourceType.WEAKNESS_TRACKER):
        for weakness in store.list_weakness_trackers(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.WEAKNESS_TRACKER,
                    source_id=weakness.weakness_id,
                    title=weakness.title,
                    summary=weakness.description or weakness.resolution_summary,
                    body=_join_lists(
                        weakness.skill_tags,
                        weakness.source_report_ids,
                        weakness.related_task_ids,
                        weakness.related_note_ids,
                    ),
                    tags=[
                        _enum_value(weakness.weakness_type),
                        _enum_value(weakness.severity),
                        _enum_value(weakness.state),
                        *weakness.skill_tags,
                    ],
                    updated_at=weakness.updated_at,
                    evidence_refs=weakness.evidence_refs,
                    source_session_id=weakness.source_session_id,
                    artifact_id=weakness.source_artifact_id,
                    related_ids=[
                        weakness.weakness_id,
                        *weakness.target_application_ids,
                        *weakness.source_report_ids,
                        *weakness.related_task_ids,
                        *weakness.related_note_ids,
                    ],
                    priority_terms=weakness.skill_tags,
                    state_hint=_enum_value(weakness.state),
                )
            )
    if request.allows(RetrievalSourceType.REVIEW_SCHEDULE):
        for review in store.list_review_schedules(include_archived=request.include_archived):
            hits.extend(
                _record_hit(
                    request,
                    source_type=RetrievalSourceType.REVIEW_SCHEDULE,
                    source_id=review.review_schedule_id,
                    title=review.title,
                    summary=review.summary,
                    body=_join_lists(review.resource_refs, review.question_refs, review.note_refs),
                    tags=[_enum_value(review.review_type), _enum_value(review.state)],
                    updated_at=review.updated_at,
                    evidence_refs=review.evidence_refs,
                    source_session_id=review.source_session_id,
                    artifact_id=review.source_artifact_id,
                    related_ids=[
                        review.review_schedule_id,
                        review.learning_plan_id,
                        review.learning_task_id,
                        review.weakness_id,
                        *review.resource_refs,
                        *review.question_refs,
                        *review.note_refs,
                    ],
                    state_hint=_enum_value(review.state),
                )
            )
    return hits


def build_session_artifact_hits(repository: SessionRepository, request: RetrievalQuery) -> list[RetrievalHit]:
    """Build hits from current-session artifacts only."""

    if not request.allows(RetrievalSourceType.SESSION_ARTIFACT):
        return []
    try:
        artifacts = repository.list_session_artifacts(request.session_id)
    except SessionNotFoundError:
        return []
    hits: list[RetrievalHit] = []
    for artifact in artifacts:
        if artifact.status != "ready":
            continue
        body = _artifact_body(repository, artifact)
        hits.extend(
            _record_hit(
                request,
                source_type=RetrievalSourceType.SESSION_ARTIFACT,
                source_id=artifact.artifact_id,
                title=artifact.title,
                summary=artifact.description or artifact.kind,
                body=body,
                tags=[artifact.kind, artifact.media_type, artifact.source_type or ""],
                updated_at=artifact.updated_at,
                evidence_refs=[artifact.artifact_id],
                source_session_id=artifact.session_id,
                artifact_id=artifact.artifact_id,
                related_ids=[artifact.artifact_id],
                priority_terms=[artifact.title],
            )
        )
    return hits


def _record_hit(
    request: RetrievalQuery,
    *,
    source_type: RetrievalSourceType,
    source_id: str,
    title: str,
    summary: str,
    body: str,
    tags: Sequence[Any],
    updated_at: datetime,
    evidence_refs: Sequence[Any],
    source_session_id: str | None,
    artifact_id: str | None,
    related_ids: Sequence[str | None] = (),
    priority_terms: Sequence[Any] = (),
    state_hint: str = "",
) -> list[RetrievalHit]:
    related = _clean_strings([*related_ids, *evidence_refs])
    if not _matches_related_application(request.related_application_id, related, evidence_refs):
        return []
    all_text = _join_lists([title, summary, body], tags, evidence_refs, related)
    score, reason = _score_candidate(
        request,
        searchable_text=all_text,
        tags=tags,
        evidence_refs=evidence_refs,
        related_ids=related,
        priority_terms=priority_terms,
        state_hint=state_hint,
    )
    if score <= 0:
        return []
    snippet = _snippet(body or summary or title, request.query, max_chars=request.max_snippet_chars)
    return [
        RetrievalHit(
            source=RetrievalSourceRef(
                source_type=source_type,
                source_id=source_id,
                source_session_id=source_session_id,
                artifact_id=artifact_id,
            ),
            title=title or source_id,
            summary=_snippet(summary, request.query, max_chars=min(request.max_snippet_chars, 500)),
            snippet=snippet,
            tags=_clean_strings(tags),
            score=score,
            match_reason=reason,
            updated_at=updated_at,
            evidence_refs=_clean_strings(evidence_refs),
        )
    ]


def _score_candidate(
    request: RetrievalQuery,
    *,
    searchable_text: str,
    tags: Sequence[Any],
    evidence_refs: Sequence[Any],
    related_ids: Sequence[str],
    priority_terms: Sequence[Any],
    state_hint: str,
) -> tuple[float, str]:
    query = request.query.casefold()
    score = 0.0
    reasons: list[str] = []
    if not query and request.related_application_id is None:
        return 0.1, "默认候选"
    if request.related_application_id is not None and request.related_application_id in set(related_ids):
        score += 0.45
        reasons.append("关联求职项目")
    search = searchable_text.casefold()
    query_terms = _query_terms(query)
    for term in query_terms:
        if term and term in search:
            score += 0.08
            reasons.append(f"命中查询词 {term}")
    for tag in _clean_strings(tags):
        if tag.casefold() and tag.casefold() in query:
            score += 0.16
            reasons.append(f"命中标签 {tag}")
    for term in _clean_strings(priority_terms):
        if term.casefold() and term.casefold() in query:
            score += 0.22
            reasons.append(f"命中关键字段 {term}")
    for ref in _clean_strings([*evidence_refs, *related_ids]):
        if ref.casefold() and ref.casefold() in query:
            score += 0.2
            reasons.append(f"命中引用 {ref}")
    if state_hint in {"open", "todo", "doing", "blocked", "scheduled"}:
        score += 0.04
    if score <= 0:
        return 0.0, ""
    reason = "；".join(_dedupe(reasons)[:4]) or "规则召回"
    return min(score, 1.0), reason


def _matches_related_application(
    related_application_id: str | None,
    related_ids: Sequence[str],
    evidence_refs: Sequence[str],
) -> bool:
    if related_application_id is None:
        return True
    refs = set(_clean_strings([*related_ids, *evidence_refs]))
    return related_application_id in refs


def _artifact_body(repository: SessionRepository, artifact: SessionArtifact) -> str:
    if artifact.text_relpath is None:
        return artifact.description or ""
    try:
        return repository.read_session_artifact_text(artifact.session_id, artifact.artifact_id)
    except (SessionNotFoundError, StorageError):
        return artifact.description or ""


def _snippet(value: str, query: str, *, max_chars: int) -> str:
    text = " ".join(value.split())
    if len(text) <= max_chars:
        return text
    lowered = text.casefold()
    terms = _query_terms(query.casefold())
    index = -1
    for term in terms:
        index = lowered.find(term)
        if index >= 0:
            break
    if index < 0:
        return text[:max_chars].rstrip()
    start = max(index - max_chars // 3, 0)
    end = min(start + max_chars, len(text))
    return text[start:end].strip()


def _query_terms(query: str) -> list[str]:
    terms = [term.strip().casefold() for term in _QUERY_TERM_RE.findall(query) if term.strip()]
    return _dedupe([term for term in terms if len(term) >= 2])


def _join_non_empty(*values: str) -> str:
    return " · ".join(_clean_strings(values))


def _join_lists(*values: Sequence[Any]) -> str:
    return "；".join(_clean_strings(_flatten(values)))


def _join_values(*values: Any) -> str:
    return "；".join(_clean_strings(_flatten(values)))


def _flatten(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            for key, item in value.items():
                output.append(f"{key}: {item}")
            continue
        if isinstance(value, list | tuple | set):
            output.extend(_flatten(value))
            continue
        output.append(_stringify(value))
    return output


def _clean_strings(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _stringify(value).strip()
        if not item:
            continue
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _dedupe(values: Sequence[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        output.append(value)
        seen.add(value)
    return output


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, dict):
        return " ".join(f"{key}: {item}" for key, item in value.items())
    return str(value)


def _enum_value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value) if value is not None else ""


def _json_summary(value: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, item in value.items():
        parts.append(f"{key}: {_join_values(item)}")
    return "；".join(parts)


def _json_list_to_strings(values: Sequence[Any]) -> list[str]:
    return _clean_strings(_flatten(values))


def _profile_title(basic_info: dict[str, Any], fallback: str) -> str:
    name = basic_info.get("name")
    if isinstance(name, str) and name.strip():
        return f"{name.strip()}的简历画像"
    return fallback
