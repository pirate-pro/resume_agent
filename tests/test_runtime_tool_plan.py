"""Tests for RuntimeToolPlan next-action planning."""

from __future__ import annotations

from app.runtime.context.models import CareerFlowState, CurrentWorkflowState
from app.runtime.workflow.phase import WorkflowPhaseSnapshot, WorkflowRequiredOutput
from app.runtime.workflow.tool_plan import (
    build_runtime_tool_plan,
    format_runtime_tool_plan_lines,
    pending_runtime_plan_from_tool_search_result,
    pending_runtime_plan_from_workflow_result,
    runtime_plan_discouraged_tools,
)

__all__ = []


def _output(name: str, ref_key: str, ref_value: str | None = None) -> WorkflowRequiredOutput:
    return WorkflowRequiredOutput(
        name=name,
        ref_key=ref_key,
        status="completed" if ref_value else "missing",
        ref_value=ref_value,
    )


def test_runtime_tool_plan_guides_resume_version_create_when_refs_are_ready() -> None:
    plan = build_runtime_tool_plan(
        workflow_phase=WorkflowPhaseSnapshot(
            phase_name="resume_version",
            confidence="high",
            required_outputs=[
                _output("resume_profile", "resume_profile_id", "resume_profile_alpha"),
                _output("jd_analysis", "jd_analysis_id", "jd_alpha"),
                _output("job_fit_report", "job_fit_report_id", "fit_alpha"),
                _output("career_application", "application_id", "application_alpha"),
                _output("resume_version", "resume_version_id"),
                _output("career_application_resume_version_link", "application_id"),
            ],
        ),
        career_flow_state=CareerFlowState(),
        workflow_state=CurrentWorkflowState(
            refs={
                "resume_profile_id": "resume_profile_alpha",
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
                "application_id": "application_alpha",
            }
        ),
    )

    assert plan.phase == "resume_version"
    assert plan.next_allowed_tools == [
        "career_application_get",
        "career_resume_profile_get",
        "career_jd_analysis_get",
        "career_job_fit_report_get",
        "career_resume_version_create",
    ]
    assert plan.schema_groups == ["career_read", "career_resume_version"]
    assert "session_read_artifact" in plan.discouraged_tools
    assert "retrieval_search" in plan.discouraged_tools
    assert plan.final_answer_ready is False
    assert any("career_resume_version_create" in line for line in format_runtime_tool_plan_lines(plan))


def test_runtime_tool_plan_guides_application_merge_after_resume_version() -> None:
    plan = build_runtime_tool_plan(
        workflow_phase=WorkflowPhaseSnapshot(
            phase_name="resume_version",
            confidence="high",
            required_outputs=[
                _output("resume_profile", "resume_profile_id", "resume_profile_alpha"),
                _output("jd_analysis", "jd_analysis_id", "jd_alpha"),
                _output("job_fit_report", "job_fit_report_id", "fit_alpha"),
                _output("career_application", "application_id", "application_alpha"),
                _output("resume_version", "resume_version_id", "resume_version_alpha"),
                _output("career_application_resume_version_link", "application_id"),
            ],
        ),
        career_flow_state=CareerFlowState(multi_refs={"resume_version_ids": ["resume_version_alpha"]}),
        workflow_state=CurrentWorkflowState(
            refs={
                "resume_profile_id": "resume_profile_alpha",
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
                "application_id": "application_alpha",
            }
        ),
    )

    assert plan.next_allowed_tools == ["career_application_merge"]
    assert plan.known_refs["resume_version_id"] == "resume_version_alpha"
    assert "career_resume_version_create" in plan.discouraged_tools


