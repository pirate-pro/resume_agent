"""Tests for RuntimeToolPlan next-action planning."""

from __future__ import annotations

from app.runtime.context.models import CareerFlowState, CurrentWorkflowState
from app.runtime.workflow.phase import WorkflowPhaseSnapshot, WorkflowRequiredOutput
from app.runtime.workflow.tool_plan import (
    build_runtime_tool_plan,
    format_runtime_tool_plan_lines,
    pending_runtime_plan_from_context_bundle,
    pending_runtime_plan_from_successful_tool_result,
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


def test_pending_runtime_plan_from_workflow_reuse_result_can_drive_next_step() -> None:
    plan = pending_runtime_plan_from_workflow_result(
        """
        {
          "workflow_runtime_result": true,
          "policy": "reuse",
          "stage": "jd_fit",
          "next_allowed_tools": ["career_jd_analysis_save"],
          "required_tools": ["career_jd_analysis_save"],
          "missing_outputs": ["jd_analysis", "job_fit_report"],
          "completed_refs": {"report_artifact_id": "artifact_fit_report"},
          "blocked_tools": ["session_read_artifact", "career_job_fit_report_save"]
        }
        """
    )

    assert plan is not None
    assert plan["next_allowed_tools"] == ["career_jd_analysis_save"]
    assert plan["required_tools"] == ["career_jd_analysis_save"]
    assert plan["known_refs"] == {"report_artifact_id": "artifact_fit_report"}
    assert runtime_plan_discouraged_tools(plan) == ["session_read_artifact", "career_job_fit_report_save"]


def test_successful_jd_analysis_save_advances_pending_plan_to_job_fit_report_save() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "career_jd_analysis_save",
        """
        {
          "record_type": "jd_analysis",
          "record_id": "jd_alpha",
          "record": {"jd_analysis_id": "jd_alpha"}
        }
        """,
        previous_pending_plan={
            "phase": "jd_fit",
            "next_allowed_tools": ["career_jd_analysis_save"],
            "required_tools": ["career_jd_analysis_save"],
            "known_refs": {"report_artifact_id": "artifact_fit_report"},
            "missing_outputs": ["jd_analysis", "job_fit_report"],
        },
    )

    assert plan is not None
    assert plan["next_allowed_tools"] == ["career_job_fit_report_save"]
    assert plan["required_tools"] == ["career_job_fit_report_save"]
    assert plan["known_refs"]["jd_analysis_id"] == "jd_alpha"
    assert plan["known_refs"]["report_artifact_id"] == "artifact_fit_report"
    assert "career_jd_analysis_save" in runtime_plan_discouraged_tools(plan)


def test_successful_jd_analysis_save_without_pending_plan_guides_report_artifact_creation() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "career_jd_analysis_save",
        """
        {
          "record_type": "jd_analysis",
          "record_id": "jd_alpha",
          "record": {"jd_analysis_id": "jd_alpha"}
        }
        """,
        previous_pending_plan=None,
    )

    assert plan is not None
    assert plan["next_allowed_tools"] == ["session_create_text_artifact"]
    assert plan["required_tools"] == ["session_create_text_artifact"]
    assert plan["known_refs"]["jd_analysis_id"] == "jd_alpha"
    assert plan["missing_outputs"] == ["job_fit_report_artifact", "job_fit_report"]
    assert "career_job_fit_report_save" in runtime_plan_discouraged_tools(plan)


def test_successful_job_fit_artifact_guides_fit_save_when_jd_is_known() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "session_create_text_artifact",
        """
        {
          "artifact_id": "artifact_fit_report",
          "title": "岗位匹配报告 - AI 应用开发工程师",
          "kind": "generated_file"
        }
        """,
        previous_pending_plan={
            "phase": "jd_fit",
            "next_allowed_tools": ["session_create_text_artifact"],
            "required_tools": ["session_create_text_artifact"],
            "known_refs": {"jd_analysis_id": "jd_alpha"},
            "missing_outputs": ["job_fit_report_artifact", "job_fit_report"],
        },
    )

    assert plan is not None
    assert plan["next_allowed_tools"] == ["career_job_fit_report_save"]
    assert plan["required_tools"] == ["career_job_fit_report_save"]
    assert plan["known_refs"]["jd_analysis_id"] == "jd_alpha"
    assert plan["known_refs"]["report_artifact_id"] == "artifact_fit_report"
    assert "session_read_artifact" in runtime_plan_discouraged_tools(plan)


