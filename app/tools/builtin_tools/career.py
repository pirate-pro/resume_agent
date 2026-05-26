"""Built-in tools for career product records."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.career.models import (
    CareerApplication,
    CareerProfile,
    CareerRecordStatus,
    JDAnalysis,
    JobFitReport,
    ResumeProfile,
    ResumeVersion,
)
from app.career.store import CareerProductStore
from app.core.errors import StorageError, ToolExecutionError, ValidationError
from app.core.time import app_now, to_app_iso
from app.domain.models import RunContext, SessionArtifact, ToolDefinition, ToolExecutionResult
from app.domain.protocols import SessionRepository
from app.domain.reference_ids import is_reserved_reference_value
from app.tools.builtin_tools.common import validate_context
from app.tools.builtin_tools.session_artifact_helpers import require_session_artifact

__all__ = [
    "CareerApplicationCreateTool",
    "CareerApplicationGetTool",
    "CareerApplicationListTool",
    "CareerApplicationMergeTool",
    "CareerJobFitReportGetTool",
    "CareerJobFitReportListTool",
    "CareerJobFitReportSaveTool",
    "CareerJDAnalysisGetTool",
    "CareerJDAnalysisListTool",
    "CareerJDAnalysisSaveTool",
    "CareerProfileGetTool",
    "CareerProfileMergeTool",
    "CareerResumeProfileGetTool",
    "CareerResumeProfileListTool",
    "CareerResumeProfileSaveTool",
    "CareerResumeVersionCreateTool",
    "CareerResumeVersionGetTool",
    "CareerResumeVersionListTool",
]

_DEFAULT_CAREER_PROFILE_ID = "career_profile_default"
_PRODUCT_EVIDENCE_PREFIXES = (
    "resume_profile_",
    "career_profile_",
    "jd_",
    "fit_",
    "resume_version_",
    "application_",
)
_CAREER_PROFILE_ALLOWED_UPDATE_FIELDS = {
    "career_goal",
    "target_roles",
    "preferred_industries",
    "preferred_cities",
    "strengths",
    "weaknesses",
    "skills",
    "interests",
    "education_summary",
    "experience_summary",
    "resume_issues",
    "interview_weaknesses",
}
_CAREER_PROFILE_LIST_UPDATE_FIELDS = {
    "target_roles",
    "preferred_industries",
    "preferred_cities",
    "strengths",
    "weaknesses",
    "skills",
    "interests",
    "resume_issues",
    "interview_weaknesses",
}
_CAREER_PROFILE_TEXT_UPDATE_FIELDS = {
    "career_goal",
    "education_summary",
    "experience_summary",
}
_JOB_FIT_RECOMMENDATIONS = {"recommended", "cautious", "not_recommended"}
_JOB_FIT_RECOMMENDATION_ALIASES = {
    "recommend": "recommended",
    "recommended": "recommended",
    "推荐": "recommended",
    "建议投递": "recommended",
    "caution": "cautious",
    "cautious": "cautious",
    "谨慎": "cautious",
    "谨慎推荐": "cautious",
    "notrecommended": "not_recommended",
    "not_recommended": "not_recommended",
    "not recommended": "not_recommended",
    "不推荐": "not_recommended",
    "不建议": "not_recommended",
}
_CAREER_PROFILE_UPDATE_ALIASES = {
    "target_direction": "career_goal",
    "target_position": "target_roles",
    "target_role": "target_roles",
    "core_skills": "skills",
    "key_skills": "skills",
    "resume_optimization_priority": "resume_issues",
}
_CAREER_PROFILE_IGNORED_UPDATE_FIELDS = {
    "education",
    "job_market_fit",
    "key_project",
    "name",
    "other",
    "project",
    "project_experience",
    "projects",
    "resume_profile_id",
    "summary",
    "work_experience",
    "work_experience_years",
}
_CAREER_APPLICATION_ALLOWED_UPDATE_FIELDS = {
    "career_profile_id",
    "jd_analysis_id",
    "job_fit_report_id",
    "next_actions",
    "notes",
    "priority",
    "resume_profile_id",
    "resume_version_ids",
    "risks",
    "stage",
    "summary",
}
_CAREER_APPLICATION_UPDATE_ALIASES = {
    "action_items": "next_actions",
    "next_step": "next_actions",
    "next_steps": "next_actions",
    "todo": "next_actions",
}
_CAREER_APPLICATION_STAGES = {
    "draft",
    "analyzing",
    "ready_to_apply",
    "applied",
    "interviewing",
    "offer",
    "rejected",
    "paused",
}
_CAREER_APPLICATION_STAGE_ALIASES = {
    "ready": "ready_to_apply",
    "resume_ready": "ready_to_apply",
    "resume_generated": "ready_to_apply",
    "resume_version": "ready_to_apply",
    "tailoring": "ready_to_apply",
    "customizing": "ready_to_apply",
    "tailored": "ready_to_apply",
    "resume_tailoring": "ready_to_apply",
    "resume_customizing": "ready_to_apply",
    "tailored_resume": "ready_to_apply",
    "custom_resume": "ready_to_apply",
    "resume_version_ready": "ready_to_apply",
    "resume_version_created": "ready_to_apply",
    "resume_version_done": "ready_to_apply",
    "resume_version_complete": "ready_to_apply",
    "resume_customized": "ready_to_apply",
    "customized_resume": "ready_to_apply",
    "version_created": "ready_to_apply",
    "version_ready": "ready_to_apply",
    "final_resume_ready": "ready_to_apply",
    "apply_ready": "ready_to_apply",
    "analysis_complete": "draft",
    "analysis_done": "draft",
    "evaluation_complete": "draft",
    "fit_ready": "draft",
}
_CAREER_APPLICATION_IGNORED_UPDATE_FIELDS = {
    "application_id",
    "company",
    "created_at",
    "evidence_refs",
    "job_url",
    "location",
    "position",
    "source_artifact_id",
    "source_session_id",
    "status",
    "updated_at",
}
_EVIDENCE_REF_TYPE_ALIASES = {
    "artifact": "artifact",
    "artifact_id": "artifact",
    "source_artifact": "artifact",
    "source_artifact_id": "artifact",
    "report_artifact": "artifact",
    "report_artifact_id": "artifact",
    "application": "application",
    "application_id": "application",
    "career_application": "application",
    "career_application_id": "application",
    "career_profile": "career_profile",
    "career_profile_id": "career_profile",
    "fit": "fit",
    "fit_report": "fit",
    "job_fit_report": "fit",
    "job_fit_report_id": "fit",
    "jd": "jd",
    "jd_analysis": "jd",
    "jd_analysis_id": "jd",
    "resume_profile": "resume_profile",
    "resume_profile_id": "resume_profile",
    "resume_version": "resume_version",
    "resume_version_id": "resume_version",
    "session": "sess",
    "session_id": "sess",
}
_RESUME_SOURCE_TECH_TERMS: dict[str, tuple[str, ...]] = {
    "agent": ("agent", "智能体"),
    "celery": ("celery",),
    "docker": ("docker",),
    "elasticsearch": ("elasticsearch",),
    "faiss": ("faiss",),
    "fastapi": ("fastapi",),
    "java": ("java",),
    "kubernetes": ("kubernetes", "k8s"),
    "langchain": ("langchain",),
    "langgraph": ("langgraph",),
    "milvus": ("milvus",),
    "mysql": ("mysql",),
    "llm_api": ("llm api", "openai api", "大模型 api", "模型 api"),
    "postgresql": ("postgresql", "postgres"),
    "python": ("python",),
    "pytorch": ("pytorch",),
    "rag": ("rag", "检索增强"),
    "react": ("react",),
    "redis": ("redis",),
    "spring": ("spring", "spring boot", "springboot"),
    "tensorflow": ("tensorflow",),
    "vector_search": ("向量检索", "vector search", "embedding search", "语义检索"),
    "vue": ("vue",),
    "websocket": ("websocket", "web socket"),
}
_RESUME_SOURCE_TERM_DISPLAY_NAMES = {
    "agent": "Agent 工具调用",
    "celery": "Celery",
    "docker": "Docker",
    "elasticsearch": "Elasticsearch",
    "faiss": "FAISS",
    "fastapi": "FastAPI",
    "java": "Java",
    "kubernetes": "Kubernetes",
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "llm_api": "LLM API",
    "milvus": "Milvus",
    "mysql": "MySQL",
    "postgresql": "PostgreSQL",
    "python": "Python",
    "pytorch": "PyTorch",
    "rag": "RAG",
    "react": "React",
    "redis": "Redis",
    "spring": "Spring",
    "tensorflow": "TensorFlow",
    "vector_search": "向量检索",
    "vue": "Vue",
    "websocket": "WebSocket",
}


class CareerResumeProfileSaveTool:
    """Persist one structured resume profile."""

    def __init__(self, career_store: CareerProductStore, session_repository: SessionRepository) -> None:
        self._career_store = career_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_resume_profile_save",
            description="Save a structured resume profile product record from a current-session resume artifact.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "resume_profile_id": {"type": "string"},
                    "source_artifact_id": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "basic_info": {"type": "object"},
                    "education": {"type": "array"},
                    "work_experience": {"type": "array"},
                    "project_experience": {"type": "array"},
                    "skills": {"type": "array"},
                    "certificates": {"type": "array"},
                    "awards": {"type": "array"},
                    "self_evaluation": {"type": "string"},
                    "raw_text_artifact_id": {"type": "string"},
                    "diagnosis_artifact_id": {"type": "string"},
                    "diagnosis": {"type": "object"},
                },
                "required": ["source_artifact_id", "evidence_refs"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            source_artifact_id = _required_current_artifact(
                self._session_repository,
                run_context.session_id,
                args,
                "source_artifact_id",
            )
            raw_text_artifact_id = _optional_current_artifact(
                self._session_repository,
                run_context.session_id,
                args.get("raw_text_artifact_id"),
                field_name="raw_text_artifact_id",
            )
            diagnosis_artifact_id = _optional_current_artifact(
                self._session_repository,
                run_context.session_id,
                args.get("diagnosis_artifact_id"),
                field_name="diagnosis_artifact_id",
            )
            existing = _find_current_session_record(
                self._career_store.list_resume_profiles(),
                run_context.session_id,
                lambda item: item.source_artifact_id == source_artifact_id,
            )
            if existing is not None:
                if existing.diagnosis_artifact_id is None and diagnosis_artifact_id is not None:
                    updated = existing.copy()
                    updated.diagnosis_artifact_id = diagnosis_artifact_id
                    updated.raw_text_artifact_id = updated.raw_text_artifact_id or raw_text_artifact_id
                    updated.evidence_refs = _sanitize_current_session_evidence_refs(
                        self._career_store,
                        self._session_repository,
                        run_context.session_id,
                        _append_evidence_refs(
                            list(updated.evidence_refs),
                            source_artifact_id,
                            raw_text_artifact_id,
                            diagnosis_artifact_id,
                        ),
                    )
                    saved = self._career_store.save_resume_profile(updated)
                    return _record_result(
                        "career_resume_profile_save",
                        "resume_profile",
                        saved.resume_profile_id,
                        saved,
                        extra={"idempotent_update": True, "updated_fields": ["diagnosis_artifact_id"]},
                    )
                return _record_result(
                    "career_resume_profile_save",
                    "resume_profile",
                    existing.resume_profile_id,
                    existing,
                    extra={"idempotent_reused": True},
                )
            args = _align_resume_profile_arguments_with_source(
                self._session_repository,
                run_context.session_id,
                source_artifact_id,
                args,
            )
            record = ResumeProfile(
                resume_profile_id=_optional_prefixed_id(args.get("resume_profile_id"), "resume_profile")
                or _new_id("resume_profile"),
                status=CareerRecordStatus.ACTIVE,
                source_session_id=run_context.session_id,
                source_artifact_id=source_artifact_id,
                evidence_refs=_sanitize_current_session_evidence_refs(
                    self._career_store,
                    self._session_repository,
                    run_context.session_id,
                    _append_evidence_refs(
                        _required_evidence_refs(args.get("evidence_refs")),
                        source_artifact_id,
                        raw_text_artifact_id,
                        diagnosis_artifact_id,
                    ),
                ),
                created_at=_now(),
                updated_at=_now(),
                basic_info=_optional_dict(args.get("basic_info"), field_name="basic_info"),
                education=_optional_list(args.get("education"), field_name="education"),
                work_experience=_optional_list(args.get("work_experience"), field_name="work_experience"),
                project_experience=_optional_list(args.get("project_experience"), field_name="project_experience"),
                skills=_optional_list(args.get("skills"), field_name="skills"),
                certificates=_optional_list(args.get("certificates"), field_name="certificates"),
                awards=_optional_list(args.get("awards"), field_name="awards"),
                self_evaluation=_optional_string(args.get("self_evaluation")) or "",
                raw_text_artifact_id=raw_text_artifact_id,
                diagnosis_artifact_id=diagnosis_artifact_id,
                diagnosis=_optional_dict(
                    args.get("diagnosis"),
                    field_name="diagnosis",
                    string_fallback_key="raw_text",
                ),
            )
            saved = self._career_store.save_resume_profile(record)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("career_resume_profile_save", "resume_profile", saved.resume_profile_id, saved)


class CareerResumeProfileGetTool:
    """Read one resume profile."""

    def __init__(self, career_store: CareerProductStore) -> None:
        self._career_store = career_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_resume_profile_get",
            description=(
                "Read a saved resume profile by resume_profile_id. Only use ids returned by save/list tools "
                "or child-agent results; call career_resume_profile_list first if unsure."
            ),
            parameters_schema={
                "type": "object",
                "properties": {"resume_profile_id": {"type": "string"}},
                "required": ["resume_profile_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _required_string(args.get("resume_profile_id"), field_name="resume_profile_id")
            record, extra = _get_record_or_current_session_single(
                record_id,
                session_id=run_context.session_id,
                records=self._career_store.list_resume_profiles(),
                getter=self._career_store.get_resume_profile,
            )
            if record is None:
                return _not_found_result(
                    "career_resume_profile_get",
                    "resume_profile",
                    record_id,
                    extra=extra,
                )
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("career_resume_profile_get", "resume_profile", record.resume_profile_id, record, extra=extra)


class CareerResumeProfileListTool:
    """List resume profiles."""

    def __init__(self, career_store: CareerProductStore) -> None:
        self._career_store = career_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_resume_profile_list",
            description="List saved resume profile product records. Use this before get when the resume_profile_id is uncertain.",
            parameters_schema={
                "type": "object",
                "properties": {"include_archived": {"type": "boolean", "default": False}},
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        args = _require_arguments(arguments)
        records = self._career_store.list_resume_profiles(include_archived=_optional_bool(args.get("include_archived")))
        return _list_result("career_resume_profile_list", "resume_profile", records)


class CareerProfileGetTool:
    """Read one career profile."""

    def __init__(self, career_store: CareerProductStore) -> None:
        self._career_store = career_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_profile_get",
            description="Read the user-visible career profile product record.",
            parameters_schema={
                "type": "object",
                "properties": {"career_profile_id": {"type": "string", "default": _DEFAULT_CAREER_PROFILE_ID}},
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _optional_string(args.get("career_profile_id")) or _DEFAULT_CAREER_PROFILE_ID
            record = self._career_store.get_career_profile(record_id)
            if record is None:
                return _not_found_result("career_profile_get", "career_profile", record_id)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("career_profile_get", "career_profile", record.career_profile_id, record)


class CareerProfileMergeTool:
    """Merge updates into one career profile, creating it if missing."""

    def __init__(self, career_store: CareerProductStore, session_repository: SessionRepository) -> None:
        self._career_store = career_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_profile_merge",
            description=(
                "Merge evidence-backed updates into the user-visible career profile. "
                "Allowed update fields: career_goal, target_roles, preferred_industries, preferred_cities, "
                "strengths, weaknesses, skills, interests, education_summary, experience_summary, "
                "resume_issues, interview_weaknesses. Common aliases are normalized: target_direction->career_goal, "
                "target_position->target_roles, core_skills->skills."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "career_profile_id": {"type": "string", "default": _DEFAULT_CAREER_PROFILE_ID},
                    "updates": {
                        "type": "object",
                        "description": (
                            "Only use allowed CareerProfile fields: career_goal, target_roles, "
                            "preferred_industries, preferred_cities, strengths, weaknesses, skills, interests, "
                            "education_summary, experience_summary, resume_issues, interview_weaknesses."
                        ),
                    },
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "source_artifact_id": {"type": "string"},
                },
                "required": ["updates", "evidence_refs"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _normalize_merge_arguments(_require_arguments(arguments), id_fields=("career_profile_id",))
            record_id = _optional_string(args.get("career_profile_id")) or _DEFAULT_CAREER_PROFILE_ID
            source_artifact_id = _optional_current_artifact(
                self._session_repository,
                run_context.session_id,
                args.get("source_artifact_id"),
                field_name="source_artifact_id",
            )
            current = _current_session_record_by_id(
                self._career_store.get_career_profile,
                record_id,
                run_context.session_id,
            )
            if record_id != _DEFAULT_CAREER_PROFILE_ID and current is None:
                record_id = _DEFAULT_CAREER_PROFILE_ID
                current = _current_session_record_by_id(
                    self._career_store.get_career_profile,
                    record_id,
                    run_context.session_id,
                )
            evidence_refs = _sanitize_current_session_evidence_refs(
                self._career_store,
                self._session_repository,
                run_context.session_id,
                _append_evidence_refs(_required_evidence_refs(args.get("evidence_refs")), source_artifact_id),
            )
            updates = _normalize_career_profile_updates(_required_dict(args.get("updates"), field_name="updates"))
            if not evidence_refs and current is not None:
                evidence_refs = _sanitize_current_session_evidence_refs(
                    self._career_store,
                    self._session_repository,
                    run_context.session_id,
                    _append_evidence_refs(current.evidence_refs, current.source_artifact_id),
                )
            if current is None:
                self._career_store.save_career_profile(
                    CareerProfile(
                        career_profile_id=record_id,
                        status=CareerRecordStatus.ACTIVE,
                        source_session_id=run_context.session_id,
                        source_artifact_id=source_artifact_id,
                        evidence_refs=evidence_refs,
                        created_at=_now(),
                        updated_at=_now(),
                    )
                )
            record = self._career_store.merge_career_profile(
                record_id,
                updates=updates,
                evidence_refs=evidence_refs,
                source_artifact_id=source_artifact_id,
            )
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("career_profile_merge", "career_profile", record.career_profile_id, record)


class CareerJDAnalysisSaveTool:
    """Persist one JD analysis."""

    def __init__(self, career_store: CareerProductStore, session_repository: SessionRepository) -> None:
        self._career_store = career_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_jd_analysis_save",
            description="Save a structured JD analysis product record from a current-session JD artifact.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "jd_analysis_id": {"type": "string"},
                    "source_artifact_id": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "company": {"type": "string"},
                    "position": {"type": "string"},
                    "seniority": {"type": "string"},
                    "required_skills": {"type": "array", "items": {"type": "string"}},
                    "preferred_skills": {"type": "array", "items": {"type": "string"}},
                    "responsibilities": {"type": "array", "items": {"type": "string"}},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "risk_signals": {"type": "array", "items": {"type": "string"}},
                    "interview_focus": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["source_artifact_id", "evidence_refs"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            source_artifact_id = _required_current_artifact(
                self._session_repository,
                run_context.session_id,
                args,
                "source_artifact_id",
            )
            existing = _find_current_session_record(
                self._career_store.list_jd_analyses(),
                run_context.session_id,
                lambda item: item.source_artifact_id == source_artifact_id,
            )
            if existing is not None:
                return _record_result(
                    "career_jd_analysis_save",
                    "jd_analysis",
                    existing.jd_analysis_id,
                    existing,
                    extra={"idempotent_reused": True},
                )
            record = JDAnalysis(
                jd_analysis_id=_optional_prefixed_id(args.get("jd_analysis_id"), "jd") or _new_id("jd"),
                status=CareerRecordStatus.ACTIVE,
                source_session_id=run_context.session_id,
                source_artifact_id=source_artifact_id,
                evidence_refs=_sanitize_current_session_evidence_refs(
                    self._career_store,
                    self._session_repository,
                    run_context.session_id,
                    _append_evidence_refs(_required_evidence_refs(args.get("evidence_refs")), source_artifact_id),
                ),
                created_at=_now(),
                updated_at=_now(),
                company=_optional_string(args.get("company")) or "",
                position=_optional_string(args.get("position")) or "",
                seniority=_optional_string(args.get("seniority")) or "",
                required_skills=_optional_string_list(args.get("required_skills"), field_name="required_skills"),
                preferred_skills=_optional_string_list(args.get("preferred_skills"), field_name="preferred_skills"),
                responsibilities=_optional_string_list(args.get("responsibilities"), field_name="responsibilities"),
                keywords=_optional_string_list(args.get("keywords"), field_name="keywords"),
                risk_signals=_optional_string_list(args.get("risk_signals"), field_name="risk_signals"),
                interview_focus=_optional_string_list(args.get("interview_focus"), field_name="interview_focus"),
            )
            saved = self._career_store.save_jd_analysis(record)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("career_jd_analysis_save", "jd_analysis", saved.jd_analysis_id, saved)


class CareerJDAnalysisGetTool:
    """Read one JD analysis."""

    def __init__(self, career_store: CareerProductStore) -> None:
        self._career_store = career_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_jd_analysis_get",
            description="Read a saved JD analysis by jd_analysis_id.",
            parameters_schema={
                "type": "object",
                "properties": {"jd_analysis_id": {"type": "string"}},
                "required": ["jd_analysis_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _required_string(args.get("jd_analysis_id"), field_name="jd_analysis_id")
            record, extra = _get_record_or_current_session_single(
                record_id,
                session_id=run_context.session_id,
                records=self._career_store.list_jd_analyses(),
                getter=self._career_store.get_jd_analysis,
            )
            if record is None:
                return _not_found_result("career_jd_analysis_get", "jd_analysis", record_id, extra=extra)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("career_jd_analysis_get", "jd_analysis", record.jd_analysis_id, record, extra=extra)


class CareerJDAnalysisListTool:
    """List JD analyses."""

    def __init__(self, career_store: CareerProductStore) -> None:
        self._career_store = career_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_jd_analysis_list",
            description="List saved JD analysis product records.",
            parameters_schema={
                "type": "object",
                "properties": {"include_archived": {"type": "boolean", "default": False}},
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        args = _require_arguments(arguments)
        records = self._career_store.list_jd_analyses(include_archived=_optional_bool(args.get("include_archived")))
        return _list_result("career_jd_analysis_list", "jd_analysis", records)


class CareerJobFitReportSaveTool:
    """Persist one job fit report."""

    def __init__(self, career_store: CareerProductStore, session_repository: SessionRepository) -> None:
        self._career_store = career_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_job_fit_report_save",
            description="Save a job fit report between a resume profile and a JD analysis.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "job_fit_report_id": {"type": "string"},
                    "source_artifact_id": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "jd_analysis_id": {"type": "string"},
                    "resume_profile_id": {"type": "string"},
                    "career_profile_id": {
                        "type": "string",
                        "description": (
                            "Use career_profile_default unless an existing career_profile_id was returned by "
                            "career_profile_get/merge or current workflow state. Do not invent profile ids."
                        ),
                    },
                    "overall_score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "score_breakdown": {
                        "type": "object",
                        "additionalProperties": {"type": "integer", "minimum": 0, "maximum": 100},
                    },
                    "matched_evidence": {
                        "type": "array",
                        "description": (
                            "Evidence-backed matches only. Do not claim the candidate has a JD skill unless it is "
                            "present in the resume source artifact or saved ResumeProfile; put unsupported JD skills "
                            "in gaps instead."
                        ),
                    },
                    "gaps": {"type": "array"},
                    "resume_optimization_direction": {"type": "array"},
                    "interview_preparation_focus": {"type": "array"},
                    "recommendation": {
                        "type": "string",
                        "enum": ["recommended", "cautious", "not_recommended"],
                    },
                    "report_artifact_id": {"type": "string"},
                },
                "required": [
                    "source_artifact_id",
                    "jd_analysis_id",
                    "resume_profile_id",
                    "career_profile_id",
                    "report_artifact_id",
                ],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            raw_source_artifact_id = args.get("source_artifact_id")
            if _is_missing_merge_argument(raw_source_artifact_id):
                raw_source_artifact_id = _infer_job_fit_source_artifact_id(
                    self._career_store,
                    session_id=run_context.session_id,
                    args=args,
                )
            source_artifact_id = _require_current_artifact(
                self._session_repository,
                run_context.session_id,
                _required_string(raw_source_artifact_id, field_name="source_artifact_id"),
                field_name="source_artifact_id",
            )
            report_artifact_id = _required_current_artifact(
                self._session_repository,
                run_context.session_id,
                args,
                "report_artifact_id",
            )
            jd_analysis_id = _optional_prefixed_id(
                _required_string(args.get("jd_analysis_id"), field_name="jd_analysis_id"),
                "jd",
            )
            if jd_analysis_id is None:
                raise ToolExecutionError("'jd_analysis_id' must be a non-empty string.")
            resume_profile_id = _optional_prefixed_id(
                _required_string(args.get("resume_profile_id"), field_name="resume_profile_id"),
                "resume_profile",
            )
            if resume_profile_id is None:
                raise ToolExecutionError("'resume_profile_id' must be a non-empty string.")
            raw_career_profile_id = args.get("career_profile_id")
            if _is_missing_merge_argument(raw_career_profile_id) or _is_reserved_string(raw_career_profile_id):
                raw_career_profile_id = _DEFAULT_CAREER_PROFILE_ID
            career_profile_id = _optional_prefixed_id(
                _required_string(raw_career_profile_id, field_name="career_profile_id"),
                "career_profile",
            )
            if career_profile_id is None:
                raise ToolExecutionError("'career_profile_id' must be a non-empty string.")
            evidence_refs = _optional_evidence_refs(args.get("evidence_refs"))
            evidence_refs = _append_evidence_refs(
                evidence_refs,
                source_artifact_id,
                report_artifact_id,
                resume_profile_id,
                career_profile_id,
            )
            jd_analysis_id, evidence_refs = _ensure_jd_analysis_ref(
                self._career_store,
                self._session_repository,
                session_id=run_context.session_id,
                jd_analysis_id=jd_analysis_id,
                source_artifact_id=source_artifact_id,
                evidence_refs=evidence_refs,
            )
            career_profile_id, evidence_refs = _ensure_career_profile_ref(
                self._career_store,
                session_id=run_context.session_id,
                career_profile_id=career_profile_id,
                source_artifact_id=source_artifact_id,
                evidence_refs=evidence_refs,
            )
            evidence_refs = _append_evidence_refs(
                evidence_refs,
                report_artifact_id,
                resume_profile_id,
                career_profile_id,
            )
            evidence_refs = _sanitize_current_session_evidence_refs(
                self._career_store,
                self._session_repository,
                run_context.session_id,
                evidence_refs,
            )
            existing = _find_current_session_record(
                self._career_store.list_job_fit_reports(),
                run_context.session_id,
                lambda item: (
                    item.jd_analysis_id == jd_analysis_id
                    and item.resume_profile_id == resume_profile_id
                    and (
                        item.report_artifact_id == report_artifact_id
                        or item.source_artifact_id == source_artifact_id
                    )
                ),
            )
            if existing is not None:
                return _record_result(
                    "career_job_fit_report_save",
                    "job_fit_report",
                    existing.job_fit_report_id,
                    existing,
                    extra={"idempotent_reused": True},
                )
            matched_evidence = _optional_list(args.get("matched_evidence"), field_name="matched_evidence")
            gaps = _optional_list(args.get("gaps"), field_name="gaps")
            matched_evidence, gaps = _sanitize_job_fit_matched_evidence(
                career_store=self._career_store,
                session_repository=self._session_repository,
                session_id=run_context.session_id,
                resume_profile_id=resume_profile_id,
                matched_evidence=matched_evidence,
                gaps=gaps,
            )
            record = JobFitReport(
                job_fit_report_id=_optional_prefixed_id(args.get("job_fit_report_id"), "fit") or _new_id("fit"),
                status=CareerRecordStatus.ACTIVE,
                source_session_id=run_context.session_id,
                source_artifact_id=source_artifact_id,
                evidence_refs=evidence_refs,
                created_at=_now(),
                updated_at=_now(),
                jd_analysis_id=jd_analysis_id,
                resume_profile_id=resume_profile_id,
                career_profile_id=career_profile_id,
                overall_score=_optional_score(args.get("overall_score"), field_name="overall_score", default=0),
                score_breakdown=_optional_score_breakdown(args.get("score_breakdown")),
                matched_evidence=matched_evidence,
                gaps=gaps,
                resume_optimization_direction=_optional_list(
                    args.get("resume_optimization_direction"),
                    field_name="resume_optimization_direction",
                ),
                interview_preparation_focus=_optional_list(
                    args.get("interview_preparation_focus"),
                    field_name="interview_preparation_focus",
                ),
                recommendation=_optional_job_fit_recommendation(args),
                report_artifact_id=report_artifact_id,
            )
            saved = self._career_store.save_job_fit_report(record)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("career_job_fit_report_save", "job_fit_report", saved.job_fit_report_id, saved)


class CareerJobFitReportGetTool:
    """Read one job fit report."""

    def __init__(self, career_store: CareerProductStore) -> None:
        self._career_store = career_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_job_fit_report_get",
            description="Read a saved job fit report by job_fit_report_id.",
            parameters_schema={
                "type": "object",
                "properties": {"job_fit_report_id": {"type": "string"}},
                "required": ["job_fit_report_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _required_string(args.get("job_fit_report_id"), field_name="job_fit_report_id")
            record, extra = _get_record_or_current_session_single(
                record_id,
                session_id=run_context.session_id,
                records=self._career_store.list_job_fit_reports(),
                getter=self._career_store.get_job_fit_report,
            )
            if record is None:
                return _not_found_result("career_job_fit_report_get", "job_fit_report", record_id, extra=extra)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("career_job_fit_report_get", "job_fit_report", record.job_fit_report_id, record, extra=extra)


class CareerJobFitReportListTool:
    """List job fit reports."""

    def __init__(self, career_store: CareerProductStore) -> None:
        self._career_store = career_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_job_fit_report_list",
            description="List saved job fit report product records.",
            parameters_schema={
                "type": "object",
                "properties": {"include_archived": {"type": "boolean", "default": False}},
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        args = _require_arguments(arguments)
        records = self._career_store.list_job_fit_reports(include_archived=_optional_bool(args.get("include_archived")))
        return _list_result("career_job_fit_report_list", "job_fit_report", records)


class CareerResumeVersionCreateTool:
    """Create one final resume version product record."""

    def __init__(self, career_store: CareerProductStore, session_repository: SessionRepository) -> None:
        self._career_store = career_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_resume_version_create",
            description=(
                "Create an evidence-bound markdown resume version product record from generated content. "
                "The resume body must not add candidate facts or quantified metrics that are absent from "
                "the base resume source artifact or saved ResumeProfile."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "resume_version_id": {"type": "string"},
                    "base_resume_profile_id": {"type": "string"},
                    "resume_profile_id": {
                        "type": "string",
                        "description": "Compatibility alias for base_resume_profile_id.",
                    },
                    "target_jd_analysis_id": {"type": "string"},
                    "title": {"type": "string"},
                    "artifact_id": {"type": "string"},
                    "artifact_title": {"type": "string"},
                    "content": {
                        "type": "string",
                        "description": (
                            "Markdown resume content. When artifact_id is omitted, the tool creates a "
                            "generated_file artifact. Use JDAnalysis/JobFitReport only for emphasis; do not "
                            "invent company names, dates, projects, skills, percentages, latency, QPS, counts, "
                            "scores, contact details, salary, school names, or outcomes unless they are explicitly "
                            "present in candidate source facts. Omit missing fields; never fill demo values. "
                            "This is the deliverable resume body only; do not include JD match tables, risk tables, "
                            "gap analysis, or interview-prep notes in content."
                        ),
                    },
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "change_summary": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Actual evidence-backed changes only; do not claim unsupported additions.",
                    },
                    "keyword_strategy": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Keywords that are present in the resume content or directly supported by candidate "
                            "evidence. Missing JD keywords belong in risk_notes, not keyword_strategy."
                        ),
                    },
                    "risk_notes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Missing or weak facts belong here, not in the resume body.",
                    },
                    "use_safe_fallback": {
                        "type": "boolean",
                        "description": (
                            "When true and no content/artifact is provided, create a conservative, evidence-bound "
                            "resume version from the saved ResumeProfile. Runtime uses this for deterministic "
                            "required-action recovery; normal callers should prefer passing full content."
                        ),
                    },
                },
                "required": ["base_resume_profile_id", "title", "evidence_refs"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            evidence_refs = _optional_evidence_refs(args.get("evidence_refs"))
            base_resume_profile_id = _resolve_resume_version_base_profile_id(args, evidence_refs)
            target_jd_analysis_id = _resolve_resume_version_target_jd_analysis_id(args, evidence_refs)
            repaired_base_resume_profile_id = _repair_missing_current_session_record_id(
                base_resume_profile_id,
                session_id=run_context.session_id,
                records=self._career_store.list_resume_profiles(),
                getter=self._career_store.get_resume_profile,
                id_attr="resume_profile_id",
            )
            if repaired_base_resume_profile_id != base_resume_profile_id:
                base_resume_profile_id = repaired_base_resume_profile_id
                evidence_refs = _remove_non_current_prefixed_refs(
                    evidence_refs,
                    prefix="resume_profile_",
                    valid_ids={base_resume_profile_id},
                )
            if target_jd_analysis_id is not None:
                repaired_target_jd_analysis_id = _repair_missing_current_session_record_id(
                    target_jd_analysis_id,
                    session_id=run_context.session_id,
                    records=self._career_store.list_jd_analyses(),
                    getter=self._career_store.get_jd_analysis,
                    id_attr="jd_analysis_id",
                )
                if repaired_target_jd_analysis_id != target_jd_analysis_id:
                    target_jd_analysis_id = repaired_target_jd_analysis_id
                    evidence_refs = _remove_non_current_prefixed_refs(
                        evidence_refs,
                        prefix="jd_",
                        valid_ids={target_jd_analysis_id},
                    )
            evidence_refs = _append_evidence_refs(evidence_refs, base_resume_profile_id, target_jd_analysis_id)
            title = _required_string(args.get("title"), field_name="title")
            change_summary = _optional_string_list(args.get("change_summary"), field_name="change_summary")
            keyword_strategy = _optional_string_list(args.get("keyword_strategy"), field_name="keyword_strategy")
            risk_notes = _optional_string_list(args.get("risk_notes"), field_name="risk_notes")
            change_summary, keyword_strategy, risk_notes = _sanitize_resume_version_metadata_placeholders(
                change_summary=change_summary,
                keyword_strategy=keyword_strategy,
                risk_notes=risk_notes,
            )
            raw_artifact_id = args.get("artifact_id")
            content_arg = _optional_string(args.get("content"))
            use_safe_fallback = _optional_bool_field(args.get("use_safe_fallback"), field_name="use_safe_fallback")
            safe_fallback_from_invalid_draft = False
            sanitized_unverified_contacts: list[str] = []
            ignored_invalid_output_artifact_id: str | None = None
            artifact_id: str | None = None
            content: str
            if content_arg is not None:
                if raw_artifact_id is not None:
                    referenced_artifact_id = _require_current_artifact(
                        self._session_repository,
                        run_context.session_id,
                        _required_string(raw_artifact_id, field_name="artifact_id"),
                        field_name="artifact_id",
                    )
                    if referenced_artifact_id not in evidence_refs:
                        evidence_refs.append(referenced_artifact_id)
                content = content_arg
                content, risk_notes, sanitized_unverified_contacts = _sanitize_resume_version_unverified_contacts(
                    career_store=self._career_store,
                    session_repository=self._session_repository,
                    session_id=run_context.session_id,
                    base_resume_profile_id=base_resume_profile_id,
                    content=content,
                    risk_notes=risk_notes,
                )
                try:
                    _reject_invalid_resume_version_text(
                        career_store=self._career_store,
                        session_repository=self._session_repository,
                        session_id=run_context.session_id,
                        base_resume_profile_id=base_resume_profile_id,
                        title=title,
                        content=content,
                        change_summary=change_summary,
                        keyword_strategy=keyword_strategy,
                        risk_notes=risk_notes,
                    )
                except ToolExecutionError as exc:
                    fallback = _safe_resume_version_fallback_after_validation_failure(
                        career_store=self._career_store,
                        session_repository=self._session_repository,
                        context=run_context,
                        base_resume_profile_id=base_resume_profile_id,
                        target_jd_analysis_id=target_jd_analysis_id,
                        title=title,
                        risk_notes=risk_notes,
                        allow_without_prior_failure=(
                            use_safe_fallback or _can_auto_fallback_resume_version_validation_error(str(exc))
                        ),
                    )
                    if fallback is None:
                        raise
                    content = fallback["content"]
                    change_summary = fallback["change_summary"]
                    keyword_strategy = fallback["keyword_strategy"]
                    risk_notes = fallback["risk_notes"]
                    safe_fallback_from_invalid_draft = True
                    _reject_invalid_resume_version_text(
                        career_store=self._career_store,
                        session_repository=self._session_repository,
                        session_id=run_context.session_id,
                        base_resume_profile_id=base_resume_profile_id,
                        title=title,
                        content=content,
                        change_summary=change_summary,
                        keyword_strategy=keyword_strategy,
                        risk_notes=risk_notes,
                    )
            elif raw_artifact_id is None:
                fallback = _safe_resume_version_fallback_after_validation_failure(
                    career_store=self._career_store,
                    session_repository=self._session_repository,
                    context=run_context,
                    base_resume_profile_id=base_resume_profile_id,
                        target_jd_analysis_id=target_jd_analysis_id,
                        title=title,
                        risk_notes=risk_notes,
                        allow_without_prior_failure=use_safe_fallback,
                    )
                if fallback is None:
                    raise ToolExecutionError("career_resume_version_create requires either content or artifact_id.")
                content = fallback["content"]
                change_summary = fallback["change_summary"]
                keyword_strategy = fallback["keyword_strategy"]
                risk_notes = fallback["risk_notes"]
                safe_fallback_from_invalid_draft = True
                _reject_invalid_resume_version_text(
                    career_store=self._career_store,
                    session_repository=self._session_repository,
                    session_id=run_context.session_id,
                    base_resume_profile_id=base_resume_profile_id,
                    title=title,
                    content=content,
                    change_summary=change_summary,
                    keyword_strategy=keyword_strategy,
                    risk_notes=risk_notes,
                )
            else:
                requested_artifact_id = _required_string(raw_artifact_id, field_name="artifact_id")
                try:
                    requested_artifact = require_session_artifact(
                        self._session_repository,
                        run_context.session_id,
                        requested_artifact_id,
                    )
                except ToolExecutionError as exc:
                    raise ToolExecutionError(
                        f"artifact_id must reference a current session artifact: {requested_artifact_id}"
                    ) from exc
                if requested_artifact.kind == "generated_file":
                    artifact_id = requested_artifact.artifact_id
                    content = _read_current_artifact_text_or_empty(
                        self._session_repository,
                        run_context.session_id,
                        artifact_id,
                    )
                else:
                    ignored_invalid_output_artifact_id = requested_artifact.artifact_id
                    if ignored_invalid_output_artifact_id not in evidence_refs:
                        evidence_refs.append(ignored_invalid_output_artifact_id)
                    fallback = _safe_resume_version_fallback_after_validation_failure(
                        career_store=self._career_store,
                        session_repository=self._session_repository,
                        context=run_context,
                        base_resume_profile_id=base_resume_profile_id,
                        target_jd_analysis_id=target_jd_analysis_id,
                        title=title,
                        risk_notes=risk_notes,
                        allow_without_prior_failure=True,
                    )
                    if fallback is None:
                        raise ToolExecutionError(
                            "artifact_id must reference a generated_file artifact for ResumeVersion output; "
                            f"got {requested_artifact.kind}: {requested_artifact.artifact_id}. If this is an "
                            "input resume artifact, save a ResumeProfile first or pass markdown content so "
                            "career_resume_version_create can create a new generated_file artifact."
                        )
                    content = fallback["content"]
                    change_summary = fallback["change_summary"]
                    keyword_strategy = fallback["keyword_strategy"]
                    risk_notes = fallback["risk_notes"]
                    safe_fallback_from_invalid_draft = True
                try:
                    _reject_invalid_resume_version_text(
                        career_store=self._career_store,
                        session_repository=self._session_repository,
                        session_id=run_context.session_id,
                        base_resume_profile_id=base_resume_profile_id,
                        title=title,
                        content=content,
                        change_summary=change_summary,
                        keyword_strategy=keyword_strategy,
                        risk_notes=risk_notes,
                    )
                except ToolExecutionError as exc:
                    fallback = _safe_resume_version_fallback_after_validation_failure(
                        career_store=self._career_store,
                        session_repository=self._session_repository,
                        context=run_context,
                        base_resume_profile_id=base_resume_profile_id,
                        target_jd_analysis_id=target_jd_analysis_id,
                        title=title,
                        risk_notes=risk_notes,
                        allow_without_prior_failure=(
                            use_safe_fallback or _can_auto_fallback_resume_version_validation_error(str(exc))
                        ),
                    )
                    if fallback is None:
                        raise
                    artifact_id = None
                    content = fallback["content"]
                    change_summary = fallback["change_summary"]
                    keyword_strategy = fallback["keyword_strategy"]
                    risk_notes = fallback["risk_notes"]
                    safe_fallback_from_invalid_draft = True
                    _reject_invalid_resume_version_text(
                        career_store=self._career_store,
                        session_repository=self._session_repository,
                        session_id=run_context.session_id,
                        base_resume_profile_id=base_resume_profile_id,
                        title=title,
                        content=content,
                        change_summary=change_summary,
                        keyword_strategy=keyword_strategy,
                        risk_notes=risk_notes,
                    )

            if artifact_id is None:
                existing = _find_current_session_record(
                    self._career_store.list_resume_versions(),
                    run_context.session_id,
                    lambda item: (
                        item.base_resume_profile_id == base_resume_profile_id
                        and item.target_jd_analysis_id == target_jd_analysis_id
                        and item.title == title
                    ),
                )
                if existing is not None:
                    return _record_result(
                        "career_resume_version_create",
                        "resume_version",
                        existing.resume_version_id,
                        existing,
                        extra={"idempotent_reused": True},
                    )
                artifact_id = _create_generated_markdown_artifact(
                    self._session_repository,
                    run_context,
                    title=_optional_string(args.get("artifact_title")) or title,
                    content=content,
                )
            else:
                existing = _find_current_session_record(
                    self._career_store.list_resume_versions(),
                    run_context.session_id,
                    lambda item: (
                        item.artifact_id == artifact_id
                        and item.base_resume_profile_id == base_resume_profile_id
                        and item.target_jd_analysis_id == target_jd_analysis_id
                    ),
                )
                if existing is not None:
                    return _record_result(
                        "career_resume_version_create",
                        "resume_version",
                        existing.resume_version_id,
                        existing,
                        extra={"idempotent_reused": True},
                    )
            if artifact_id not in evidence_refs:
                evidence_refs.append(artifact_id)
            evidence_refs = _sanitize_current_session_evidence_refs(
                self._career_store,
                self._session_repository,
                run_context.session_id,
                evidence_refs,
            )
            record = ResumeVersion(
                resume_version_id=_optional_prefixed_id(args.get("resume_version_id"), "resume_version")
                or _new_id("resume_version"),
                status=CareerRecordStatus.ACTIVE,
                source_session_id=run_context.session_id,
                source_artifact_id=artifact_id,
                evidence_refs=evidence_refs,
                created_at=_now(),
                updated_at=_now(),
                base_resume_profile_id=base_resume_profile_id,
                target_jd_analysis_id=target_jd_analysis_id,
                title=title,
                format="markdown",
                artifact_id=artifact_id,
                change_summary=change_summary,
                keyword_strategy=keyword_strategy,
                risk_notes=risk_notes,
            )
            saved = self._career_store.save_resume_version(record)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        extra: dict[str, Any] = {}
        if safe_fallback_from_invalid_draft:
            extra["safe_fallback_from_invalid_draft"] = True
        if ignored_invalid_output_artifact_id is not None:
            extra["ignored_invalid_output_artifact_id"] = ignored_invalid_output_artifact_id
        if sanitized_unverified_contacts:
            extra["sanitized_unverified_contacts"] = sanitized_unverified_contacts
        return _record_result("career_resume_version_create", "resume_version", saved.resume_version_id, saved, extra=extra)


class CareerResumeVersionGetTool:
    """Read one resume version."""

    def __init__(self, career_store: CareerProductStore) -> None:
        self._career_store = career_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_resume_version_get",
            description="Read a saved resume version by resume_version_id.",
            parameters_schema={
                "type": "object",
                "properties": {"resume_version_id": {"type": "string"}},
                "required": ["resume_version_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _required_string(args.get("resume_version_id"), field_name="resume_version_id")
            record, extra = _get_record_or_current_session_single(
                record_id,
                session_id=run_context.session_id,
                records=self._career_store.list_resume_versions(),
                getter=self._career_store.get_resume_version,
            )
            if record is None:
                return _not_found_result("career_resume_version_get", "resume_version", record_id, extra=extra)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("career_resume_version_get", "resume_version", record.resume_version_id, record, extra=extra)


class CareerResumeVersionListTool:
    """List resume versions."""

    def __init__(self, career_store: CareerProductStore) -> None:
        self._career_store = career_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_resume_version_list",
            description="List saved resume version product records.",
            parameters_schema={
                "type": "object",
                "properties": {"include_archived": {"type": "boolean", "default": False}},
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        args = _require_arguments(arguments)
        records = self._career_store.list_resume_versions(include_archived=_optional_bool(args.get("include_archived")))
        return _list_result("career_resume_version_list", "resume_version", records)


class CareerApplicationCreateTool:
    """Create one user-visible career application project."""

    def __init__(self, career_store: CareerProductStore, session_repository: SessionRepository) -> None:
        self._career_store = career_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_application_create",
            description=(
                "Create a career application project that links reusable career product records. "
                "Use this after JD analysis, job fit report, or resume version records exist. "
                "When jd_analysis_id or job_fit_report_id is provided, company, position, source_artifact_id, "
                "resume_profile_id, and career_profile_id can be inferred from existing product records."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "application_id": {"type": "string"},
                    "company": {"type": "string"},
                    "position": {"type": "string"},
                    "location": {"type": "string"},
                    "job_url": {"type": "string"},
                    "stage": {
                        "type": "string",
                        "enum": [
                            "draft",
                            "analyzing",
                            "ready_to_apply",
                            "applied",
                            "interviewing",
                            "offer",
                            "rejected",
                            "paused",
                        ],
                        "default": "draft",
                    },
                    "priority": {"type": "string", "enum": ["high", "medium", "low"], "default": "medium"},
                    "resume_profile_id": {"type": "string"},
                    "career_profile_id": {"type": "string"},
                    "jd_analysis_id": {"type": "string"},
                    "job_fit_report_id": {"type": "string"},
                    "resume_version_ids": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                    "next_actions": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                    "source_artifact_id": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["evidence_refs"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(_normalize_application_create_raw_arguments(arguments))
            evidence_refs = _optional_evidence_refs(args.get("evidence_refs"))
            source_artifact_id = _optional_current_artifact(
                self._session_repository,
                run_context.session_id,
                args.get("source_artifact_id"),
                field_name="source_artifact_id",
            )
            job_fit_report_id = _optional_prefixed_id(args.get("job_fit_report_id"), "fit")
            jd_analysis_id = _optional_prefixed_id(args.get("jd_analysis_id"), "jd")
            resume_profile_id = _optional_prefixed_id(args.get("resume_profile_id"), "resume_profile")
            career_profile_id = _optional_prefixed_id(args.get("career_profile_id"), "career_profile")
            resume_version_ids = _optional_prefixed_id_list(
                args.get("resume_version_ids"),
                prefix="resume_version",
                field_name="resume_version_ids",
            )
            resume_version_ids = _existing_current_session_resume_version_ids(
                self._career_store,
                session_id=run_context.session_id,
                resume_version_ids=resume_version_ids,
            )
            evidence_refs = _remove_non_current_prefixed_refs(
                evidence_refs,
                prefix="resume_version_",
                valid_ids=set(resume_version_ids),
            )
            inferred_fit_record = _infer_single_current_fit_report(
                self._career_store,
                session_id=run_context.session_id,
                source_artifact_id=source_artifact_id,
                jd_analysis_id=jd_analysis_id,
                resume_profile_id=resume_profile_id,
            )
            if job_fit_report_id is None and inferred_fit_record is not None:
                job_fit_report_id = inferred_fit_record.job_fit_report_id
            if job_fit_report_id is not None:
                repaired_job_fit_report_id = _repair_missing_current_session_record_id(
                    job_fit_report_id,
                    session_id=run_context.session_id,
                    records=self._career_store.list_job_fit_reports(),
                    getter=self._career_store.get_job_fit_report,
                    id_attr="job_fit_report_id",
                )
                if repaired_job_fit_report_id != job_fit_report_id:
                    job_fit_report_id = repaired_job_fit_report_id
                    evidence_refs = _remove_non_current_prefixed_refs(
                        evidence_refs,
                        prefix="fit_",
                        valid_ids={job_fit_report_id},
                    )

            fit_record = self._career_store.get_job_fit_report(job_fit_report_id) if job_fit_report_id else None
            if fit_record is not None:
                if jd_analysis_id is None or _current_session_record_by_id(
                    self._career_store.get_jd_analysis,
                    jd_analysis_id,
                    run_context.session_id,
                ) is None:
                    jd_analysis_id = fit_record.jd_analysis_id
                if resume_profile_id is None or _current_session_record_by_id(
                    self._career_store.get_resume_profile,
                    resume_profile_id,
                    run_context.session_id,
                ) is None:
                    resume_profile_id = fit_record.resume_profile_id
                if career_profile_id is None or _current_session_record_by_id(
                    self._career_store.get_career_profile,
                    career_profile_id,
                    run_context.session_id,
                ) is None:
                    career_profile_id = fit_record.career_profile_id
                if fit_record.source_artifact_id is not None:
                    source_artifact_id = fit_record.source_artifact_id
                evidence_refs = _remove_non_current_prefixed_refs(
                    evidence_refs,
                    prefix="jd_",
                    valid_ids={fit_record.jd_analysis_id},
                )
                evidence_refs = _remove_non_current_prefixed_refs(
                    evidence_refs,
                    prefix="resume_profile_",
                    valid_ids={fit_record.resume_profile_id},
                )
                evidence_refs = _remove_non_current_prefixed_refs(
                    evidence_refs,
                    prefix="career_profile_",
                    valid_ids={fit_record.career_profile_id},
                )
                evidence_refs = _append_evidence_refs(
                    evidence_refs,
                    fit_record.job_fit_report_id,
                    fit_record.jd_analysis_id,
                    fit_record.resume_profile_id,
                    fit_record.career_profile_id,
                    fit_record.source_artifact_id,
                    fit_record.report_artifact_id,
                )

            if jd_analysis_id is not None:
                repaired_jd_analysis_id = _repair_missing_current_session_record_id(
                    jd_analysis_id,
                    session_id=run_context.session_id,
                    records=self._career_store.list_jd_analyses(),
                    getter=self._career_store.get_jd_analysis,
                    id_attr="jd_analysis_id",
                )
                if repaired_jd_analysis_id != jd_analysis_id:
                    jd_analysis_id = repaired_jd_analysis_id
                    evidence_refs = _remove_non_current_prefixed_refs(
                        evidence_refs,
                        prefix="jd_",
                        valid_ids={jd_analysis_id},
                    )
            if resume_profile_id is not None:
                repaired_resume_profile_id = _repair_missing_current_session_record_id(
                    resume_profile_id,
                    session_id=run_context.session_id,
                    records=self._career_store.list_resume_profiles(),
                    getter=self._career_store.get_resume_profile,
                    id_attr="resume_profile_id",
                )
                if repaired_resume_profile_id != resume_profile_id:
                    resume_profile_id = repaired_resume_profile_id
                    evidence_refs = _remove_non_current_prefixed_refs(
                        evidence_refs,
                        prefix="resume_profile_",
                        valid_ids={resume_profile_id},
                    )
            jd_record = self._career_store.get_jd_analysis(jd_analysis_id) if jd_analysis_id else None
            if jd_record is not None:
                if jd_record.source_artifact_id is not None:
                    source_artifact_id = jd_record.source_artifact_id
                evidence_refs = _append_evidence_refs(
                    evidence_refs,
                    jd_record.jd_analysis_id,
                    jd_record.source_artifact_id,
                )

            application_fields = _application_create_fields_from_sources(
                args=args,
                jd_record=jd_record,
                fit_record=fit_record,
            )
            company = application_fields["company"]
            position = application_fields["position"]
            _ensure_application_has_backing_context(
                jd_record=jd_record,
                fit_record=fit_record,
                company=company,
                position=position,
                source_artifact_id=source_artifact_id,
                resume_version_ids=resume_version_ids,
            )
            evidence_refs = _append_evidence_refs(
                evidence_refs,
                source_artifact_id,
                resume_profile_id,
                career_profile_id,
                jd_analysis_id,
                job_fit_report_id,
                *resume_version_ids,
            )
            evidence_refs = _sanitize_current_session_evidence_refs(
                self._career_store,
                self._session_repository,
                run_context.session_id,
                evidence_refs,
            )

            existing = _find_current_session_record(
                self._career_store.list_career_applications(),
                run_context.session_id,
                lambda item: _is_same_application_project(
                    item,
                    company=company,
                    position=position,
                    jd_analysis_id=jd_analysis_id,
                    job_fit_report_id=job_fit_report_id,
                ),
            )
            if existing is not None:
                return _record_result(
                    "career_application_create",
                    "career_application",
                    existing.application_id,
                    existing,
                    extra={"idempotent_reused": True},
                )

            record = CareerApplication(
                application_id=_optional_prefixed_id(args.get("application_id"), "application")
                or _new_application_id(company=company, position=position),
                status=CareerRecordStatus.ACTIVE,
                source_session_id=run_context.session_id,
                source_artifact_id=source_artifact_id,
                evidence_refs=evidence_refs,
                created_at=_now(),
                updated_at=_now(),
                company=company,
                position=position,
                location=application_fields["location"],
                job_url=_optional_string(args.get("job_url")) or "",
                stage=_normalize_application_stage_or_default(_optional_string(args.get("stage")), default="draft"),
                priority=_optional_string(args.get("priority")) or "medium",
                resume_profile_id=resume_profile_id,
                career_profile_id=career_profile_id,
                jd_analysis_id=jd_analysis_id,
                job_fit_report_id=job_fit_report_id,
                resume_version_ids=resume_version_ids,
                summary=application_fields["summary"],
                next_actions=application_fields["next_actions"],
                risks=application_fields["risks"],
                notes=application_fields["notes"],
            )
            saved = self._career_store.save_career_application(record)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("career_application_create", "career_application", saved.application_id, saved)


class CareerApplicationGetTool:
    """Read one career application project."""

    def __init__(self, career_store: CareerProductStore) -> None:
        self._career_store = career_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_application_get",
            description="Read a saved career application project by application_id.",
            parameters_schema={
                "type": "object",
                "properties": {"application_id": {"type": "string"}},
                "required": ["application_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _required_string(args.get("application_id"), field_name="application_id")
            record, extra = _get_record_or_current_session_single(
                record_id,
                session_id=run_context.session_id,
                records=self._career_store.list_career_applications(),
                getter=self._career_store.get_career_application,
            )
            if record is None:
                return _not_found_result("career_application_get", "career_application", record_id, extra=extra)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("career_application_get", "career_application", record.application_id, record, extra=extra)


class CareerApplicationListTool:
    """List career application projects."""

    def __init__(self, career_store: CareerProductStore) -> None:
        self._career_store = career_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_application_list",
            description="List saved career application projects.",
            parameters_schema={
                "type": "object",
                "properties": {"include_archived": {"type": "boolean", "default": False}},
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        args = _require_arguments(arguments)
        records = self._career_store.list_career_applications(
            include_archived=_optional_bool(args.get("include_archived"))
        )
        return _list_result("career_application_list", "career_application", records)


class CareerApplicationMergeTool:
    """Merge evidence-backed updates into one career application project."""

    def __init__(self, career_store: CareerProductStore, session_repository: SessionRepository) -> None:
        self._career_store = career_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="career_application_merge",
            description=(
                "Merge evidence-backed updates into a career application project. "
                "Allowed update fields: stage, priority, resume_profile_id, career_profile_id, jd_analysis_id, "
                "job_fit_report_id, resume_version_ids, summary, next_actions, risks, notes."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "application_id": {"type": "string"},
                    "updates": {
                        "type": "object",
                        "description": (
                            "Only use allowed CareerApplication fields: stage, priority, resume_profile_id, "
                            "career_profile_id, jd_analysis_id, job_fit_report_id, resume_version_ids, summary, "
                            "next_actions, risks, notes."
                        ),
                    },
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "source_artifact_id": {"type": "string"},
                },
                "required": ["application_id", "updates", "evidence_refs"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _normalize_application_merge_arguments(_require_arguments(arguments))
            record_id = _required_string(args.get("application_id"), field_name="application_id")
            source_artifact_id = _optional_current_artifact(
                self._session_repository,
                run_context.session_id,
                args.get("source_artifact_id"),
                field_name="source_artifact_id",
            )
            record = self._career_store.merge_career_application(
                record_id,
                updates=_career_application_merge_updates(args.get("updates")),
                evidence_refs=_sanitize_current_session_evidence_refs(
                    self._career_store,
                    self._session_repository,
                    run_context.session_id,
                    _required_evidence_refs(args.get("evidence_refs")),
                ),
                source_artifact_id=source_artifact_id,
            )
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("career_application_merge", "career_application", record.application_id, record)


def _require_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ToolExecutionError("Tool arguments must be an object.")
    path_fields = {"path", "file_path", "workspace_path", "absolute_path", "relative_path"}
    store_owned_fields = {"created_at", "updated_at", "source_session_id", "status"}
    for key in arguments:
        if not isinstance(key, str) or not key.strip():
            raise ToolExecutionError("Tool argument keys must be non-empty strings.")
        normalized_key = key.strip()
        if normalized_key in path_fields:
            raise ToolExecutionError(f"Path arguments are not allowed: {key}")
        if normalized_key in store_owned_fields:
            raise ToolExecutionError(f"Store-owned fields are not accepted: {key}")
    return arguments


def _normalize_application_create_raw_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Map common LLM aliases before the global store-owned field check."""

    if not isinstance(arguments, dict):
        return arguments
    normalized = dict(arguments)
    raw_status = normalized.pop("status", None)
    for key in ("created_at", "updated_at", "source_session_id"):
        normalized.pop(key, None)
    if "stage" not in normalized and isinstance(raw_status, str):
        normalized_stage = _normalize_application_stage(raw_status)
        if normalized_stage in _CAREER_APPLICATION_STAGES:
            normalized["stage"] = normalized_stage
    return normalized


