"""External career knowledge HTTP endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_knowledge_store
from app.api.presenters import (
    company_profile_view,
    experience_post_view,
    external_resource_view,
    interview_question_view,
    skill_requirement_view,
)
from app.api.responses import ok
from app.core.errors import ValidationError
from app.core.time import app_now
from app.knowledge.models import (
    CompanyProfile,
    ExperiencePost,
    ExternalResource,
    InterviewQuestion,
    KnowledgeRecordStatus,
    SkillRequirement,
)
from app.knowledge.store import KnowledgeStore
from app.schemas.common import StandardResponse
from app.schemas.knowledge import (
    CompanyProfileCreateRequest,
    CompanyProfileUpdateRequest,
    CompanyProfileView,
    ExperiencePostCreateRequest,
    ExperiencePostUpdateRequest,
    ExperiencePostView,
    ExternalResourceCreateRequest,
    ExternalResourceUpdateRequest,
    ExternalResourceView,
    InterviewQuestionCreateRequest,
    InterviewQuestionUpdateRequest,
    InterviewQuestionView,
    SkillRequirementCreateRequest,
    SkillRequirementUpdateRequest,
    SkillRequirementView,
)

__all__ = ["admin_router", "router"]

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
admin_router = APIRouter(prefix="/api/knowledge-admin", tags=["knowledge-admin"])
_RecordT = TypeVar(
    "_RecordT",
    ExternalResource,
    ExperiencePost,
    InterviewQuestion,
    CompanyProfile,
    SkillRequirement,
)


@router.get("/resources", response_model=StandardResponse[list[ExternalResourceView]])
def list_external_resources(
    include_archived: bool = Query(default=False),
    related_application_id: str | None = Query(default=None),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[list[ExternalResourceView]]:
    return ok([
        external_resource_view(item)
        for item in store.list_external_resources(
            include_archived=include_archived,
            related_application_id=related_application_id,
        )
    ])


@admin_router.post("/resources", response_model=StandardResponse[ExternalResourceView])
def create_external_resource(
    request: ExternalResourceCreateRequest,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[ExternalResourceView]:
    record = ExternalResource(
        resource_id=request.resource_id or _new_resource_id(),
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id=request.source_session_id,
        source_artifact_id=request.source_artifact_id,
        evidence_refs=request.evidence_refs,
        created_at=_placeholder_time(),
        updated_at=_placeholder_time(),
        title=request.title,
        resource_type=request.resource_type,
        url=request.url,
        provider=request.provider,
        company=request.company,
        position=request.position,
        target_roles=request.target_roles,
        skill_tags=request.skill_tags,
        summary=request.summary,
        key_points=request.key_points,
        raw_artifact_id=request.raw_artifact_id,
        related_application_ids=request.related_application_ids,
        related_note_ids=request.related_note_ids,
    )
    return ok(external_resource_view(store.save_external_resource(record)))


@router.get("/resources/{resource_id}", response_model=StandardResponse[ExternalResourceView])
def get_external_resource(
    resource_id: str,
    include_archived: bool = Query(default=False),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[ExternalResourceView]:
    record = _require_visible(
        store.get_external_resource(resource_id),
        include_archived=include_archived,
        record_type="ExternalResource",
        record_id=resource_id,
    )
    return ok(external_resource_view(record))


@admin_router.patch("/resources/{resource_id}", response_model=StandardResponse[ExternalResourceView])
def update_external_resource(
    resource_id: str,
    request: ExternalResourceUpdateRequest,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[ExternalResourceView]:
    _require_visible(
        store.get_external_resource(resource_id),
        include_archived=False,
        record_type="ExternalResource",
        record_id=resource_id,
    )
    updates = _updates(request)
    return ok(external_resource_view(store.update_external_resource(resource_id, updates=updates)))


@admin_router.post("/resources/{resource_id}/archive", response_model=StandardResponse[ExternalResourceView])
def archive_external_resource(
    resource_id: str,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[ExternalResourceView]:
    record = store.archive_external_resource(resource_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"ExternalResource not found: {resource_id}")
    return ok(external_resource_view(record))


@router.get("/experiences", response_model=StandardResponse[list[ExperiencePostView]])
def list_experience_posts(
    include_archived: bool = Query(default=False),
    source_resource_id: str | None = Query(default=None),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[list[ExperiencePostView]]:
    return ok([
        experience_post_view(item)
        for item in store.list_experience_posts(
            include_archived=include_archived,
            source_resource_id=source_resource_id,
        )
    ])


@admin_router.post("/experiences", response_model=StandardResponse[ExperiencePostView])
def create_experience_post(
    request: ExperiencePostCreateRequest,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[ExperiencePostView]:
    record = ExperiencePost(
        experience_id=request.experience_id or _new_experience_id(),
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id=request.source_session_id,
        source_artifact_id=request.source_artifact_id,
        evidence_refs=request.evidence_refs,
        created_at=_placeholder_time(),
        updated_at=_placeholder_time(),
        source_resource_id=request.source_resource_id,
        company=request.company,
        position=request.position,
        seniority=request.seniority,
        interview_rounds=request.interview_rounds,
        interview_process=request.interview_process,
        questions=request.questions,
        outcome=request.outcome,
        difficulty=request.difficulty,
        summary=request.summary,
        tags=request.tags,
        related_application_ids=request.related_application_ids,
        related_note_ids=request.related_note_ids,
    )
    return ok(experience_post_view(store.save_experience_post(record)))


@router.get("/experiences/{experience_id}", response_model=StandardResponse[ExperiencePostView])
def get_experience_post(
    experience_id: str,
    include_archived: bool = Query(default=False),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[ExperiencePostView]:
    record = _require_visible(
        store.get_experience_post(experience_id),
        include_archived=include_archived,
        record_type="ExperiencePost",
        record_id=experience_id,
    )
    return ok(experience_post_view(record))


@admin_router.patch("/experiences/{experience_id}", response_model=StandardResponse[ExperiencePostView])
def update_experience_post(
    experience_id: str,
    request: ExperiencePostUpdateRequest,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[ExperiencePostView]:
    _require_visible(
        store.get_experience_post(experience_id),
        include_archived=False,
        record_type="ExperiencePost",
        record_id=experience_id,
    )
    updates = _updates(request)
    return ok(experience_post_view(store.update_experience_post(experience_id, updates=updates)))


@admin_router.post("/experiences/{experience_id}/archive", response_model=StandardResponse[ExperiencePostView])
def archive_experience_post(
    experience_id: str,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[ExperiencePostView]:
    record = store.archive_experience_post(experience_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"ExperiencePost not found: {experience_id}")
    return ok(experience_post_view(record))


@router.get("/questions", response_model=StandardResponse[list[InterviewQuestionView]])
def list_interview_questions(
    include_archived: bool = Query(default=False),
    source_resource_id: str | None = Query(default=None),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[list[InterviewQuestionView]]:
    return ok([
        interview_question_view(item)
        for item in store.list_interview_questions(
            include_archived=include_archived,
            source_resource_id=source_resource_id,
        )
    ])


@admin_router.post("/questions", response_model=StandardResponse[InterviewQuestionView])
def create_interview_question(
    request: InterviewQuestionCreateRequest,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[InterviewQuestionView]:
    record = InterviewQuestion(
        question_id=request.question_id or _new_question_id(),
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id=request.source_session_id,
        source_artifact_id=request.source_artifact_id,
        evidence_refs=request.evidence_refs,
        created_at=_placeholder_time(),
        updated_at=_placeholder_time(),
        question_text=request.question_text,
        question_type=request.question_type,
        difficulty=request.difficulty,
        skill_tags=request.skill_tags,
        company=request.company,
        position=request.position,
        source_resource_id=request.source_resource_id,
        source_experience_id=request.source_experience_id,
        answer_outline=request.answer_outline,
        evaluation_points=request.evaluation_points,
        common_pitfalls=request.common_pitfalls,
        related_application_ids=request.related_application_ids,
        related_note_ids=request.related_note_ids,
    )
    return ok(interview_question_view(store.save_interview_question(record)))


@router.get("/questions/{question_id}", response_model=StandardResponse[InterviewQuestionView])
def get_interview_question(
    question_id: str,
    include_archived: bool = Query(default=False),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[InterviewQuestionView]:
    record = _require_visible(
        store.get_interview_question(question_id),
        include_archived=include_archived,
        record_type="InterviewQuestion",
        record_id=question_id,
    )
    return ok(interview_question_view(record))


@admin_router.patch("/questions/{question_id}", response_model=StandardResponse[InterviewQuestionView])
def update_interview_question(
    question_id: str,
    request: InterviewQuestionUpdateRequest,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[InterviewQuestionView]:
    _require_visible(
        store.get_interview_question(question_id),
        include_archived=False,
        record_type="InterviewQuestion",
        record_id=question_id,
    )
    updates = _updates(request)
    return ok(interview_question_view(store.update_interview_question(question_id, updates=updates)))


@admin_router.post("/questions/{question_id}/archive", response_model=StandardResponse[InterviewQuestionView])
def archive_interview_question(
    question_id: str,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[InterviewQuestionView]:
    record = store.archive_interview_question(question_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"InterviewQuestion not found: {question_id}",
        )
    return ok(interview_question_view(record))


@router.get("/companies", response_model=StandardResponse[list[CompanyProfileView]])
def list_company_profiles(
    include_archived: bool = Query(default=False),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[list[CompanyProfileView]]:
    return ok([
        company_profile_view(item)
        for item in store.list_company_profiles(include_archived=include_archived)
    ])


@admin_router.post("/companies", response_model=StandardResponse[CompanyProfileView])
def create_company_profile(
    request: CompanyProfileCreateRequest,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[CompanyProfileView]:
    record = CompanyProfile(
        company_id=request.company_id or _new_company_id(),
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id=request.source_session_id,
        source_artifact_id=request.source_artifact_id,
        evidence_refs=request.evidence_refs,
        created_at=_placeholder_time(),
        updated_at=_placeholder_time(),
        company_name=request.company_name,
        aliases=request.aliases,
        industries=request.industries,
        target_roles=request.target_roles,
        hiring_signals=request.hiring_signals,
        interview_style=request.interview_style,
        common_questions=request.common_questions,
        resource_ids=request.resource_ids,
        question_ids=request.question_ids,
        summary=request.summary,
    )
    return ok(company_profile_view(store.save_company_profile(record)))


@router.get("/companies/{company_id}", response_model=StandardResponse[CompanyProfileView])
def get_company_profile(
    company_id: str,
    include_archived: bool = Query(default=False),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[CompanyProfileView]:
    record = _require_visible(
        store.get_company_profile(company_id),
        include_archived=include_archived,
        record_type="CompanyProfile",
        record_id=company_id,
    )
    return ok(company_profile_view(record))


@admin_router.patch("/companies/{company_id}", response_model=StandardResponse[CompanyProfileView])
def update_company_profile(
    company_id: str,
    request: CompanyProfileUpdateRequest,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[CompanyProfileView]:
    _require_visible(
        store.get_company_profile(company_id),
        include_archived=False,
        record_type="CompanyProfile",
        record_id=company_id,
    )
    updates = _updates(request)
    return ok(company_profile_view(store.update_company_profile(company_id, updates=updates)))


@admin_router.post("/companies/{company_id}/archive", response_model=StandardResponse[CompanyProfileView])
def archive_company_profile(
    company_id: str,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[CompanyProfileView]:
    record = store.archive_company_profile(company_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"CompanyProfile not found: {company_id}")
    return ok(company_profile_view(record))


@router.get("/skill-requirements", response_model=StandardResponse[list[SkillRequirementView]])
def list_skill_requirements(
    include_archived: bool = Query(default=False),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[list[SkillRequirementView]]:
    return ok([
        skill_requirement_view(item)
        for item in store.list_skill_requirements(include_archived=include_archived)
    ])


@admin_router.post("/skill-requirements", response_model=StandardResponse[SkillRequirementView])
def create_skill_requirement(
    request: SkillRequirementCreateRequest,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[SkillRequirementView]:
    record = SkillRequirement(
        skill_requirement_id=request.skill_requirement_id or _new_skill_requirement_id(),
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id=request.source_session_id,
        source_artifact_id=request.source_artifact_id,
        evidence_refs=request.evidence_refs,
        created_at=_placeholder_time(),
        updated_at=_placeholder_time(),
        skill_name=request.skill_name,
        category=request.category,
        level=request.level,
        description=request.description,
        assessment_points=request.assessment_points,
        role_tags=request.role_tags,
        company_ids=request.company_ids,
        resource_ids=request.resource_ids,
        question_ids=request.question_ids,
    )
    return ok(skill_requirement_view(store.save_skill_requirement(record)))


@router.get("/skill-requirements/{skill_requirement_id}", response_model=StandardResponse[SkillRequirementView])
def get_skill_requirement(
    skill_requirement_id: str,
    include_archived: bool = Query(default=False),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[SkillRequirementView]:
    record = _require_visible(
        store.get_skill_requirement(skill_requirement_id),
        include_archived=include_archived,
        record_type="SkillRequirement",
        record_id=skill_requirement_id,
    )
    return ok(skill_requirement_view(record))


@admin_router.patch("/skill-requirements/{skill_requirement_id}", response_model=StandardResponse[SkillRequirementView])
def update_skill_requirement(
    skill_requirement_id: str,
    request: SkillRequirementUpdateRequest,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[SkillRequirementView]:
    _require_visible(
        store.get_skill_requirement(skill_requirement_id),
        include_archived=False,
        record_type="SkillRequirement",
        record_id=skill_requirement_id,
    )
    updates = _updates(request)
    return ok(skill_requirement_view(store.update_skill_requirement(skill_requirement_id, updates=updates)))


@admin_router.post(
    "/skill-requirements/{skill_requirement_id}/archive",
    response_model=StandardResponse[SkillRequirementView],
)
def archive_skill_requirement(
    skill_requirement_id: str,
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> StandardResponse[SkillRequirementView]:
    record = store.archive_skill_requirement(skill_requirement_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SkillRequirement not found: {skill_requirement_id}",
        )
    return ok(skill_requirement_view(record))


def _require_visible(
    record: _RecordT | None,
    *,
    include_archived: bool,
    record_type: str,
    record_id: str,
) -> _RecordT:
    if record is None or (record.status == KnowledgeRecordStatus.ARCHIVED and not include_archived):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{record_type} not found: {record_id}",
        )
    return record


def _updates(request: Any) -> dict[str, object]:
    if not hasattr(request, "model_dump"):
        raise ValidationError("Knowledge update payload is invalid.")
    updates = cast(dict[str, object], request.model_dump(exclude_unset=True))
    if not updates:
        raise ValidationError("Knowledge update must include at least one editable field.")
    return updates


def _new_resource_id() -> str:
    return f"resource_{uuid4().hex}"


def _new_experience_id() -> str:
    return f"experience_{uuid4().hex}"


def _new_question_id() -> str:
    return f"question_{uuid4().hex}"


def _new_company_id() -> str:
    return f"company_{uuid4().hex}"


def _new_skill_requirement_id() -> str:
    return f"skill_req_{uuid4().hex}"


def _placeholder_time() -> datetime:
    return app_now()
