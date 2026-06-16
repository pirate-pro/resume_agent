"""Tests for LangGraph child-task product quality gates."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.domain.models import RunContext
from app.runtime.langgraph.multi_agent_contracts import CAREER_INTAKE_TASK_GRAPH
from app.services.agent_invocation_service import AgentInvocationResult
from app.services.graph_agent_task_executor import GraphAgentTaskRequest
from app.services.graph_agent_task_output_validator import GraphAgentTaskOutputValidator


class _CareerStore:
    def __init__(self, *, fit: Any = None, resume: Any = None) -> None:
        self._fit = fit
        self._resume = resume

    def get_job_fit_report(self, fit_id: str) -> Any:
        return self._fit if fit_id == "fit_alpha" else None

    def get_resume_profile(self, profile_id: str) -> Any:
        return self._resume if profile_id == "resume_profile_alpha" else None


class _SessionRepository:
    def get_session_artifact(self, session_id: str, artifact_id: str) -> Any:
        if session_id == "sess_multi" and artifact_id == "artifact_fit_report":
            return SimpleNamespace(status="ready")
        if session_id == "sess_multi" and artifact_id == "artifact_diagnosis":
            return SimpleNamespace(status="ready")
        return None

    def read_session_artifact_text(self, session_id: str, artifact_id: str) -> str:
        assert session_id == "sess_multi"
        assert artifact_id == "artifact_resume"
        return "# 简历\n\n## 教育经历\n本科\n\n## 工作经历\n后端工程师\n\n## 项目经历\nAgent\n\n## 核心技能\nPython"


def test_resume_validator_rejects_omitted_source_section() -> None:
    validator = GraphAgentTaskOutputValidator(
        career_store=_CareerStore(
            resume=SimpleNamespace(
                source_session_id="sess_multi",
                source_artifact_id="artifact_resume",
                basic_info={"name": "张明"},
                education=[],
                work_experience=[{"position": "后端工程师"}],
                project_experience=[{"name": "Agent"}],
                skills=["Python"],
                diagnosis_artifact_id="artifact_diagnosis",
            )
        ),  # type: ignore[arg-type]
        session_repository=_SessionRepository(),  # type: ignore[arg-type]
    )
    request = GraphAgentTaskRequest(
        source_context=_context(),
        workflow_instance_id="wf_multi",
        graph=CAREER_INTAKE_TASK_GRAPH,
        definition=CAREER_INTAKE_TASK_GRAPH.task("resume_analysis"),
        instruction="解析简历。",
        input_refs={"resume_artifact_id": "artifact_resume"},
        artifact_refs=("artifact_resume",),
    )
    result = AgentInvocationResult(
        task_id="graph_task_resume",
        source_agent_id="agent_main",
        target_agent_id="resume_agent",
        child_run_id="run_child",
        status="completed",
        summary="completed",
        artifact_refs=["artifact_resume"],
        output_artifact_refs=["artifact_diagnosis"],
        product_refs=["resume_profile_alpha"],
        answer="completed",
    )

    assert validator.validate(request, result) == "ResumeProfile omitted source section: education."


def test_job_fit_validator_rejects_empty_structured_report() -> None:
    validator = _validator(
        SimpleNamespace(
            resume_profile_id="resume_profile_alpha",
            career_profile_id="career_profile_default",
            jd_analysis_id="jd_alpha",
            score_breakdown={},
            matched_evidence=[],
            gaps=[],
            resume_optimization_direction=[],
            interview_preparation_focus=[],
            report_artifact_id="artifact_fit_report",
        )
    )

    error = validator.validate(_request(), _result())

    assert error == "JobFitReport score_breakdown is empty."


def test_job_fit_validator_accepts_substantive_report() -> None:
    validator = _validator(
        SimpleNamespace(
            resume_profile_id="resume_profile_alpha",
            career_profile_id="career_profile_default",
            jd_analysis_id="jd_alpha",
            score_breakdown={"skills": 82, "experience": 76},
            matched_evidence=["FastAPI 与 Agent Runtime 经历匹配"],
            gaps=["消息队列深度不足"],
            resume_optimization_direction=["突出 RAG 评估经验"],
            interview_preparation_focus=["准备 Kafka 与 Celery 取舍"],
            report_artifact_id="artifact_fit_report",
        )
    )

    assert validator.validate(_request(), _result()) is None


def _validator(fit: Any) -> GraphAgentTaskOutputValidator:
    return GraphAgentTaskOutputValidator(
        career_store=_CareerStore(fit=fit),  # type: ignore[arg-type]
        session_repository=_SessionRepository(),  # type: ignore[arg-type]
    )


def _request() -> GraphAgentTaskRequest:
    return GraphAgentTaskRequest(
        source_context=_context(),
        workflow_instance_id="wf_multi",
        graph=CAREER_INTAKE_TASK_GRAPH,
        definition=CAREER_INTAKE_TASK_GRAPH.task("job_fit_analysis"),
        instruction="生成岗位匹配报告。",
        input_refs={
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "jd_analysis_id": "jd_alpha",
        },
        artifact_refs=("artifact_jd",),
    )


def _context() -> RunContext:
    return RunContext(
        session_id="sess_multi",
        run_id="run_multi",
        agent_id="agent_main",
        turn_id="turn_multi",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={},
    )


def _result() -> AgentInvocationResult:
    return AgentInvocationResult(
        task_id="graph_task_fit",
        source_agent_id="agent_main",
        target_agent_id="job_agent",
        child_run_id="run_child",
        status="completed",
        summary="completed",
        artifact_refs=["artifact_jd"],
        output_artifact_refs=["artifact_fit_report"],
        product_refs=["fit_alpha"],
        answer="completed",
    )
