"""Quality gates for products created by LangGraph-owned child tasks."""

from __future__ import annotations

from app.career.store import CareerProductStore
from app.domain.protocols import SessionRepository
from app.services.agent_invocation_service import AgentInvocationResult
from app.services.graph_agent_task_executor import GraphAgentTaskRequest

__all__ = ["GraphAgentTaskOutputValidator"]


class GraphAgentTaskOutputValidator:
    def __init__(
        self,
        *,
        career_store: CareerProductStore,
        session_repository: SessionRepository,
    ) -> None:
        self._career_store = career_store
        self._session_repository = session_repository

    def validate(
        self,
        request: GraphAgentTaskRequest,
        result: AgentInvocationResult,
    ) -> str | None:
        task_key = request.definition.task_key
        if task_key == "resume_analysis":
            return self._validate_resume_analysis(request, result)
        if task_key == "jd_analysis":
            return self._validate_jd_analysis(request, result)
        if task_key == "job_fit_analysis":
            return self._validate_job_fit_analysis(request, result)
        return f"unsupported graph task output validation: {task_key}"

    def _validate_resume_analysis(
        self,
        request: GraphAgentTaskRequest,
        result: AgentInvocationResult,
    ) -> str | None:
        profile_id = _first_ref(result.product_refs, "resume_profile_")
        profile = self._career_store.get_resume_profile(profile_id) if profile_id is not None else None
        if profile is None:
            return "resume_analysis output is missing a readable ResumeProfile."
        if profile.source_session_id != request.source_context.session_id:
            return "ResumeProfile belongs to a different session."
        if profile.source_artifact_id != request.input_refs.get("resume_artifact_id"):
            return "ResumeProfile does not reference the selected resume artifact."
        if not (
            profile.basic_info
            or profile.education
            or profile.work_experience
            or profile.project_experience
            or profile.skills
        ):
            return "ResumeProfile is empty."
        source_artifact_id = request.input_refs.get("resume_artifact_id")
        if source_artifact_id is not None:
            try:
                source_text = self._session_repository.read_session_artifact_text(
                    request.source_context.session_id,
                    source_artifact_id,
                )
            except Exception as exc:  # noqa: BLE001
                return f"cannot verify ResumeProfile against source artifact: {exc}"
            section_error = _resume_section_error(profile, source_text)
            if section_error is not None:
                return section_error
        if profile.diagnosis_artifact_id not in result.output_artifact_refs:
            return "ResumeProfile diagnosis artifact is missing from child outputs."
        return self._artifact_error(
            request.source_context.session_id,
            profile.diagnosis_artifact_id,
            label="resume diagnosis",
        )

    def _validate_jd_analysis(
        self,
        request: GraphAgentTaskRequest,
        result: AgentInvocationResult,
    ) -> str | None:
        jd_id = _first_ref(result.product_refs, "jd_")
        record = self._career_store.get_jd_analysis(jd_id) if jd_id is not None else None
        if record is None:
            return "jd_analysis output is missing a readable JDAnalysis."
        if record.source_session_id != request.source_context.session_id:
            return "JDAnalysis belongs to a different session."
        if record.source_artifact_id != request.input_refs.get("jd_artifact_id"):
            return "JDAnalysis does not reference the selected JD artifact."
        if not record.position or not (
            record.required_skills
            or record.responsibilities
            or record.keywords
        ):
            return "JDAnalysis is missing the position requirements."
        return None

    def _validate_job_fit_analysis(
        self,
        request: GraphAgentTaskRequest,
        result: AgentInvocationResult,
    ) -> str | None:
        fit_id = _first_ref(result.product_refs, "fit_")
        record = self._career_store.get_job_fit_report(fit_id) if fit_id is not None else None
        if record is None:
            return "job_fit_analysis output is missing a readable JobFitReport."
        expected_refs = {
            "resume_profile_id": record.resume_profile_id,
            "career_profile_id": record.career_profile_id,
            "jd_analysis_id": record.jd_analysis_id,
        }
        for key, actual in expected_refs.items():
            if actual != request.input_refs.get(key):
                return f"JobFitReport does not reference the selected {key}."
        if not record.score_breakdown:
            return "JobFitReport score_breakdown is empty."
        if not record.matched_evidence and not record.gaps:
            return "JobFitReport has neither matched evidence nor gaps."
        if not record.resume_optimization_direction and not record.interview_preparation_focus:
            return "JobFitReport is missing actionable recommendations."
        if record.report_artifact_id not in result.output_artifact_refs:
            return "JobFitReport artifact is missing from child outputs."
        return self._artifact_error(
            request.source_context.session_id,
            record.report_artifact_id,
            label="job fit report",
        )

    def _artifact_error(
        self,
        session_id: str,
        artifact_id: str | None,
        *,
        label: str,
    ) -> str | None:
        if artifact_id is None:
            return f"{label} artifact id is missing."
        artifact = self._session_repository.get_session_artifact(session_id, artifact_id)
        if artifact is None or artifact.status != "ready":
            return f"{label} artifact is not ready: {artifact_id}"
        return None


def _first_ref(refs: list[str], prefix: str) -> str | None:
    return next((ref for ref in refs if ref.startswith(prefix)), None)


def _resume_section_error(profile: object, source_text: str) -> str | None:
    checks = (
        (("教育经历", "education"), getattr(profile, "education", None), "education"),
        (("工作经历", "work experience"), getattr(profile, "work_experience", None), "work_experience"),
        (("项目经历", "project experience"), getattr(profile, "project_experience", None), "project_experience"),
        (("核心技能", "技能", "skills"), getattr(profile, "skills", None), "skills"),
    )
    normalized = source_text.casefold()
    for markers, value, field_name in checks:
        if any(marker.casefold() in normalized for marker in markers) and not value:
            return f"ResumeProfile omitted source section: {field_name}."
    return None
