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
    "resume_profile_id",
    "summary",
    "work_experience_years",
}
_EVIDENCE_REF_TYPE_ALIASES = {
    "artifact": "artifact",
    "artifact_id": "artifact",
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
                return _record_result(
                    "career_resume_profile_save",
                    "resume_profile",
                    existing.resume_profile_id,
                    existing,
                    extra={"idempotent_reused": True},
                )
            record = ResumeProfile(
                resume_profile_id=_optional_prefixed_id(args.get("resume_profile_id"), "resume_profile")
                or _new_id("resume_profile"),
                status=CareerRecordStatus.ACTIVE,
                source_session_id=run_context.session_id,
                source_artifact_id=source_artifact_id,
                evidence_refs=_required_evidence_refs(args.get("evidence_refs")),
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
                diagnosis=_optional_dict(args.get("diagnosis"), field_name="diagnosis"),
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
            args = _require_arguments(arguments)
            record_id = _optional_string(args.get("career_profile_id")) or _DEFAULT_CAREER_PROFILE_ID
            source_artifact_id = _optional_current_artifact(
                self._session_repository,
                run_context.session_id,
                args.get("source_artifact_id"),
                field_name="source_artifact_id",
            )
            evidence_refs = _required_evidence_refs(args.get("evidence_refs"))
            updates = _normalize_career_profile_updates(_required_dict(args.get("updates"), field_name="updates"))
            current = self._career_store.get_career_profile(record_id)
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
                evidence_refs=_required_evidence_refs(args.get("evidence_refs")),
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
                    "career_profile_id": {"type": "string"},
                    "overall_score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "score_breakdown": {
                        "type": "object",
                        "additionalProperties": {"type": "integer", "minimum": 0, "maximum": 100},
                    },
                    "matched_evidence": {"type": "array"},
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
                    "evidence_refs",
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
            source_artifact_id = _required_current_artifact(
                self._session_repository,
                run_context.session_id,
                args,
                "source_artifact_id",
            )
            report_artifact_id = _required_current_artifact(
                self._session_repository,
                run_context.session_id,
                args,
                "report_artifact_id",
            )
            jd_analysis_id = _required_string(args.get("jd_analysis_id"), field_name="jd_analysis_id")
            resume_profile_id = _required_string(args.get("resume_profile_id"), field_name="resume_profile_id")
            career_profile_id = _required_string(args.get("career_profile_id"), field_name="career_profile_id")
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
            record = JobFitReport(
                job_fit_report_id=_optional_prefixed_id(args.get("job_fit_report_id"), "fit") or _new_id("fit"),
                status=CareerRecordStatus.ACTIVE,
                source_session_id=run_context.session_id,
                source_artifact_id=source_artifact_id,
                evidence_refs=_required_evidence_refs(args.get("evidence_refs")),
                created_at=_now(),
                updated_at=_now(),
                jd_analysis_id=jd_analysis_id,
                resume_profile_id=resume_profile_id,
                career_profile_id=career_profile_id,
                overall_score=_optional_score(args.get("overall_score"), field_name="overall_score", default=0),
                score_breakdown=_optional_score_breakdown(args.get("score_breakdown")),
                matched_evidence=_optional_list(args.get("matched_evidence"), field_name="matched_evidence"),
                gaps=_optional_list(args.get("gaps"), field_name="gaps"),
                resume_optimization_direction=_optional_list(
                    args.get("resume_optimization_direction"),
                    field_name="resume_optimization_direction",
                ),
                interview_preparation_focus=_optional_list(
                    args.get("interview_preparation_focus"),
                    field_name="interview_preparation_focus",
                ),
                recommendation=_optional_string(args.get("recommendation")) or "cautious",
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
            description="Create a markdown resume version product record from a generated artifact.",
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
                        "description": "Markdown resume content. When artifact_id is omitted, the tool creates a generated_file artifact.",
                    },
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "change_summary": {"type": "array", "items": {"type": "string"}},
                    "keyword_strategy": {"type": "array", "items": {"type": "string"}},
                    "risk_notes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["base_resume_profile_id", "title", "evidence_refs"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            evidence_refs = _required_evidence_refs(args.get("evidence_refs"))
            base_resume_profile_id = _resolve_resume_version_base_profile_id(args, evidence_refs)
            target_jd_analysis_id = _optional_prefixed_id(args.get("target_jd_analysis_id"), "jd")
            title = _required_string(args.get("title"), field_name="title")
            raw_artifact_id = args.get("artifact_id")
            if raw_artifact_id is None:
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
                    content=_required_string(args.get("content"), field_name="content"),
                )
            else:
                artifact_id = _require_current_artifact(
                    self._session_repository,
                    run_context.session_id,
                    _required_string(raw_artifact_id, field_name="artifact_id"),
                    field_name="artifact_id",
                )
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
                change_summary=_optional_string_list(args.get("change_summary"), field_name="change_summary"),
                keyword_strategy=_optional_string_list(args.get("keyword_strategy"), field_name="keyword_strategy"),
                risk_notes=_optional_string_list(args.get("risk_notes"), field_name="risk_notes"),
            )
            saved = self._career_store.save_resume_version(record)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("career_resume_version_create", "resume_version", saved.resume_version_id, saved)


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
            args = _require_arguments(arguments)
            evidence_refs = _required_evidence_refs(args.get("evidence_refs"))
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

            fit_record = self._career_store.get_job_fit_report(job_fit_report_id) if job_fit_report_id else None
            if fit_record is not None:
                jd_analysis_id = jd_analysis_id or fit_record.jd_analysis_id
                resume_profile_id = resume_profile_id or fit_record.resume_profile_id
                career_profile_id = career_profile_id or fit_record.career_profile_id
                source_artifact_id = source_artifact_id or fit_record.source_artifact_id
                evidence_refs = _append_evidence_refs(
                    evidence_refs,
                    fit_record.job_fit_report_id,
                    fit_record.jd_analysis_id,
                    fit_record.resume_profile_id,
                    fit_record.career_profile_id,
                    fit_record.source_artifact_id,
                    fit_record.report_artifact_id,
                )

            jd_record = self._career_store.get_jd_analysis(jd_analysis_id) if jd_analysis_id else None
            if jd_record is not None:
                source_artifact_id = source_artifact_id or jd_record.source_artifact_id
                evidence_refs = _append_evidence_refs(
                    evidence_refs,
                    jd_record.jd_analysis_id,
                    jd_record.source_artifact_id,
                )

            company = _optional_string(args.get("company")) or (jd_record.company if jd_record is not None else "")
            position = _optional_string(args.get("position")) or (jd_record.position if jd_record is not None else "")
            evidence_refs = _append_evidence_refs(
                evidence_refs,
                source_artifact_id,
                resume_profile_id,
                career_profile_id,
                jd_analysis_id,
                job_fit_report_id,
                *resume_version_ids,
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
                location=_optional_string(args.get("location")) or "",
                job_url=_optional_string(args.get("job_url")) or "",
                stage=_optional_string(args.get("stage")) or "draft",
                priority=_optional_string(args.get("priority")) or "medium",
                resume_profile_id=resume_profile_id,
                career_profile_id=career_profile_id,
                jd_analysis_id=jd_analysis_id,
                job_fit_report_id=job_fit_report_id,
                resume_version_ids=resume_version_ids,
                summary=_optional_string(args.get("summary")) or "",
                next_actions=_optional_string_list(args.get("next_actions"), field_name="next_actions"),
                risks=_optional_string_list(args.get("risks"), field_name="risks"),
                notes=_optional_string(args.get("notes")) or "",
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
            args = _require_arguments(arguments)
            record_id = _required_string(args.get("application_id"), field_name="application_id")
            source_artifact_id = _optional_current_artifact(
                self._session_repository,
                run_context.session_id,
                args.get("source_artifact_id"),
                field_name="source_artifact_id",
            )
            record = self._career_store.merge_career_application(
                record_id,
                updates=_required_dict(args.get("updates"), field_name="updates"),
                evidence_refs=_required_evidence_refs(args.get("evidence_refs")),
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
    if raw is None:
        return None
    return _require_current_artifact(
        session_repository,
        session_id,
        _required_string(raw, field_name=field_name),
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


def _optional_prefixed_id(raw: Any, prefix: str) -> str | None:
    value = _optional_string(raw)
    if value is None:
        return None
    marker = f"{prefix}_"
    stem = value[len(marker):] if value.startswith(marker) else value
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    if not slug:
        return None
    return f"{marker}{slug[:100]}"


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


def _optional_prefixed_id_list(raw: Any, *, prefix: str, field_name: str) -> list[str]:
    values = _optional_string_list(raw, field_name=field_name)
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _optional_prefixed_id(value, prefix)
        if normalized is None:
            raise ToolExecutionError(f"each '{field_name}' item must be a valid {prefix}_ id.")
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


def _required_dict(raw: Any, *, field_name: str) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolExecutionError(f"'{field_name}' must be an object.") from exc
        raw = decoded
    if not isinstance(raw, dict):
        raise ToolExecutionError(f"'{field_name}' must be an object.")
    return dict(raw)


def _optional_dict(raw: Any, *, field_name: str) -> dict[str, Any]:
    if raw is None:
        return {}
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
    if field_name in _CAREER_PROFILE_LIST_UPDATE_FIELDS and isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    return value


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
    output: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        normalized = _normalize_evidence_ref(ref)
        if normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output


def _normalize_evidence_ref(raw: str) -> str:
    value = raw.strip().strip("`")
    if ":" not in value:
        return value
    raw_kind, raw_id = value.split(":", 1)
    kind = _EVIDENCE_REF_TYPE_ALIASES.get(raw_kind.strip().lower())
    record_id = raw_id.strip().strip("`")
    if kind is None or not record_id:
        return value
    if kind == "artifact" and record_id.startswith("artifact_"):
        return record_id
    if kind == "application" and record_id.startswith("application_"):
        return record_id
    if kind == "career_profile" and record_id.startswith("career_profile_"):
        return record_id
    if kind == "fit" and record_id.startswith("fit_"):
        return record_id
    if kind == "jd" and record_id.startswith("jd_"):
        return record_id
    if kind == "resume_profile" and record_id.startswith("resume_profile_"):
        return record_id
    if kind == "resume_version" and record_id.startswith("resume_version_"):
        return record_id
    if kind == "sess" and record_id.startswith("sess_"):
        return record_id
    return value


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


def _optional_bool(raw: Any) -> bool:
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise ToolExecutionError("'include_archived' must be a boolean.")
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