def test_runtime_tool_plan_creates_application_when_resume_stage_lacks_application() -> None:
    plan = build_runtime_tool_plan(
        workflow_phase=WorkflowPhaseSnapshot(
            phase_name="resume_version",
            confidence="high",
            required_outputs=[
                _output("resume_profile", "resume_profile_id", "resume_profile_alpha"),
                _output("jd_analysis", "jd_analysis_id", "jd_alpha"),
                _output("job_fit_report", "job_fit_report_id", "fit_alpha"),
                _output("career_application", "application_id"),
                _output("resume_version", "resume_version_id"),
                _output("career_application_resume_version_link", "application_id"),
            ],
        ),
        career_flow_state=CareerFlowState(),
        workflow_state=CurrentWorkflowState(
            refs={
                "resume_profile_id": "resume_profile_alpha",
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
            }
        ),
    )

    assert plan.phase == "resume_version"
    assert plan.next_allowed_tools == ["career_application_create"]
    assert "career_application" in plan.missing_outputs
    assert "delegate_agents" in plan.discouraged_tools
    assert "career_application_list" in plan.discouraged_tools
    assert "career_resume_version_create" in plan.discouraged_tools
    assert "直接调用 career_application_create" in (plan.next_action or "")


def test_pending_runtime_plan_from_workflow_result_preserves_discouraged_tools() -> None:
    plan = pending_runtime_plan_from_workflow_result(
        """
        {
          "workflow_runtime_result": true,
          "policy": "block",
          "terminal": false,
          "stage": "jd_fit",
          "next_allowed_tools": ["career_application_create"],
          "missing_outputs": ["career_application"],
          "completed_refs": {"job_fit_report_id": "fit_alpha"},
          "blocked_tools": ["delegate_agents", "session_read_artifact"]
        }
        """
    )

    assert plan is not None
    assert plan["next_allowed_tools"] == ["career_application_create"]
    assert runtime_plan_discouraged_tools(plan) == ["delegate_agents", "session_read_artifact"]


def test_pending_runtime_plan_from_tool_search_result_preserves_runtime_discouraged_tools() -> None:
    plan = pending_runtime_plan_from_tool_search_result(
        """
        {
          "runtime_plan_applied": true,
          "runtime_final_answer_ready": false,
          "runtime_plan_phase": "resume_version",
          "runtime_next_allowed_tools": ["career_resume_version_create"],
          "runtime_missing_outputs": ["resume_version"],
          "runtime_discouraged_tools": ["delegate_agents", "session_read_artifact"]
        }
        """
    )

    assert plan is not None
    assert plan["next_allowed_tools"] == ["career_resume_version_create"]
    assert runtime_plan_discouraged_tools(plan) == ["delegate_agents", "session_read_artifact"]


def test_runtime_tool_plan_stops_when_final_answer_ready() -> None:
    plan = build_runtime_tool_plan(
        workflow_phase=WorkflowPhaseSnapshot(
            phase_name="jd_fit",
            confidence="high",
            required_outputs=[
                _output("jd_analysis", "jd_analysis_id", "jd_alpha"),
                _output("job_fit_report", "job_fit_report_id", "fit_alpha"),
                _output("career_application", "application_id", "application_alpha"),
            ],
            final_answer_ready=True,
        ),
        career_flow_state=CareerFlowState(final_answer_ready=True),
        workflow_state=CurrentWorkflowState(
            refs={
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
                "application_id": "application_alpha",
            }
        ),
    )

    assert plan.final_answer_ready is True
    assert plan.next_allowed_tools == []
    assert "tool_search" in plan.discouraged_tools
    assert "直接面向用户总结结果" in (plan.next_action or "")


def test_runtime_tool_plan_guides_jd_fit_application_create() -> None:
    plan = build_runtime_tool_plan(
        workflow_phase=WorkflowPhaseSnapshot(
            phase_name="jd_fit",
            confidence="high",
            required_outputs=[
                _output("jd_analysis", "jd_alpha", "jd_alpha"),
                _output("job_fit_report", "fit_alpha", "fit_alpha"),
                _output("career_application", "application_id"),
            ],
        ),
        career_flow_state=CareerFlowState(),
        workflow_state=CurrentWorkflowState(
            refs={
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
                "resume_profile_id": "resume_profile_alpha",
            }
        ),
    )

    assert plan.next_allowed_tools == ["career_application_create"]
    assert "delegate_agents" in plan.discouraged_tools
    assert "career_resume_version_create" in plan.discouraged_tools