def test_successful_job_fit_artifact_without_jd_guides_jd_save_first() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "session_create_text_artifact",
        """
        {
          "artifact_id": "artifact_fit_report",
          "title": "岗位匹配报告 - AI 应用开发工程师",
          "kind": "generated_file"
        }
        """,
        previous_pending_plan=None,
    )

    assert plan is not None
    assert plan["next_allowed_tools"] == ["career_jd_analysis_save"]
    assert plan["required_tools"] == ["career_jd_analysis_save"]
    assert plan["known_refs"]["report_artifact_id"] == "artifact_fit_report"
    assert "session_create_text_artifact" in runtime_plan_discouraged_tools(plan)


def test_successful_delegate_agents_jd_fit_guides_application_create() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "delegate_agents",
        """
        {
          "status": "completed",
          "results": [
            {
              "target_agent_id": "job_agent",
              "status": "completed",
              "summary": "已完成 JDAnalysis jd_alpha 和 JobFitReport fit_alpha。",
              "output_artifact_refs": ["artifact_fit_report"],
              "product_refs": ["jd_alpha", "fit_alpha"]
            }
          ]
        }
        """,
        previous_pending_plan={
            "phase": "jd_fit",
            "next_allowed_tools": ["delegate_agents"],
            "required_tools": ["delegate_agents"],
            "known_refs": {"resume_profile_id": "resume_profile_alpha"},
            "missing_outputs": ["jd_analysis", "job_fit_report", "career_application"],
        },
    )

    assert plan is not None
    assert plan["phase"] == "jd_fit"
    assert plan["next_allowed_tools"] == ["career_application_create"]
    assert plan["required_tools"] == ["career_application_create"]
    assert plan["missing_outputs"] == ["career_application"]
    assert plan["known_refs"]["resume_profile_id"] == "resume_profile_alpha"
    assert plan["known_refs"]["jd_analysis_id"] == "jd_alpha"
    assert plan["known_refs"]["job_fit_report_id"] == "fit_alpha"
    assert plan["known_refs"]["report_artifact_id"] == "artifact_fit_report"
    assert "delegate_agents" in runtime_plan_discouraged_tools(plan)
    assert "tool_search" in runtime_plan_discouraged_tools(plan)


def test_successful_delegate_agents_extracts_refs_from_text_when_structured_refs_are_sparse() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "delegate_agents",
        """
        {
          "status": "completed",
          "results": [
            {
              "target_agent_id": "job_agent",
              "status": "completed",
              "summary": "产出：jd_analysis_id=jd_b8e6607b59a6，job_fit_report_id=fit_b7c9ff559172，报告 artifact_5eba62c32cd4。"
            }
          ]
        }
        """,
        previous_pending_plan={
            "phase": "jd_fit",
            "next_allowed_tools": ["delegate_agents"],
            "required_tools": ["delegate_agents"],
            "known_refs": {"resume_profile_id": "resume_profile_2c9a9af42398"},
            "missing_outputs": ["jd_analysis", "job_fit_report", "career_application"],
        },
    )

    assert plan is not None
    assert plan["next_allowed_tools"] == ["career_application_create"]
    assert plan["known_refs"]["jd_analysis_id"] == "jd_b8e6607b59a6"
    assert plan["known_refs"]["job_fit_report_id"] == "fit_b7c9ff559172"
    assert plan["known_refs"]["report_artifact_id"] == "artifact_5eba62c32cd4"


def test_successful_resume_profile_save_does_not_guess_missing_diagnosis_without_runtime_state() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "career_resume_profile_save",
        """
        {
          "record_type": "resume_profile",
          "record_id": "resume_profile_alpha",
          "record": {"resume_profile_id": "resume_profile_alpha"}
        }
        """,
        previous_pending_plan=None,
    )

    assert plan is None