def _normalize_application_stage(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stage = value.strip()
    if not stage:
        return stage
    alias = _CAREER_APPLICATION_STAGE_ALIASES.get(stage)
    if alias is not None:
        return alias
    normalized = stage.casefold()
    alias = _CAREER_APPLICATION_STAGE_ALIASES.get(normalized)
    if alias is not None:
        return alias
    compact = re.sub(r"[\s_\-:：/|]+", "", normalized)
    alias = _CAREER_APPLICATION_STAGE_ALIASES.get(compact)
    if alias is not None:
        return alias
    if _looks_like_applied_stage(compact):
        return "applied"
    if _looks_like_resume_ready_stage(compact):
        return "ready_to_apply"
    if _looks_like_analysis_done_stage(compact):
        return "draft"
    if "面试" in compact or "interview" in compact:
        return "interviewing"
    if "offer" in compact or "录用" in compact:
        return "offer"
    if "拒" in compact or "reject" in compact:
        return "rejected"
    if "暂停" in compact or "pause" in compact:
        return "paused"
    return stage


def _normalize_application_merge_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Repair common CareerApplication merge shapes before strict field validation."""

    try:
        normalized = _normalize_merge_arguments(arguments, id_fields=("application_id",))
    except ToolExecutionError:
        raw_updates = arguments.get("updates")
        if not isinstance(raw_updates, str) or not raw_updates.strip():
            raise
        normalized = dict(arguments)
        normalized["updates"] = {"summary": raw_updates.strip()}
    normalized = dict(normalized)

    raw_updates = normalized.get("updates")
    updates: dict[str, Any]
    if isinstance(raw_updates, dict):
        updates = dict(raw_updates)
    elif isinstance(raw_updates, str) and raw_updates.strip():
        try:
            decoded_updates = _decode_json_objectish_string(raw_updates, field_name="updates")
        except ToolExecutionError:
            updates = {"summary": raw_updates.strip()}
        else:
            updates = dict(decoded_updates) if isinstance(decoded_updates, dict) else {"summary": raw_updates.strip()}
    elif _is_missing_merge_argument(raw_updates):
        updates = {}
    else:
        normalized["updates"] = raw_updates
        return normalized

    meta_fields = {"application_id", "evidence_refs", "source_artifact_id", "updates"}
    for raw_key, value in normalized.items():
        if raw_key in meta_fields:
            continue
        key = _CAREER_APPLICATION_UPDATE_ALIASES.get(raw_key, raw_key)
        if key in _CAREER_APPLICATION_ALLOWED_UPDATE_FIELDS and key not in updates:
            updates[key] = value
    normalized["updates"] = updates
    return normalized


def _normalize_application_stage_or_default(value: Any, *, default: str) -> str:
    normalized = _normalize_application_stage(value)
    return normalized if normalized in _CAREER_APPLICATION_STAGES else default


def _looks_like_resume_ready_stage(value: str) -> bool:
    if not value:
        return False
    if ("简历" in value or "resume" in value) and ("定制" in value or "tailor" in value or "custom" in value):
        return True
    if ("简历" in value or "resume" in value or "tailor" in value or "custom" in value) and (
        "完成" in value
        or "生成" in value
        or "定制" in value
        or "优化" in value
        or "ready" in value
        or "done" in value
        or "complete" in value
    ):
        return True
    return ("投递" in value or "申请" in value or "apply" in value) and (
        "待" in value
        or "准备" in value
        or "前" in value
        or "可" in value
        or "ready" in value
        or "toapply" in value
    )


def _looks_like_applied_stage(value: str) -> bool:
    if not value:
        return False
    has_apply_signal = "投递" in value or "申请" in value or "apply" in value or "applied" in value
    has_done_signal = (
        "已" in value
        or "完成" in value
        or "成功" in value
        or "提交" in value
        or "submitted" in value
        or "applied" in value
    )
    has_ready_signal = "待" in value or "准备" in value or "前" in value or "可" in value or "ready" in value
    return has_apply_signal and has_done_signal and not has_ready_signal


def _looks_like_analysis_done_stage(value: str) -> bool:
    if not value:
        return False
    return ("分析" in value or "匹配" in value or "analysis" in value or "fit" in value) and (
        "完成" in value or "结束" in value or "done" in value or "complete" in value or "ready" in value
    )


def _career_application_merge_updates(raw: Any) -> dict[str, Any]:
    payload = _required_dict(raw, field_name="updates")
    output: dict[str, Any] = {}
    for raw_key, value in payload.items():
        if not isinstance(raw_key, str):
            raise ToolExecutionError("CareerApplication merge update fields must be strings.")
        key = _CAREER_APPLICATION_UPDATE_ALIASES.get(raw_key, raw_key)
        if key in _CAREER_APPLICATION_ALLOWED_UPDATE_FIELDS:
            if key == "stage":
                normalized_stage = _normalize_application_stage(value)
                if normalized_stage in _CAREER_APPLICATION_STAGES:
                    output[key] = normalized_stage
                continue
            elif key in {"summary", "notes"}:
                value = _optional_career_application_text(value, field_name=key) or ""
            elif key in {"next_actions", "risks"}:
                value = _sanitize_career_application_text_list(
                    _optional_career_application_text_list(value, field_name=key)
                )
            output[key] = value
            continue
        if raw_key in _CAREER_APPLICATION_IGNORED_UPDATE_FIELDS:
            continue
        raise ToolExecutionError(f"Unsupported CareerApplication merge field: {raw_key}")
    if output.get("resume_version_ids") and "stage" not in output:
        output["stage"] = "ready_to_apply"
    return output


def _sanitize_career_application_text(value: str) -> str:
    sanitized = value.strip()
    replacements = (
        ("替换为真实数据", "需要补充真实数据"),
        ("待补充", "需要补充"),
        ("待补", "需要补充"),
        ("待填写", "需要填写"),
        ("待填", "需要填写"),
        ("待完善", "需要完善"),
        ("占位", "临时记录"),
        ("TODO", "需要处理"),
        ("TBD", "需要确认"),
    )
    for source, target in replacements:
        sanitized = re.sub(re.escape(source), target, sanitized, flags=re.IGNORECASE)
    return sanitized.strip()


def _sanitize_career_application_text_list(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        sanitized = _sanitize_career_application_text(value)
        if not sanitized or sanitized in seen:
            continue
        output.append(sanitized)
        seen.add(sanitized)
    return output


def _optional_career_application_text_list(raw: Any, *, field_name: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    if not isinstance(raw, list):
        raise ToolExecutionError(f"'{field_name}' must be a list of strings.")
    output: list[str] = []
    for item in raw:
        if isinstance(item, str):
            if not item.strip():
                continue
            output.append(item.strip())
            continue
        if isinstance(item, dict):
            text = _career_application_structured_item_text(item)
            if text:
                output.append(text)
                continue
            continue
        raise ToolExecutionError(f"each '{field_name}' item must be a non-empty string.")
    return output


def _career_application_structured_item_text(item: dict[str, Any]) -> str | None:
    primary = _first_optional_string(
        item,
        ("description", "summary", "content", "text", "action", "task", "title", "name", "risk", "item"),
    )
    if primary is None:
        return None

    parts: list[str] = []
    severity = _optional_string(item.get("severity"))
    if severity:
        parts.append(f"[{severity}]")
    kind = _optional_string(item.get("type"))
    if kind:
        parts.append(kind)
    parts.append(primary)
    mitigation = _optional_string(item.get("mitigation"))
    if mitigation:
        parts.append(f"mitigation: {mitigation}")
    return " - ".join(parts)


def _first_optional_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _optional_string(payload.get(key))
        if value:
            return value
    return None


def _optional_career_application_text(raw: Any, *, field_name: str) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return _sanitize_career_application_text(raw)
    if isinstance(raw, list):
        values = _optional_career_application_text_list(raw, field_name=field_name)
        return "\n".join(_sanitize_career_application_text_list(values)) or None
    raise ToolExecutionError(f"'{field_name}' must be a string or list of strings.")


def _application_create_fields_from_sources(
    *,
    args: dict[str, Any],
    jd_record: JDAnalysis | None,
    fit_record: JobFitReport | None,
) -> dict[str, Any]:
    """Build CareerApplication display fields from product records when available."""

    if jd_record is None and fit_record is None:
        return {
            "company": _optional_string(args.get("company")) or "",
            "position": _optional_string(args.get("position")) or "",
            "location": _optional_string(args.get("location")) or "",
            "summary": _sanitize_career_application_text(_optional_string(args.get("summary")) or ""),
            "next_actions": _sanitize_career_application_text_list(
                _optional_string_list(args.get("next_actions"), field_name="next_actions")
            ),
            "risks": _sanitize_career_application_text_list(
                _optional_string_list(args.get("risks"), field_name="risks")
            ),
            "notes": _sanitize_career_application_text(_optional_string(args.get("notes")) or ""),
        }

    company = jd_record.company if jd_record is not None else ""
    position = jd_record.position if jd_record is not None else ""
    next_actions = _application_next_actions_from_fit(fit_record)
    risks = _application_risks_from_records(jd_record=jd_record, fit_record=fit_record)
    summary = _application_summary_from_records(
        company=company,
        position=position,
        fit_record=fit_record,
    )
    notes = ""
    if fit_record is not None:
        notes = f"基于 JobFitReport {fit_record.job_fit_report_id} 创建。"
    elif jd_record is not None:
        notes = f"基于 JDAnalysis {jd_record.jd_analysis_id} 创建。"
    return {
        "company": company,
        "position": position,
        "location": "",
        "summary": _sanitize_career_application_text(summary),
        "next_actions": _sanitize_career_application_text_list(next_actions),
        "risks": _sanitize_career_application_text_list(risks),
        "notes": _sanitize_career_application_text(notes),
    }


def _ensure_application_has_backing_context(
    *,
    jd_record: JDAnalysis | None,
    fit_record: JobFitReport | None,
    company: str,
    position: str,
    source_artifact_id: str | None,
    resume_version_ids: list[str],
) -> None:
    if jd_record is not None or fit_record is not None:
        return
    if company.strip() or position.strip() or source_artifact_id is not None or resume_version_ids:
        return
    raise ToolExecutionError(
        "CareerApplication requires a valid current-session JDAnalysis/JobFitReport, ResumeVersion, "
        "or explicit company/position/source_artifact_id. Create JDAnalysis and JobFitReport before "
        "creating a JD-backed application."
    )


def _application_summary_from_records(
    *,
    company: str,
    position: str,
    fit_record: JobFitReport | None,
) -> str:
    role_text = position or "目标岗位"
    company_text = company or "未明确公司"
    parts = [f"{company_text} · {role_text}"]
    if fit_record is not None:
        parts.append(f"匹配度 {fit_record.overall_score}/100")
        if fit_record.recommendation:
            parts.append(f"推荐策略 {fit_record.recommendation}")
    return "，".join(parts) + "。"


def _application_next_actions_from_fit(fit_record: JobFitReport | None) -> list[str]:
    if fit_record is None:
        return []
    return _dedupe_application_text_items(
        [
            *_application_text_items(fit_record.resume_optimization_direction),
            *_application_text_items(fit_record.interview_preparation_focus),
        ],
        limit=6,
    )


def _application_risks_from_records(
    *,
    jd_record: JDAnalysis | None,
    fit_record: JobFitReport | None,
) -> list[str]:
    values: list[str] = []
    if fit_record is not None:
        values.extend(_application_text_items(fit_record.gaps))
    if jd_record is not None:
        values.extend(jd_record.risk_signals)
    return _dedupe_application_text_items(values, limit=6)


def _application_text_items(values: list[Any]) -> list[str]:
    output: list[str] = []
    for item in values:
        text = _application_text_item(item)
        if text:
            output.append(text)
    return output


def _application_text_item(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("title", "summary", "description", "gap", "risk", "action", "evidence", "text", "name"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        parts = [value.strip() for value in item.values() if isinstance(value, str) and value.strip()]
        return "；".join(parts[:3])
    if isinstance(item, (int, float)):
        return str(item)
    return ""


def _dedupe_application_text_items(values: list[str], *, limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        if not value or value in seen:
            continue
        output.append(value)
        seen.add(value)
        if len(output) >= limit:
            break
    return output


def _ensure_career_profile_ref(
    career_store: CareerProductStore,
    *,
    session_id: str,
    career_profile_id: str,
    source_artifact_id: str | None,
    evidence_refs: list[str],
) -> tuple[str, list[str]]:
    if _current_session_record_by_id(career_store.get_career_profile, career_profile_id, session_id) is not None:
        return career_profile_id, _append_evidence_refs(evidence_refs, career_profile_id, source_artifact_id)
    fallback = _single_current_session_record(career_store.list_career_profiles(), session_id)
    if isinstance(fallback, CareerProfile):
        evidence_refs = _remove_non_current_prefixed_refs(
            evidence_refs,
            prefix="career_profile_",
            valid_ids={fallback.career_profile_id},
        )
        return fallback.career_profile_id, _append_evidence_refs(
            evidence_refs,
            fallback.career_profile_id,
            source_artifact_id,
        )
    if career_profile_id != _DEFAULT_CAREER_PROFILE_ID:
        evidence_refs = _remove_non_current_prefixed_refs(
            evidence_refs,
            prefix="career_profile_",
            valid_ids={_DEFAULT_CAREER_PROFILE_ID},
        )
        career_profile_id = _DEFAULT_CAREER_PROFILE_ID
    now = _now()
    saved = career_store.save_career_profile(
        CareerProfile(
            career_profile_id=career_profile_id,
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=source_artifact_id,
            evidence_refs=evidence_refs,
            created_at=now,
            updated_at=now,
        )
    )
    return saved.career_profile_id, _append_evidence_refs(evidence_refs, saved.career_profile_id, source_artifact_id)


def _ensure_jd_analysis_ref(
    career_store: CareerProductStore,
    session_repository: SessionRepository,
    *,
    session_id: str,
    jd_analysis_id: str,
    source_artifact_id: str,
    evidence_refs: list[str],
) -> tuple[str, list[str]]:
    current = _current_session_record_by_id(career_store.get_jd_analysis, jd_analysis_id, session_id)
    if current is not None:
        return jd_analysis_id, _append_evidence_refs(evidence_refs, jd_analysis_id, source_artifact_id)

    existing = _find_current_session_record(
        career_store.list_jd_analyses(),
        session_id,
        lambda item: item.source_artifact_id == source_artifact_id,
    )
    if isinstance(existing, JDAnalysis):
        evidence_refs = _remove_non_current_prefixed_refs(
            evidence_refs,
            prefix="jd_",
            valid_ids={existing.jd_analysis_id},
        )
        return existing.jd_analysis_id, _append_evidence_refs(
            evidence_refs,
            existing.jd_analysis_id,
            existing.source_artifact_id,
        )

    jd_text = _read_current_artifact_text_or_empty(session_repository, session_id, source_artifact_id)
    inferred_skills = _infer_jd_required_skills(jd_text)
    now = _now()
    saved = career_store.save_jd_analysis(
        JDAnalysis(
            jd_analysis_id=jd_analysis_id,
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=source_artifact_id,
            evidence_refs=[source_artifact_id],
            created_at=now,
            updated_at=now,
            company="",
            position=_infer_jd_position(jd_text),
            seniority="",
            required_skills=inferred_skills,
            preferred_skills=[],
            responsibilities=[],
            keywords=list(inferred_skills),
            risk_signals=["JDAnalysis 由 JobFitReport 保存时兜底创建；建议后续补充更完整的 JD 结构化字段。"],
            interview_focus=[],
        )
    )
    evidence_refs = _remove_non_current_prefixed_refs(
        evidence_refs,
        prefix="jd_",
        valid_ids={saved.jd_analysis_id},
    )
    return saved.jd_analysis_id, _append_evidence_refs(evidence_refs, saved.jd_analysis_id, source_artifact_id)


def _infer_job_fit_source_artifact_id(
    career_store: CareerProductStore,
    *,
    session_id: str,
    args: dict[str, Any],
) -> str | None:
    jd_analysis_id = _optional_prefixed_id(args.get("jd_analysis_id"), "jd")
    if jd_analysis_id is not None:
        jd_record = _current_session_record_by_id(career_store.get_jd_analysis, jd_analysis_id, session_id)
        if isinstance(jd_record, JDAnalysis) and jd_record.source_artifact_id:
            return jd_record.source_artifact_id
    fallback = _single_current_session_record(career_store.list_jd_analyses(), session_id)
    if isinstance(fallback, JDAnalysis) and fallback.source_artifact_id:
        return fallback.source_artifact_id
    return None


def _infer_jd_position(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    for pattern in (
        re.compile(r"招聘\s*([^，。；\n]{2,40}(?:工程师|经理|专家|实习生|开发))"),
        re.compile(r"岗位[:：]\s*([^，。；\n]{2,40})"),
        re.compile(r"职位[:：]\s*([^，。；\n]{2,40})"),
    ):
        match = pattern.search(normalized)
        if match is not None:
            return match.group(1).strip()
    return ""


def _infer_jd_required_skills(text: str) -> list[str]:
    display_names = {
        "agent": "Agent",
        "docker": "Docker",
        "fastapi": "FastAPI",
        "langchain": "LangChain",
        "langgraph": "LangGraph",
        "milvus": "Milvus",
        "mysql": "MySQL",
        "postgresql": "PostgreSQL",
        "python": "Python",
        "rag": "RAG",
        "redis": "Redis",
        "vector_search": "向量检索",
    }
    lowered = text.casefold()
    output: list[str] = []
    for canonical, aliases in _RESUME_SOURCE_TECH_TERMS.items():
        if canonical not in display_names:
            continue
        if not any(alias.casefold() in lowered for alias in aliases):
            continue
        output.append(display_names[canonical])
    return output


def _sanitize_job_fit_matched_evidence(
    *,
    career_store: CareerProductStore,
    session_repository: SessionRepository,
    session_id: str,
    resume_profile_id: str,
    matched_evidence: list[Any],
    gaps: list[Any],
) -> tuple[list[Any], list[Any]]:
    """Move unsupported candidate-skill claims from matched evidence to gaps."""

    try:
        profile = career_store.get_resume_profile(resume_profile_id)
    except (StorageError, ValidationError):
        return matched_evidence, gaps
    if profile is None or profile.source_session_id != session_id:
        return matched_evidence, gaps

    support_text = "\n".join(
        (
            _resume_profile_source_text(session_repository, session_id=session_id, profile=profile),
            _resume_profile_supported_fact_text(profile),
        )
    )
    if not support_text.strip():
        return matched_evidence, gaps

    sanitized_matches: list[Any] = []
    sanitized_gaps = list(gaps)
    for item in matched_evidence:
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, sort_keys=True)
        unsupported_terms = _unsupported_resume_version_tech_terms(text, support_text)
        if unsupported_terms:
            gap_text = (
                "未证实匹配项已转为差距: "
                + text
                + "；未在候选人事实中找到支持: "
                + ", ".join(unsupported_terms[:8])
            )
            if gap_text not in sanitized_gaps:
                sanitized_gaps.append(gap_text)
            continue
        sanitized_matches.append(item)
    return sanitized_matches, sanitized_gaps


def _normalize_merge_arguments(arguments: dict[str, Any], *, id_fields: tuple[str, ...]) -> dict[str, Any]:
    """Repair common LLM merge argument nesting without weakening field validation."""
    normalized = dict(arguments)
    raw_updates = normalized.get("updates")
    if _is_missing_merge_argument(raw_updates):
        for alias in ("fields", "field_updates", "profile_fields", "profile_updates"):
            alias_updates = normalized.get(alias)
            if _is_missing_merge_argument(alias_updates):
                continue
            normalized["updates"] = alias_updates
            raw_updates = alias_updates
            break
    if not isinstance(raw_updates, str) or not raw_updates.strip():
        return normalized
    payload = _decode_json_objectish_string(raw_updates, field_name="updates")
    if not isinstance(payload, dict):
        return normalized

    meta_fields = {"evidence_refs", "source_artifact_id", *id_fields}
    for field_name in meta_fields:
        value = payload.get(field_name)
        if value is not None and _is_missing_merge_argument(normalized.get(field_name)):
            normalized[field_name] = value

    nested_updates = payload.get("updates")
    if nested_updates is not None:
        normalized["updates"] = nested_updates
        return normalized

    update_payload = {key: value for key, value in payload.items() if key not in meta_fields}
    normalized["updates"] = update_payload
    return normalized


def _is_missing_merge_argument(raw: Any) -> bool:
    if raw is None:
        return True
    if isinstance(raw, str):
        return not raw.strip()
    if isinstance(raw, list | dict | tuple | set):
        return len(raw) == 0
    return False


def _decode_json_objectish_string(raw: str, *, field_name: str) -> dict[str, Any]:
    text = raw.strip()
    try:
        decoded = _decode_json_object_string(text, field_name=field_name)
        if isinstance(decoded, dict):
            return decoded
    except ToolExecutionError:
        pass

    decoder = json.JSONDecoder()
    try:
        first, end_index = decoder.raw_decode(text)
    except json.JSONDecodeError:
        first = None
        end_index = -1
    if isinstance(first, dict):
        tail = text[end_index:].strip()
        if tail.startswith(","):
            try:
                extra = _decode_json_object_string("{" + tail[1:].strip() + "}", field_name=field_name)
            except ToolExecutionError:
                extra = None
            if isinstance(extra, dict):
                return {**first, **extra}

    try:
        wrapped = _decode_json_object_string("{" + text + "}", field_name=field_name)
    except ToolExecutionError as exc:
        raise ToolExecutionError(f"'{field_name}' must be an object.") from exc
    if not isinstance(wrapped, dict):
        raise ToolExecutionError(f"'{field_name}' must be an object.")
    return wrapped


def _required_current_artifact(
    session_repository: SessionRepository,
    session_id: str,
    arguments: dict[str, Any],
    field_name: str,
) -> str:
    return _require_current_artifact(
        session_repository,
        session_id,
        _required_string(arguments.get(field_name), field_name=field_name),
        field_name=field_name,
    )


def _optional_current_artifact(
    session_repository: SessionRepository,
    session_id: str,
    raw: Any,
    *,
    field_name: str,
) -> str | None:
    value = _optional_string(raw)
    if value is None:
        return None
    if not value.startswith("artifact_"):
        return None
    return _require_current_artifact(
        session_repository,
        session_id,
        value,
        field_name=field_name,
    )


def _require_current_artifact(
    session_repository: SessionRepository,
    session_id: str,
    artifact_id: str,
    *,
    field_name: str,
) -> str:
    try:
        artifact = require_session_artifact(session_repository, session_id, artifact_id)
    except ToolExecutionError as exc:
        raise ToolExecutionError(f"{field_name} must reference a current session artifact: {artifact_id}") from exc
    return artifact.artifact_id


def _require_current_generated_artifact(
    session_repository: SessionRepository,
    session_id: str,
    artifact_id: str,
    *,
    field_name: str,
) -> str:
    try:
        artifact = require_session_artifact(session_repository, session_id, artifact_id)
    except ToolExecutionError as exc:
        raise ToolExecutionError(f"{field_name} must reference a current session artifact: {artifact_id}") from exc
    if artifact.kind != "generated_file":
        raise ToolExecutionError(
            f"{field_name} must reference a generated_file artifact for ResumeVersion output; "
            f"got {artifact.kind}: {artifact_id}. If you have markdown resume content, pass it as content "
            "so career_resume_version_create can create a new generated_file artifact."
        )
    return artifact.artifact_id


def _required_string(raw: Any, *, field_name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ToolExecutionError(f"'{field_name}' must be a non-empty string.")
    return raw.strip()


def _optional_string(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ToolExecutionError("optional string argument must be a string.")
    normalized = raw.strip()
    return normalized or None


def _is_reserved_string(raw: Any) -> bool:
    return isinstance(raw, str) and is_reserved_reference_value(raw.strip())


def _optional_prefixed_id(raw: Any, prefix: str) -> str | None:
    value = _optional_string(raw)
    if value is None:
        return None
    if is_reserved_reference_value(value):
        return None
    marker = f"{prefix}_"
    stem = value[len(marker):] if value.startswith(marker) else value
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    if not slug:
        return None
    normalized = f"{marker}{slug[:100]}"
    if is_reserved_reference_value(normalized):
        return None
    return normalized


def _resolve_resume_version_base_profile_id(arguments: dict[str, Any], evidence_refs: list[str]) -> str:
    explicit = _optional_prefixed_id(arguments.get("base_resume_profile_id"), "resume_profile")
    if explicit is not None:
        return explicit
    alias = _optional_prefixed_id(arguments.get("resume_profile_id"), "resume_profile")
    if alias is not None:
        return alias
    candidates = sorted({ref for ref in evidence_refs if ref.startswith("resume_profile_")})
    if len(candidates) == 1:
        return candidates[0]
    raise ToolExecutionError("'base_resume_profile_id' must be a non-empty string.")


def _resolve_resume_version_target_jd_analysis_id(arguments: dict[str, Any], evidence_refs: list[str]) -> str | None:
    explicit = _optional_prefixed_id(arguments.get("target_jd_analysis_id"), "jd")
    if explicit is not None:
        return explicit
    candidates = sorted({ref for ref in evidence_refs if ref.startswith("jd_")})
    if len(candidates) == 1:
        return candidates[0]
    return None


def _optional_prefixed_id_list(raw: Any, *, prefix: str, field_name: str) -> list[str]:
    values = _optional_string_list(raw, field_name=field_name)
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _optional_prefixed_id(value, prefix)
        if normalized is None:
            continue
        if normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output


def _append_evidence_refs(evidence_refs: list[str], *refs: str | None) -> list[str]:
    output = list(evidence_refs)
    seen = set(output)
    for ref in refs:
        if ref is None:
            continue
        normalized = _normalize_evidence_ref(ref)
        if normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output


def _sanitize_current_session_artifact_evidence_refs(
    session_repository: SessionRepository,
    session_id: str,
    evidence_refs: list[str],
) -> list[str]:
    current_artifact_ids = {
        artifact.artifact_id for artifact in session_repository.list_session_artifacts(session_id)
    }
    output: list[str] = []
    seen: set[str] = set()
    for ref in evidence_refs:
        if ref.startswith("artifact_") and ref not in current_artifact_ids:
            continue
        if ref in seen:
            continue
        output.append(ref)
        seen.add(ref)
    return output


def _sanitize_current_session_evidence_refs(
    career_store: CareerProductStore,
    session_repository: SessionRepository,
    session_id: str,
    evidence_refs: list[str],
) -> list[str]:
    artifact_sanitized = _sanitize_current_session_artifact_evidence_refs(
        session_repository,
        session_id,
        evidence_refs,
    )
    current_product_ids = _current_session_product_ref_ids(career_store, session_id)
    output: list[str] = []
    seen: set[str] = set()
    for ref in artifact_sanitized:
        if _is_product_evidence_ref(ref) and ref not in current_product_ids:
            continue
        if ref in seen:
            continue
        output.append(ref)
        seen.add(ref)
    return output


def _current_session_product_ref_ids(career_store: CareerProductStore, session_id: str) -> set[str]:
    ids: set[str] = set()
    for resume_profile in career_store.list_resume_profiles():
        if resume_profile.source_session_id == session_id:
            ids.add(resume_profile.resume_profile_id)
    for career_profile in career_store.list_career_profiles():
        if career_profile.source_session_id == session_id:
            ids.add(career_profile.career_profile_id)
    for jd_analysis in career_store.list_jd_analyses():
        if jd_analysis.source_session_id == session_id:
            ids.add(jd_analysis.jd_analysis_id)
    for fit_report in career_store.list_job_fit_reports():
        if fit_report.source_session_id == session_id:
            ids.add(fit_report.job_fit_report_id)
    for resume_version in career_store.list_resume_versions():
        if resume_version.source_session_id == session_id:
            ids.add(resume_version.resume_version_id)
    for application in career_store.list_career_applications():
        if application.source_session_id == session_id:
            ids.add(application.application_id)
    return ids


def _is_product_evidence_ref(ref: str) -> bool:
    return ref.startswith(_PRODUCT_EVIDENCE_PREFIXES)


def _is_same_application_project(
    record: CareerApplication,
    *,
    company: str,
    position: str,
    jd_analysis_id: str | None,
    job_fit_report_id: str | None,
) -> bool:
    if job_fit_report_id is not None and record.job_fit_report_id == job_fit_report_id:
        return True
    if jd_analysis_id is not None and record.jd_analysis_id == jd_analysis_id:
        return True
    return bool(company and position and record.company == company and record.position == position)


def _validate_resume_profile_source_alignment(
    session_repository: SessionRepository,
    session_id: str,
    source_artifact_id: str,
    args: dict[str, Any],
) -> None:
    try:
        source_text = session_repository.read_session_artifact_text(session_id, source_artifact_id)
    except Exception:
        return
    source_terms = _extract_resume_source_terms(source_text)
    if len(source_terms) < 2:
        return

    profile_text = _resume_profile_fact_text(args)
    profile_terms = _extract_resume_source_terms(profile_text)
    if not profile_terms.intersection(source_terms):
        expected = ", ".join(sorted(source_terms))
        raise ToolExecutionError(
            "ResumeProfile 与 source_artifact_id 的明确技术证据不一致："
            f"源简历包含 {expected}，但画像事实字段没有保留这些证据。请重新读取源 artifact 后再保存。"
        )

    missing_terms = sorted(source_terms - profile_terms)
    if len(source_terms) >= 3 and len(missing_terms) >= max(2, int(len(source_terms) * 0.6)):
        expected = ", ".join(sorted(source_terms))
        missing = ", ".join(missing_terms)
        raise ToolExecutionError(
            "ResumeProfile 丢失过多源简历中的明确技术证据："
            f"源简历包含 {expected}，画像缺失 {missing}。请以源 artifact 为准重新保存。"
        )


def _align_resume_profile_arguments_with_source(
    session_repository: SessionRepository,
    session_id: str,
    source_artifact_id: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    original_error: ToolExecutionError | None = None
    try:
        _validate_resume_profile_source_alignment(session_repository, session_id, source_artifact_id, args)
        return args
    except ToolExecutionError as exc:
        message = str(exc)
        if "明确技术证据" not in message and "丢失过多源简历" not in message:
            raise
        original_error = exc

    repaired = _resume_profile_arguments_from_source(session_repository, session_id, source_artifact_id, args)
    if repaired is None:
        if original_error is not None:
            raise original_error
        raise ToolExecutionError("ResumeProfile 与 source_artifact_id 的明确技术证据不一致。")
    _validate_resume_profile_source_alignment(session_repository, session_id, source_artifact_id, repaired)
    return repaired


def _resume_profile_arguments_from_source(
    session_repository: SessionRepository,
    session_id: str,
    source_artifact_id: str,
    args: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        source_text = session_repository.read_session_artifact_text(session_id, source_artifact_id)
    except Exception:
        return None
    source_terms = _extract_resume_source_terms(source_text)
    if len(source_terms) < 2:
        return None

    repaired = dict(args)
    repaired["basic_info"] = _source_resume_basic_info(source_text)
    repaired["education"] = _source_resume_section_items(source_text, ("教育", "教育背景"), field_name="description")
    repaired["work_experience"] = _source_resume_section_items(
        source_text,
        ("经历", "工作经历", "工作经验"),
        field_name="description",
    )
    repaired["project_experience"] = _source_resume_projects(source_text, source_terms)
    repaired["skills"] = _source_term_display_names(source_terms)
    repaired["certificates"] = _optional_list(args.get("certificates"), field_name="certificates")
    repaired["awards"] = _optional_list(args.get("awards"), field_name="awards")
    repaired["self_evaluation"] = ""
    return repaired


def _source_resume_basic_info(source_text: str) -> dict[str, Any]:
    output: dict[str, Any] = {}
    name = _source_labeled_value(source_text, ("候选人", "姓名", "name"))
    if name:
        output["name"] = name
    target = _source_labeled_value(source_text, ("目标方向", "求职意向", "目标岗位", "target"))
    if target:
        output["target_direction"] = target
    if not output:
        output["note"] = "源简历未提供可确定的基本信息字段。"
    return output


def _source_resume_section_items(
    source_text: str,
    labels: tuple[str, ...],
    *,
    field_name: str,
) -> list[dict[str, str]]:
    value = _source_labeled_value(source_text, labels)
    if not value:
        return []
    return [{field_name: value}]


def _source_resume_projects(source_text: str, source_terms: set[str]) -> list[dict[str, Any]]:
    value = _source_labeled_value(source_text, ("项目", "项目经历", "项目经验"))
    if not value:
        return []
    return [{"description": value, "technologies": _source_term_display_names(source_terms)}]


def _source_labeled_value(source_text: str, labels: tuple[str, ...]) -> str:
    normalized_labels = tuple(label.casefold() for label in labels)
    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for label, lowered_label in zip(labels, normalized_labels, strict=True):
            for separator in ("：", ":"):
                prefix = f"{label}{separator}"
                if line.startswith(prefix):
                    return line[len(prefix) :].strip()
                lowered_prefix = f"{lowered_label}{separator}"
                if line.casefold().startswith(lowered_prefix):
                    return line[len(lowered_prefix) :].strip()
    return ""


def _source_term_display_names(source_terms: set[str]) -> list[str]:
    return [
        _RESUME_SOURCE_TERM_DISPLAY_NAMES.get(term, term)
        for term in sorted(source_terms)
        if _RESUME_SOURCE_TERM_DISPLAY_NAMES.get(term, term).strip()
    ]


def _resume_profile_fact_text(args: dict[str, Any]) -> str:
    fact_payload = {
        "basic_info": args.get("basic_info"),
        "education": args.get("education"),
        "work_experience": args.get("work_experience"),
        "project_experience": args.get("project_experience"),
        "skills": args.get("skills"),
        "certificates": args.get("certificates"),
        "awards": args.get("awards"),
        "self_evaluation": args.get("self_evaluation"),
    }
    return json.dumps(fact_payload, ensure_ascii=False)


def _extract_resume_source_terms(text: str) -> set[str]:
    lowered = text.casefold()
    terms: set[str] = set()
    for canonical, aliases in _RESUME_SOURCE_TECH_TERMS.items():
        if any(alias.casefold() in lowered for alias in aliases):
            terms.add(canonical)
    return terms


def _required_dict(raw: Any, *, field_name: str) -> dict[str, Any]:
    if isinstance(raw, str):
        decoded = _decode_json_object_string(raw, field_name=field_name)
        raw = decoded
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict):
        raw = raw[0]
    if not isinstance(raw, dict):
        raise ToolExecutionError(f"'{field_name}' must be an object.")
    return dict(raw)


def _decode_json_object_string(raw: str, *, field_name: str) -> Any:
    text = raw.strip()
    if not text:
        raise ToolExecutionError(f"'{field_name}' must be an object.")
    candidates = [text]
    repaired = _repair_unclosed_json_containers(text)
    if repaired != text:
        candidates.append(repaired)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ToolExecutionError(f"'{field_name}' must be an object.")


def _repair_unclosed_json_containers(text: str) -> str:
    if not text.startswith("{"):
        return text
    output: list[str] = []
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        output.append(char)
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            stack.append("}")
            continue
        if char == "[":
            stack.append("]")
            continue
        if char not in {"]", "}"}:
            continue
        if stack and stack[-1] == char:
            stack.pop()
            continue
        while stack and stack[-1] != char:
            output.insert(len(output) - 1, stack.pop())
        if stack and stack[-1] == char:
            stack.pop()
    while stack:
        output.append(stack.pop())
    return "".join(output)


def _optional_dict(raw: Any, *, field_name: str, string_fallback_key: str | None = None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, str) and string_fallback_key is not None:
        try:
            return _required_dict(raw, field_name=field_name)
        except ToolExecutionError:
            text = raw.strip()
            return {string_fallback_key: text} if text else {}
    return _required_dict(raw, field_name=field_name)


def _normalize_career_profile_updates(raw: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for raw_key, value in raw.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ToolExecutionError("'updates' keys must be non-empty strings.")
        source_key = raw_key.strip()
        target_key = _CAREER_PROFILE_UPDATE_ALIASES.get(source_key, source_key)
        if target_key in _CAREER_PROFILE_IGNORED_UPDATE_FIELDS:
            continue
        if target_key not in _CAREER_PROFILE_ALLOWED_UPDATE_FIELDS:
            allowed = ", ".join(sorted(_CAREER_PROFILE_ALLOWED_UPDATE_FIELDS))
            raise ToolExecutionError(f"Unsupported CareerProfile merge field: {source_key}. Allowed fields: {allowed}")
        normalized_value = _normalize_career_profile_update_value(target_key, value)
        if target_key in normalized and target_key in _CAREER_PROFILE_LIST_UPDATE_FIELDS:
            existing = normalized[target_key]
            if isinstance(existing, list) and isinstance(normalized_value, list):
                normalized[target_key] = existing + normalized_value
                continue
        normalized[target_key] = normalized_value
    return normalized


def _normalize_career_profile_update_value(field_name: str, value: Any) -> Any:
    if field_name in _CAREER_PROFILE_LIST_UPDATE_FIELDS:
        return _optional_career_profile_string_list(value, field_name=field_name)
    if field_name in _CAREER_PROFILE_TEXT_UPDATE_FIELDS:
        return _optional_career_profile_text(value, field_name=field_name) or ""
    return value


def _optional_career_profile_string_list(raw: Any, *, field_name: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        normalized = raw.strip()
        return [normalized] if normalized else []
    if not isinstance(raw, list):
        raise ToolExecutionError(f"'{field_name}' must be a list of strings.")
    output: list[str] = []
    for item in raw:
        if item is None:
            continue
        if not isinstance(item, str):
            raise ToolExecutionError(f"each '{field_name}' item must be a string.")
        normalized = item.strip()
        if normalized:
            output.append(normalized)
    return output


def _optional_career_profile_text(raw: Any, *, field_name: str) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        normalized = raw.strip()
        return normalized or None
    if isinstance(raw, list):
        values = _optional_string_list(raw, field_name=field_name)
        return "；".join(values) or None
    raise ToolExecutionError(f"'{field_name}' must be a string or list of strings.")


def _optional_job_fit_recommendation(args: dict[str, Any]) -> str:
    label = _coerce_job_fit_recommendation(args.get("recommendation_label"))
    if label is not None:
        return label
    recommendation = _coerce_job_fit_recommendation(args.get("recommendation"))
    if recommendation is not None:
        return recommendation
    return "cautious"


def _coerce_job_fit_recommendation(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return _infer_job_fit_recommendation(" ".join(str(item) for item in raw))
    if not isinstance(raw, str):
        raise ToolExecutionError("'recommendation' must be a string.")
    normalized = raw.strip()
    if not normalized:
        return None
    lowered = normalized.casefold()
    if lowered in _JOB_FIT_RECOMMENDATIONS:
        return lowered
    compact = re.sub(r"[\s_\-:：/|]+", "", lowered)
    alias = _JOB_FIT_RECOMMENDATION_ALIASES.get(lowered) or _JOB_FIT_RECOMMENDATION_ALIASES.get(compact)
    if alias is not None:
        return alias
    if normalized.startswith("["):
        try:
            payload = json.loads(normalized)
        except ValueError:
            payload = None
        if isinstance(payload, list):
            return _infer_job_fit_recommendation(" ".join(str(item) for item in payload))
    return _infer_job_fit_recommendation(normalized)


def _infer_job_fit_recommendation(text: str) -> str | None:
    normalized = text.casefold()
    if _has_any_text(normalized, ("not_recommended", "not recommended", "不推荐", "不建议", "不建议投递")):
        return "not_recommended"
    if _has_any_text(normalized, ("cautious", "谨慎", "谨慎推荐", "谨慎投递")):
        return "cautious"
    if _has_any_text(normalized, ("recommended", "recommend", "推荐", "建议投递", "匹配度较高", "高度契合")):
        return "recommended"
    return None


def _has_any_text(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _optional_list(raw: Any, *, field_name: str) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    if not isinstance(raw, list):
        raise ToolExecutionError(f"'{field_name}' must be a list.")
    return list(raw)


def _required_string_list(raw: Any, *, field_name: str) -> list[str]:
    values = _optional_string_list(raw, field_name=field_name)
    if not values:
        raise ToolExecutionError(f"'{field_name}' must be a non-empty list.")
    return values


def _required_evidence_refs(raw: Any) -> list[str]:
    refs = _required_string_list(raw, field_name="evidence_refs")
    return _normalize_evidence_refs(refs)


def _optional_evidence_refs(raw: Any) -> list[str]:
    refs = _optional_string_list(raw, field_name="evidence_refs")
    return _normalize_evidence_refs(refs)


def _normalize_evidence_refs(refs: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        raw_ref = ref.strip().strip("`")
        if is_reserved_reference_value(raw_ref):
            continue
        normalized = _normalize_evidence_ref(ref)
        if is_reserved_reference_value(normalized):
            continue
        if normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output


def _normalize_evidence_ref(raw: str) -> str:
    value = raw.strip().strip("`")
    if value.startswith("job_fit_report_") or value.startswith("fit_report_"):
        return _normalize_prefixed_alias(value, "fit")
    separator = ":" if ":" in value else "=" if "=" in value else None
    if separator is None:
        return value
    raw_kind, raw_id = value.split(separator, 1)
    kind = _EVIDENCE_REF_TYPE_ALIASES.get(raw_kind.strip().lower())
    record_id = raw_id.strip().strip("`")
    if not record_id:
        return value
    if kind is None:
        return _normalize_labeled_evidence_ref(record_id) or value
    if kind == "artifact" and record_id.startswith("artifact_"):
        return record_id
    if kind == "application" and record_id.startswith("application_"):
        return record_id
    if kind == "career_profile" and record_id.startswith("career_profile_"):
        return record_id
    if kind == "fit" and record_id.startswith("fit_"):
        return record_id
    if kind == "fit" and (record_id.startswith("job_fit_report_") or record_id.startswith("fit_report_")):
        return _normalize_prefixed_alias(record_id, "fit")
    if kind == "jd" and record_id.startswith("jd_"):
        return record_id
    if kind == "resume_profile" and record_id.startswith("resume_profile_"):
        return record_id
    if kind == "resume_version" and record_id.startswith("resume_version_"):
        return record_id
    if kind == "sess" and record_id.startswith("sess_"):
        return record_id
    return value


def _normalize_labeled_evidence_ref(record_id: str) -> str | None:
    if record_id.startswith("artifact_"):
        return record_id
    if record_id.startswith("application_"):
        return record_id
    if record_id.startswith("career_profile_"):
        return record_id
    if record_id.startswith("fit_"):
        return record_id
    if record_id.startswith("job_fit_report_") or record_id.startswith("fit_report_"):
        return _normalize_prefixed_alias(record_id, "fit")
    if record_id.startswith("jd_"):
        return record_id
    if record_id.startswith("resume_profile_"):
        return record_id
    if record_id.startswith("resume_version_"):
        return record_id
    if record_id.startswith("sess_"):
        return record_id
    return None


def _normalize_prefixed_alias(value: str, prefix: str) -> str:
    marker = f"{prefix}_"
    stem = value[len(marker):] if value.startswith(marker) else value
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    return f"{marker}{slug[:100]}" if slug else value


def _optional_string_list(raw: Any, *, field_name: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    if not isinstance(raw, list):
        raise ToolExecutionError(f"'{field_name}' must be a list of strings.")
    output: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ToolExecutionError(f"each '{field_name}' item must be a non-empty string.")
        output.append(item.strip())
    return output


def _optional_score(raw: Any, *, field_name: str, default: int) -> int:
    if raw is None:
        return default
    return _normalize_score_value(raw, field_name=field_name)


def _optional_score_breakdown(raw: Any) -> dict[str, int]:
    if raw is None:
        return {}
    source = _required_dict(raw, field_name="score_breakdown")
    output: dict[str, int] = {}
    for raw_key, raw_score in source.items():
        key = _required_string(raw_key, field_name="score_breakdown key")
        output[key] = _normalize_score_value(raw_score, field_name=f"score_breakdown.{key}")
    return output


def _normalize_score_value(raw: Any, *, field_name: str) -> int:
    if isinstance(raw, bool):
        raise ToolExecutionError(f"'{field_name}' must be a score in range 0..100.")
    if isinstance(raw, int):
        score = raw
    elif isinstance(raw, float):
        score = int(round(raw * 100)) if 0 <= raw <= 1 else int(round(raw))
    elif isinstance(raw, str):
        normalized = raw.strip()
        match = re.fullmatch(r"(\d{1,3})(?:\s*/\s*100|%)?", normalized)
        if match is None:
            raise ToolExecutionError(f"'{field_name}' must be a score in range 0..100.")
        score = int(match.group(1))
    else:
        raise ToolExecutionError(f"'{field_name}' must be a score in range 0..100.")
    if score < 0 or score > 100:
        raise ToolExecutionError(f"'{field_name}' must be a score in range 0..100.")
    return score


_RESUME_VERSION_PLACEHOLDER_PATTERNS = (
    re.compile(r"占位", re.IGNORECASE),
    re.compile(r"替换为真实数据", re.IGNORECASE),
    re.compile(r"待填", re.IGNORECASE),
    re.compile(r"待补", re.IGNORECASE),
    re.compile(r"待完善", re.IGNORECASE),
    re.compile(r"\bTODO\b", re.IGNORECASE),
    re.compile(r"\bTBD\b", re.IGNORECASE),
)
_RESUME_VERSION_METRIC_PATTERNS = (
    re.compile(r"\d+(?:\.\d+)?\s*%"),
    re.compile(r"\d+(?:\.\d+)?\s*(?:ms|毫秒|秒|qps|tps|rps)", re.IGNORECASE),
    re.compile(r"\d+(?:\.\d+)?\s*(?:倍|x)", re.IGNORECASE),
    re.compile(r"\d+(?:\.\d+)?\s*[kK]\b"),
    re.compile(r"\d+(?:\.\d+)?\s*年"),
    re.compile(r"\d+\+?\s*(?:个|项)?\s*[\u4e00-\u9fffA-Za-z]{0,8}(?:算法|维度|连接|用户|客户|项目|接口|模块|服务)"),
    re.compile(r"(?:千|万|百万|千万|亿)级"),
)
_RESUME_VERSION_EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_RESUME_VERSION_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def _sanitize_resume_version_unverified_contacts(
    *,
    career_store: CareerProductStore,
    session_repository: SessionRepository,
    session_id: str,
    base_resume_profile_id: str,
    content: str,
    risk_notes: list[str],
) -> tuple[str, list[str], list[str]]:
    try:
        profile = career_store.get_resume_profile(base_resume_profile_id)
    except (StorageError, ValidationError):
        return content, risk_notes, []
    if profile is None or profile.source_session_id != session_id:
        return content, risk_notes, []
    source_text = _resume_profile_source_text(
        session_repository,
        session_id=session_id,
        profile=profile,
    )
    support_text = "\n".join((source_text, _resume_profile_supported_fact_text(profile)))
    unsupported_contacts = _unsupported_resume_version_contacts(content, support_text)
    if not unsupported_contacts:
        return content, risk_notes, []

    sanitized_content = _remove_unverified_contact_lines(content, unsupported_contacts)
    sanitized_risk_notes = list(risk_notes)
    _append_unique(
        sanitized_risk_notes,
        "已自动移除原始简历未证实的联系方式；如需展示手机号或邮箱，请先由用户补充确认。",
    )
    return sanitized_content, sanitized_risk_notes, unsupported_contacts


def _remove_unverified_contact_lines(content: str, unsupported_contacts: list[str]) -> str:
    output: list[str] = []
    for line in content.splitlines():
        if not any(contact in line for contact in unsupported_contacts):
            output.append(line)
            continue
        cleaned = line
        for contact in unsupported_contacts:
            cleaned = cleaned.replace(contact, "")
        cleaned = re.sub(r"(?i)\b(?:phone|mobile|tel|email|e-mail)\b\s*[:：]?", "", cleaned)
        cleaned = re.sub(r"(?:电话|手机|邮箱|邮件|联系方式)\s*[:：]?", "", cleaned)
        cleaned = re.sub(r"[\s|｜/、,，;；-]+", " ", cleaned).strip()
        if cleaned:
            output.append(cleaned)
    return "\n".join(output).strip() + "\n"


def _reject_invalid_resume_version_text(
    *,
    career_store: CareerProductStore,
    session_repository: SessionRepository,
    session_id: str,
    base_resume_profile_id: str,
    title: str,
    content: str | None,
    change_summary: list[str],
    keyword_strategy: list[str],
    risk_notes: list[str],
) -> None:
    issues = _resume_version_placeholder_issues(
        title=title,
        content=content,
        change_summary=change_summary,
        keyword_strategy=keyword_strategy,
        risk_notes=risk_notes,
    )
    if content:
        issues.extend(
            _resume_version_unverified_metric_issues(
                career_store=career_store,
                session_repository=session_repository,
                session_id=session_id,
                base_resume_profile_id=base_resume_profile_id,
                content=content,
            )
        )
        issues.extend(
            _resume_version_unsupported_candidate_fact_issues(
                career_store=career_store,
                session_repository=session_repository,
                session_id=session_id,
                base_resume_profile_id=base_resume_profile_id,
                content=content,
                change_summary=change_summary,
                keyword_strategy=keyword_strategy,
            )
        )
    if issues:
        raise ToolExecutionError("ResumeVersion validation failed: " + " ".join(issues))


def _safe_resume_version_fallback_after_validation_failure(
    *,
    career_store: CareerProductStore,
    session_repository: SessionRepository,
    context: RunContext,
    base_resume_profile_id: str,
    target_jd_analysis_id: str | None,
    title: str,
    risk_notes: list[str],
    allow_without_prior_failure: bool = False,
) -> dict[str, Any] | None:
    if (
        not allow_without_prior_failure
        and _current_run_resume_version_validation_failure_count(session_repository, context) < 1
    ):
        return None
    try:
        profile = career_store.get_resume_profile(base_resume_profile_id)
    except (StorageError, ValidationError):
        return None
    if profile is None or profile.source_session_id != context.session_id:
        return None
    source_text = _resume_profile_source_text(
        session_repository,
        session_id=context.session_id,
        profile=profile,
    )
    content = _build_conservative_resume_version_content(profile=profile, source_text=source_text, title=title)
    support_text = "\n".join((source_text, _resume_profile_supported_fact_text(profile)))
    keyword_strategy = _supported_resume_version_keywords(support_text)
    merged_risk_notes = list(risk_notes)
    _append_unique(merged_risk_notes, "已启用保守事实版本：未在原始简历或 ResumeProfile 中证实的联系方式、量化指标和技术关键词均未写入正文。")
    missing_jd_skills = _missing_jd_skills_for_resume_version(
        career_store,
        session_id=context.session_id,
        target_jd_analysis_id=target_jd_analysis_id,
        support_text=support_text,
    )
    if missing_jd_skills:
        _append_unique(merged_risk_notes, "以下 JD 关键词未在候选人事实中证实，需确认后再写入简历正文：" + "、".join(missing_jd_skills[:8]))
    return {
        "content": content,
        "change_summary": [
            "基于原始简历和 ResumeProfile 生成保守定制版本。",
            "移除未证实的联系方式、量化指标和 JD 技术关键词，避免候选人事实漂移。",
        ],
        "keyword_strategy": keyword_strategy,
        "risk_notes": merged_risk_notes,
    }


def _can_auto_fallback_resume_version_validation_error(message: str) -> bool:
    return "unsupported candidate tech facts" in message


def _current_run_resume_version_validation_failure_count(
    session_repository: SessionRepository,
    context: RunContext,
) -> int:
    try:
        events = session_repository.list_run_events(context.session_id, context.agent_id, context.run_id)
    except (StorageError, ValidationError):
        return 0
    count = 0
    for event in events:
        if event.type != "tool_result":
            continue
        payload = event.payload
        if payload.get("tool_name") != "career_resume_version_create" or payload.get("success") is not False:
            continue
        content = payload.get("content")
        if isinstance(content, str) and "ResumeVersion validation failed" in content:
            count += 1
    return count


def _build_conservative_resume_version_content(*, profile: ResumeProfile, source_text: str, title: str) -> str:
    _ = title
    name = _resume_profile_display_name(profile) or "候选人"
    lines = [
        f"# {name}",
        "",
        "> 保守事实定制版本",
        "",
        "## 已证实简历事实",
        "",
    ]
    fact_lines = [line.strip() for line in source_text.splitlines() if line.strip()]
    if fact_lines:
        lines.extend(f"- {line}" for line in fact_lines)
    else:
        lines.extend(_profile_fact_bullets(profile))
    lines.extend(
        [
            "",
            "## 定制说明",
            "",
            "- 本版本仅重组和突出已证实的简历事实。",
            "- 未在候选人事实中出现的 JD 技术关键词不写入正文，可在后续确认后补充。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _resume_profile_display_name(profile: ResumeProfile) -> str:
    for key in ("name", "姓名", "candidate_name"):
        value = profile.basic_info.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _profile_fact_bullets(profile: ResumeProfile) -> list[str]:
    sections = {
        "基本信息": profile.basic_info,
        "教育背景": profile.education,
        "工作经历": profile.work_experience,
        "项目经历": profile.project_experience,
        "技能": profile.skills,
        "证书": profile.certificates,
        "奖项": profile.awards,
        "自我评价": profile.self_evaluation,
    }
    bullets: list[str] = []
    for label, value in sections.items():
        text = _compact_fact_value(value)
        if text:
            bullets.append(f"{label}：{text}")
    return bullets or ["暂无可展开的结构化事实，请回到原始简历补充信息。"]


def _compact_fact_value(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _supported_resume_version_keywords(support_text: str) -> list[str]:
    display_names = {
        "agent": "Agent",
        "celery": "Celery",
        "docker": "Docker",
        "elasticsearch": "Elasticsearch",
        "faiss": "FAISS",
        "fastapi": "FastAPI",
        "java": "Java",
        "kubernetes": "Kubernetes",
        "langchain": "LangChain",
        "langgraph": "LangGraph",
        "milvus": "Milvus",
        "mysql": "MySQL",
        "llm_api": "LLM API",
        "postgresql": "PostgreSQL",
        "python": "Python",
        "pytorch": "PyTorch",
        "rag": "RAG",
        "react": "React",
        "redis": "Redis",
        "spring": "Spring",
        "tensorflow": "TensorFlow",
        "vector_search": "向量检索",
        "vue": "Vue",
        "websocket": "WebSocket",
    }
    normalized_support = _normalize_fact_text(support_text)
    output: list[str] = []
    for canonical, aliases in _RESUME_SOURCE_TECH_TERMS.items():
        if canonical not in display_names:
            continue
        if _first_present_alias(normalized_support, aliases) is not None:
            output.append(display_names[canonical])
    return output[:12]


def _missing_jd_skills_for_resume_version(
    career_store: CareerProductStore,
    *,
    session_id: str,
    target_jd_analysis_id: str | None,
    support_text: str,
) -> list[str]:
    if target_jd_analysis_id is None:
        return []
    try:
        jd_analysis = career_store.get_jd_analysis(target_jd_analysis_id)
    except (StorageError, ValidationError):
        return []
    if jd_analysis is None or jd_analysis.source_session_id != session_id:
        return []
    normalized_support = _normalize_fact_text(support_text)
    missing: list[str] = []
    for skill in jd_analysis.required_skills:
        if _normalize_fact_text(skill) not in normalized_support:
            _append_unique(missing, skill)
    return missing


def _resume_version_placeholder_issues(
    *,
    title: str,
    content: str | None,
    change_summary: list[str],
    keyword_strategy: list[str],
    risk_notes: list[str],
) -> list[str]:
    fields = {
        "title": title,
        "content": content or "",
        "change_summary": "\n".join(change_summary),
        "keyword_strategy": "\n".join(keyword_strategy),
        "risk_notes": "\n".join(risk_notes),
    }
    issues: list[str] = []
    for field_name, text in fields.items():
        matched_terms = _matched_placeholder_terms(text)
        if matched_terms:
            issues.append(
                f"ResumeVersion {field_name} contains forbidden placeholder or replacement wording. "
                f"Matched: {', '.join(matched_terms[:4])}. "
                "Remove that wording from the resume body; describe missing facts only in risk_notes."
            )
    return issues


def _matched_placeholder_terms(text: str) -> list[str]:
    output: list[str] = []
    for pattern in _RESUME_VERSION_PLACEHOLDER_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        term = match.group(0)
        if term not in output:
            output.append(term)
    return output


def _sanitize_resume_version_metadata_placeholders(
    *,
    change_summary: list[str],
    keyword_strategy: list[str],
    risk_notes: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Normalize non-body metadata so wording advice does not fail resume creation.

    Placeholder terms inside the resume title/body are still hard failures. Metadata
    fields are product annotations, so the tool should store neutral wording instead
    of forcing the model into a retry when it says things like "avoid placeholder text".
    """

    return (
        _sanitize_resume_version_metadata_list(change_summary),
        _sanitize_resume_version_keyword_strategy(keyword_strategy),
        _sanitize_resume_version_metadata_list(risk_notes),
    )


def _sanitize_resume_version_metadata_list(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        sanitized = _sanitize_resume_version_metadata_text(value)
        if not sanitized or sanitized in seen:
            continue
        output.append(sanitized)
        seen.add(sanitized)
    return output


def _sanitize_resume_version_keyword_strategy(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if _matched_placeholder_terms(value):
            continue
        sanitized = _sanitize_resume_version_metadata_text(value)
        if not sanitized or sanitized in seen:
            continue
        output.append(sanitized)
        seen.add(sanitized)
    return output


def _sanitize_resume_version_metadata_text(value: str) -> str:
    sanitized = value.strip()
    replacements = (
        ("替换为真实数据", "补充真实数据"),
        ("待补充", "需要补充"),
        ("待补", "需要补充"),
        ("待填写", "需要填写"),
        ("待填", "需要填写"),
        ("待完善", "需要完善"),
        ("占位表达", "未确认内容"),
        ("占位", "未确认内容"),
        ("TODO", "需要处理"),
        ("TBD", "需要确认"),
    )
    for source, target in replacements:
        sanitized = re.sub(re.escape(source), target, sanitized, flags=re.IGNORECASE)
    return sanitized.strip()


def _resume_version_unverified_metric_issues(
    *,
    career_store: CareerProductStore,
    session_repository: SessionRepository,
    session_id: str,
    base_resume_profile_id: str,
    content: str,
) -> list[str]:
    try:
        profile = career_store.get_resume_profile(base_resume_profile_id)
    except (StorageError, ValidationError):
        return []
    if profile is None or profile.source_session_id != session_id:
        return []
    source_text = _resume_profile_source_text(
        session_repository,
        session_id=session_id,
        profile=profile,
    )
    if not source_text.strip():
        return []
    source_metric_text = _normalize_metric_text(source_text)
    unverified: list[str] = []
    for metric in _extract_resume_version_metrics(content):
        if _normalize_metric_text(metric) not in source_metric_text:
            unverified.append(metric)
    if not unverified:
        return []
    return [
        "ResumeVersion content contains unverified quantitative metrics not present in the base resume artifact: "
        + ", ".join(unverified[:8])
        + ". Retry career_resume_version_create immediately with those metrics removed; do not add unsupported "
        "evidence_refs and do not call more get/list/read tools unless a required id is missing."
    ]


def _resume_version_unsupported_candidate_fact_issues(
    *,
    career_store: CareerProductStore,
    session_repository: SessionRepository,
    session_id: str,
    base_resume_profile_id: str,
    content: str,
    change_summary: list[str],
    keyword_strategy: list[str],
) -> list[str]:
    try:
        profile = career_store.get_resume_profile(base_resume_profile_id)
    except (StorageError, ValidationError):
        return []
    if profile is None or profile.source_session_id != session_id:
        return []
    source_text = _resume_profile_source_text(
        session_repository,
        session_id=session_id,
        profile=profile,
    )
    support_text = "\n".join((source_text, _resume_profile_supported_fact_text(profile)))
    if not support_text.strip():
        return []

    unsupported_contacts = _unsupported_resume_version_contacts(content, support_text)
    candidate_claim_text = "\n".join((content, "\n".join(change_summary), "\n".join(keyword_strategy)))
    unsupported_terms = _unsupported_resume_version_tech_terms(candidate_claim_text, support_text)
    issues: list[str] = []
    if unsupported_contacts:
        issues.append(
            "ResumeVersion content contains contact or salary-like candidate facts absent from the base resume: "
            + ", ".join(unsupported_contacts[:8])
            + ". Remove fabricated contact/salary fields instead of filling demo values."
        )
    if unsupported_terms:
        issues.append(
            "ResumeVersion content/change_summary/keyword_strategy contains unsupported candidate tech facts: "
            + ", ".join(unsupported_terms[:10])
            + ". Only write technologies present in the base resume or saved ResumeProfile; move missing JD keywords "
            "to risk_notes or next_actions."
        )
    return issues


def _resume_profile_supported_fact_text(profile: ResumeProfile) -> str:
    payload = {
        "basic_info": profile.basic_info,
        "education": profile.education,
        "work_experience": profile.work_experience,
        "project_experience": profile.project_experience,
        "skills": profile.skills,
        "certificates": profile.certificates,
        "awards": profile.awards,
        "self_evaluation": profile.self_evaluation,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _unsupported_resume_version_contacts(content: str, support_text: str) -> list[str]:
    normalized_support = _normalize_fact_text(support_text)
    unsupported: list[str] = []
    for email in _RESUME_VERSION_EMAIL_PATTERN.findall(content):
        if _normalize_fact_text(email) not in normalized_support:
            _append_unique(unsupported, email)
    for phone in _RESUME_VERSION_PHONE_PATTERN.findall(content):
        if _normalize_fact_text(phone) not in normalized_support:
            _append_unique(unsupported, phone)
    return unsupported


def _unsupported_resume_version_tech_terms(candidate_claim_text: str, support_text: str) -> list[str]:
    normalized_claim = _normalize_fact_text(candidate_claim_text)
    normalized_support = _normalize_fact_text(support_text)
    unsupported: list[str] = []
    for canonical, aliases in _RESUME_SOURCE_TECH_TERMS.items():
        claim_alias = _first_present_alias(normalized_claim, aliases)
        if claim_alias is None:
            continue
        if _first_present_alias(normalized_support, aliases) is None:
            _append_unique(unsupported, canonical)
    return unsupported


def _first_present_alias(normalized_text: str, aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        normalized_alias = _normalize_fact_text(alias)
        if normalized_alias and normalized_alias in normalized_text:
            return alias
    return None


def _normalize_fact_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _append_unique(output: list[str], value: str) -> None:
    if value not in output:
        output.append(value)


def _resume_profile_source_text(
    session_repository: SessionRepository,
    *,
    session_id: str,
    profile: ResumeProfile,
) -> str:
    artifact_ids = [
        artifact_id
        for artifact_id in (profile.source_artifact_id, profile.raw_text_artifact_id)
        if isinstance(artifact_id, str) and artifact_id.strip()
    ]
    texts: list[str] = []
    seen: set[str] = set()
    for artifact_id in artifact_ids:
        if artifact_id in seen:
            continue
        seen.add(artifact_id)
        text = _read_current_artifact_text_or_empty(session_repository, session_id, artifact_id)
        if text:
            texts.append(text)
    return "\n".join(texts)


def _read_current_artifact_text_or_empty(
    session_repository: SessionRepository,
    session_id: str,
    artifact_id: str,
) -> str:
    try:
        _require_current_artifact(
            session_repository,
            session_id,
            artifact_id,
            field_name="artifact_id",
        )
        return session_repository.read_session_artifact_text(session_id, artifact_id)
    except (StorageError, ToolExecutionError, ValidationError):
        return ""


def _extract_resume_version_metrics(content: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for pattern in _RESUME_VERSION_METRIC_PATTERNS:
        for match in pattern.finditer(content):
            metric = match.group(0).strip()
            key = _normalize_metric_text(metric)
            if not key or key in seen:
                continue
            output.append(metric)
            seen.add(key)
    return output


def _normalize_metric_text(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _optional_bool(raw: Any) -> bool:
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise ToolExecutionError("'include_archived' must be a boolean.")
    return raw


def _optional_bool_field(raw: Any, *, field_name: str) -> bool:
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise ToolExecutionError(f"'{field_name}' must be a boolean.")
    return raw


def _single_current_session_record(records: list[Any], session_id: str) -> Any | None:
    matches = [record for record in records if getattr(record, "source_session_id", None) == session_id]
    if len(matches) == 1:
        return matches[0]
    return None


def _get_record_or_current_session_single(
    requested_record_id: str,
    *,
    session_id: str,
    records: list[Any],
    getter: Callable[[str], Any | None],
) -> tuple[Any | None, dict[str, Any]]:
    try:
        record = getter(requested_record_id)
    except ValidationError:
        record = None
        invalid_id_format = True
    else:
        invalid_id_format = False
    if record is not None:
        return record, {}
    extra: dict[str, Any] = {"requested_record_id": requested_record_id}
    if invalid_id_format:
        extra["invalid_id_format"] = True
    fallback = _single_current_session_record(records, session_id)
    if fallback is None:
        extra["hint"] = "Call the corresponding list tool to get a valid current-session record id."
        return None, extra
    if invalid_id_format:
        extra["resolved_from_invalid_id"] = True
    else:
        extra["resolved_from_missing_id"] = True
    return fallback, extra


def _current_session_record_by_id(
    getter: Callable[[str], Any | None],
    record_id: str,
    session_id: str,
) -> Any | None:
    try:
        record = getter(record_id)
    except (StorageError, ValidationError):
        return None
    if record is None or getattr(record, "source_session_id", None) != session_id:
        return None
    return record


def _repair_missing_current_session_record_id(
    record_id: str,
    *,
    session_id: str,
    records: list[Any],
    getter: Callable[[str], Any | None],
    id_attr: str,
) -> str:
    if _current_session_record_by_id(getter, record_id, session_id) is not None:
        return record_id
    fallback = _single_current_session_record(records, session_id)
    if fallback is None:
        return record_id
    repaired = getattr(fallback, id_attr, None)
    return repaired if isinstance(repaired, str) and repaired.strip() else record_id


def _infer_single_current_fit_report(
    career_store: CareerProductStore,
    *,
    session_id: str,
    source_artifact_id: str | None,
    jd_analysis_id: str | None,
    resume_profile_id: str | None,
) -> JobFitReport | None:
    fit_report = _single_current_session_record(career_store.list_job_fit_reports(), session_id)
    if fit_report is None:
        return None
    if not isinstance(fit_report, JobFitReport):
        return None
    if source_artifact_id is not None and fit_report.source_artifact_id != source_artifact_id:
        return None
    if jd_analysis_id is not None and fit_report.jd_analysis_id != jd_analysis_id:
        return None
    if resume_profile_id is not None and fit_report.resume_profile_id != resume_profile_id:
        return None
    return fit_report


def _remove_non_current_prefixed_refs(
    refs: list[str],
    *,
    prefix: str,
    valid_ids: set[str],
) -> list[str]:
    return [ref for ref in refs if not ref.startswith(prefix) or ref in valid_ids]


def _existing_current_session_resume_version_ids(
    career_store: CareerProductStore,
    *,
    session_id: str,
    resume_version_ids: list[str],
) -> list[str]:
    valid_ids = {
        item.resume_version_id
        for item in career_store.list_resume_versions()
        if item.source_session_id == session_id and item.status == CareerRecordStatus.ACTIVE
    }
    return [item for item in resume_version_ids if item in valid_ids]


def _find_current_session_record(records: list[Any], session_id: str, predicate: Callable[[Any], bool]) -> Any | None:
    for record in records:
        if getattr(record, "source_session_id", None) == session_id and predicate(record):
            return record
    return None


def _create_generated_markdown_artifact(
    session_repository: SessionRepository,
    context: RunContext,
    *,
    title: str,
    content: str,
) -> str:
    artifact_id = _new_id("artifact")
    root = session_repository.get_session_root_path(context.session_id).resolve()
    artifact_dir = root / "artifacts" / artifact_id
    original_path = artifact_dir / "original.bin"
    text_path = artifact_dir / "content.txt"
    try:
        artifact_dir.mkdir(parents=True, exist_ok=False)
        original_path.write_text(content, encoding="utf-8")
        text_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ToolExecutionError(f"Failed to create resume version artifact: {exc}") from exc
    now = _now()
    artifact = SessionArtifact(
        artifact_id=artifact_id,
        session_id=context.session_id,
        kind="generated_file",
        title=title,
        media_type="text/markdown",
        size_bytes=original_path.stat().st_size,
        status="ready",
        visibility="session_shared",
        storage_relpath=str(original_path.relative_to(root)),
        text_relpath=str(text_path.relative_to(root)),
        owner_agent_id=context.agent_id,
        description="Generated markdown resume version",
        source_type="tool_career_resume_version_create",
        source_event_id=None,
        error=None,
        text_char_count=len(content),
        token_estimate=max(1, (len(content) + 3) // 4),
        parsed_at=now,
        created_at=now,
        updated_at=now,
    )
    session_repository.add_or_update_session_artifact(artifact)
    return artifact_id


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _new_application_id(*, company: str, position: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{company}_{position}").strip("_").lower()
    if slug:
        return f"application_{slug[:80]}_{uuid4().hex[:8]}"
    return _new_id("application")


def _now() -> datetime:
    return app_now()


def _record_result(
    tool_name: str,
    record_type: str,
    record_id: str,
    record: ResumeProfile | CareerProfile | JDAnalysis | JobFitReport | ResumeVersion | CareerApplication,
    *,
    extra: dict[str, Any] | None = None,
) -> ToolExecutionResult:
    payload = {
        "record_type": record_type,
        "record_id": record_id,
        "found": True,
        "status": record.status.value,
        "source_session_id": record.source_session_id,
        "source_artifact_id": record.source_artifact_id,
        "evidence_refs": record.evidence_refs,
        "created_at": _to_iso(record.created_at),
        "updated_at": _to_iso(record.updated_at),
        "record": _record_to_payload(record),
    }
    if extra:
        payload.update(extra)
    return ToolExecutionResult(tool_name=tool_name, success=True, content=json.dumps(payload, ensure_ascii=False))


def _not_found_result(
    tool_name: str,
    record_type: str,
    record_id: str,
    *,
    extra: dict[str, Any] | None = None,
) -> ToolExecutionResult:
    payload = {
        "record_type": record_type,
        "record_id": record_id,
        "found": False,
        "message": f"{record_type} not found: {record_id}",
    }
    if extra:
        payload.update(extra)
    return ToolExecutionResult(tool_name=tool_name, success=True, content=json.dumps(payload, ensure_ascii=False))


def _list_result(
    tool_name: str,
    record_type: str,
    records: (
        list[ResumeProfile]
        | list[CareerProfile]
        | list[JDAnalysis]
        | list[JobFitReport]
        | list[ResumeVersion]
        | list[CareerApplication]
    ),
) -> ToolExecutionResult:
    payload = {
        "record_type": record_type,
        "records": [_record_to_payload(record) for record in records],
    }
    return ToolExecutionResult(tool_name=tool_name, success=True, content=json.dumps(payload, ensure_ascii=False))


def _record_to_payload(
    record: ResumeProfile | CareerProfile | JDAnalysis | JobFitReport | ResumeVersion | CareerApplication,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": record.status.value,
        "source_session_id": record.source_session_id,
        "source_artifact_id": record.source_artifact_id,
        "evidence_refs": record.evidence_refs,
        "created_at": _to_iso(record.created_at),
        "updated_at": _to_iso(record.updated_at),
    }
    if isinstance(record, ResumeProfile):
        base.update(
            {
                "resume_profile_id": record.resume_profile_id,
                "basic_info": record.basic_info,
                "education": record.education,
                "work_experience": record.work_experience,
                "project_experience": record.project_experience,
                "skills": record.skills,
                "certificates": record.certificates,
                "awards": record.awards,
                "self_evaluation": record.self_evaluation,
                "raw_text_artifact_id": record.raw_text_artifact_id,
                "diagnosis_artifact_id": record.diagnosis_artifact_id,
                "diagnosis": record.diagnosis,
            }
        )
        return base
    if isinstance(record, CareerProfile):
        base.update(
            {
                "career_profile_id": record.career_profile_id,
                "career_goal": record.career_goal,
                "target_roles": record.target_roles,
                "preferred_industries": record.preferred_industries,
                "preferred_cities": record.preferred_cities,
                "strengths": record.strengths,
                "weaknesses": record.weaknesses,
                "skills": record.skills,
                "interests": record.interests,
                "education_summary": record.education_summary,
                "experience_summary": record.experience_summary,
                "resume_issues": record.resume_issues,
                "interview_weaknesses": record.interview_weaknesses,
            }
        )
        return base
    if isinstance(record, JDAnalysis):
        base.update(
            {
                "jd_analysis_id": record.jd_analysis_id,
                "company": record.company,
                "position": record.position,
                "seniority": record.seniority,
                "required_skills": record.required_skills,
                "preferred_skills": record.preferred_skills,
                "responsibilities": record.responsibilities,
                "keywords": record.keywords,
                "risk_signals": record.risk_signals,
                "interview_focus": record.interview_focus,
            }
        )
        return base
    if isinstance(record, JobFitReport):
        base.update(
            {
                "job_fit_report_id": record.job_fit_report_id,
                "jd_analysis_id": record.jd_analysis_id,
                "resume_profile_id": record.resume_profile_id,
                "career_profile_id": record.career_profile_id,
                "overall_score": record.overall_score,
                "score_breakdown": record.score_breakdown,
                "matched_evidence": record.matched_evidence,
                "gaps": record.gaps,
                "resume_optimization_direction": record.resume_optimization_direction,
                "interview_preparation_focus": record.interview_preparation_focus,
                "recommendation": record.recommendation,
                "report_artifact_id": record.report_artifact_id,
            }
        )
        return base
    if isinstance(record, ResumeVersion):
        base.update(
            {
                "resume_version_id": record.resume_version_id,
                "base_resume_profile_id": record.base_resume_profile_id,
                "target_jd_analysis_id": record.target_jd_analysis_id,
                "title": record.title,
                "format": record.format,
                "artifact_id": record.artifact_id,
                "change_summary": record.change_summary,
                "keyword_strategy": record.keyword_strategy,
                "risk_notes": record.risk_notes,
            }
        )
        return base
    base.update(
        {
            "application_id": record.application_id,
            "company": record.company,
            "position": record.position,
            "location": record.location,
            "job_url": record.job_url,
            "stage": record.stage,
            "priority": record.priority,
            "resume_profile_id": record.resume_profile_id,
            "career_profile_id": record.career_profile_id,
            "jd_analysis_id": record.jd_analysis_id,
            "job_fit_report_id": record.job_fit_report_id,
            "resume_version_ids": record.resume_version_ids,
            "summary": record.summary,
            "next_actions": record.next_actions,
            "risks": record.risks,
            "notes": record.notes,
        }
    )
    return base


def _to_iso(value: datetime) -> str:
    return to_app_iso(value)