def test_successful_resume_profile_save_finishes_when_diagnosis_artifact_exists() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "career_resume_profile_save",
        """
        {
          "record_type": "resume_profile",
          "record_id": "resume_profile_alpha",
          "record": {"resume_profile_id": "resume_profile_alpha"}
        }
        """,
        previous_pending_plan={
            "phase": "resume_diagnosis",
            "next_allowed_tools": ["career_resume_profile_save"],
            "required_tools": ["career_resume_profile_save"],
            "known_refs": {"diagnosis_artifact_id": "artifact_diagnosis"},
            "missing_outputs": ["resume_profile"],
        },
    )

    assert plan is not None
    assert plan["final_answer_ready"] is True
    assert plan["next_allowed_tools"] == []
    assert plan["missing_outputs"] == []
    assert plan["known_refs"]["resume_profile_id"] == "resume_profile_alpha"
    assert plan["known_refs"]["diagnosis_artifact_id"] == "artifact_diagnosis"


def test_successful_resume_diagnosis_artifact_finishes_resume_stage() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "session_create_text_artifact",
        """
        {
          "artifact_id": "artifact_diagnosis",
          "title": "张明-简历诊断报告.md",
          "kind": "generated_file"
        }
        """,
        previous_pending_plan={
            "phase": "resume_diagnosis",
            "next_allowed_tools": ["session_create_text_artifact"],
            "required_tools": ["session_create_text_artifact"],
            "known_refs": {"resume_profile_id": "resume_profile_alpha"},
            "missing_outputs": ["diagnosis_artifact"],
        },
    )

    assert plan is not None
    assert plan["final_answer_ready"] is True
    assert plan["next_allowed_tools"] == []
    assert plan["known_refs"]["resume_profile_id"] == "resume_profile_alpha"
    assert plan["known_refs"]["diagnosis_artifact_id"] == "artifact_diagnosis"
    assert "session_create_text_artifact" in runtime_plan_discouraged_tools(plan)


def test_successful_resume_version_create_preserves_application_ref_for_merge() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "career_resume_version_create",
        """
        {
          "record_type": "resume_version",
          "record_id": "resume_version_alpha",
          "record": {
            "resume_version_id": "resume_version_alpha",
            "artifact_id": "artifact_resume_version"
          }
        }
        """,
        previous_pending_plan={
            "phase": "resume_version",
            "next_allowed_tools": ["career_resume_version_create"],
            "required_tools": ["career_resume_version_create"],
            "known_refs": {
                "application_id": "application_alpha",
                "resume_profile_id": "resume_profile_alpha",
                "jd_analysis_id": "jd_alpha"
            },
            "missing_outputs": ["resume_version", "career_application_resume_version_link"],
        },
    )

    assert plan is not None
    assert plan["next_allowed_tools"] == ["career_application_merge"]
    assert plan["required_tools"] == ["career_application_merge"]
    assert plan["known_refs"]["application_id"] == "application_alpha"
    assert plan["known_refs"]["resume_version_id"] == "resume_version_alpha"
    assert plan["known_refs"]["artifact_id"] == "artifact_resume_version"


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


def test_final_context_runtime_plan_still_hides_discouraged_tools() -> None:
    plan = pending_runtime_plan_from_context_bundle(
        {
            "phase": "resume_diagnosis",
            "known_refs": {"resume_profile_id": "resume_profile_alpha"},
            "missing_outputs": [],
            "next_allowed_tools": [],
            "discouraged_tools": ["tool_search", "delegate_agents", "session_read_artifact"],
            "final_answer_ready": True,
            "next_action": "关键产物已完成；直接总结结果。",
        }
    )

    assert plan is not None
    assert plan["final_answer_ready"] is True
    assert plan["next_allowed_tools"] == []
    assert plan["required_tools"] == []
    assert plan["known_refs"]["resume_profile_id"] == "resume_profile_alpha"
    assert runtime_plan_discouraged_tools(plan) == ["tool_search", "delegate_agents", "session_read_artifact"]


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
