"""Tests for RuntimeToolPlan next-action planning."""

from __future__ import annotations

import json

from app.runtime.agent.tool_reveal import hidden_tool_result
from app.runtime.context.models import CareerFlowState, CurrentWorkflowState
from app.runtime.workflow.intent_boundary import build_turn_intent_boundary
from app.runtime.workflow.phase import WorkflowPhaseSnapshot, WorkflowRequiredOutput
from app.runtime.workflow.tool_plan import (
    build_runtime_tool_plan,
    format_runtime_tool_plan_lines,
    known_refs_from_successful_tool_result,
    merge_pending_runtime_plan,
    pending_runtime_plan_from_context_bundle,
    pending_runtime_plan_from_successful_tool_result,
    pending_runtime_plan_from_tool_search_result,
    pending_runtime_plan_from_workflow_result,
    runtime_plan_discouraged_tools,
    runtime_plan_notice,
)

__all__ = []


def _output(name: str, ref_key: str, ref_value: str | None = None) -> WorkflowRequiredOutput:
    return WorkflowRequiredOutput(
        name=name,
        ref_key=ref_key,
        status="completed" if ref_value else "missing",
        ref_value=ref_value,
    )


def test_graph_jd_analysis_finishes_after_jd_save() -> None:
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
            "phase": "jd_analysis",
            "known_refs": {"jd_artifact_id": "artifact_jd_alpha"},
            "missing_outputs": ["jd_analysis_id"],
            "next_allowed_tools": ["career_jd_analysis_save"],
            "required_tools": ["career_jd_analysis_save"],
        },
    )

    assert plan is not None
    assert plan["phase"] == "jd_analysis"
    assert plan["final_answer_ready"] is True
    assert plan["missing_outputs"] == []
    assert plan["required_tools"] == []
    assert plan["known_refs"]["jd_analysis_id"] == "jd_alpha"


def test_graph_job_fit_transitions_from_artifact_to_structured_save() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "session_create_text_artifact",
        """
        {
          "artifact_id": "artifact_fit_report",
          "title": "岗位匹配报告",
          "kind": "generated_file"
        }
        """,
        previous_pending_plan={
            "phase": "job_fit_analysis",
            "known_refs": {
                "resume_profile_id": "resume_profile_alpha",
                "career_profile_id": "career_profile_default",
                "jd_analysis_id": "jd_alpha"
            },
            "missing_outputs": ["report_artifact_id", "job_fit_report_id"],
            "next_allowed_tools": ["session_create_text_artifact"],
            "required_tools": ["session_create_text_artifact"],
        },
    )

    assert plan is not None
    assert plan["phase"] == "job_fit_analysis"
    assert plan["next_allowed_tools"] == ["career_job_fit_report_save"]
    assert plan["required_tools"] == ["career_job_fit_report_save"]
    assert plan["known_refs"]["report_artifact_id"] == "artifact_fit_report"
    assert "评分拆分" in plan["next_action"]


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
    assert plan.next_allowed_tools == ["career_resume_version_create"]
    assert plan.schema_groups == ["career_resume_version"]
    assert "session_read_artifact" in plan.discouraged_tools
    assert "career_resume_profile_get" in plan.discouraged_tools
    assert "retrieval_search" in plan.discouraged_tools
    assert plan.final_answer_ready is False
    assert any("career_resume_version_create" in line for line in format_runtime_tool_plan_lines(plan))


def test_action_runtime_plan_exposes_upcoming_tools_without_changing_current_allowed_tools() -> None:
    plan = build_runtime_tool_plan(
        workflow_phase=WorkflowPhaseSnapshot(
            phase_name="interview_review_update",
            confidence="high",
            required_outputs=[
                _output("retrieval_search", "retrieval_search", "done"),
                _output("retrieval_context_pack", "retrieval_context_pack", "done"),
                _output("note", "note_id"),
                _output("career_application_update", "application_id"),
            ],
        ),
        career_flow_state=CareerFlowState(),
        workflow_state=CurrentWorkflowState(refs={"application_id": "application_alpha"}),
    )

    lines = format_runtime_tool_plan_lines(plan)

    assert plan.next_allowed_tools == ["note_create", "note_append"]
    assert plan.required_tools == ["note_create", "note_append"]
    assert plan.upcoming_required_tools == ["career_application_merge"]
    assert "- current_allowed_tools=note_create,note_append" in lines
    assert "- upcoming_required_tools=career_application_merge" in lines


def test_runtime_plan_notice_includes_required_tool_hint() -> None:
    notice = runtime_plan_notice(
        {
            "phase": "resume_version",
            "next_allowed_tools": ["career_resume_version_create"],
            "required_tools": ["career_resume_version_create"],
            "known_refs": {
                "resume_profile_id": "resume_profile_alpha",
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
                "application_id": "application_alpha",
            },
            "missing_outputs": ["resume_version"],
            "discouraged_tools": ["tool_search"],
            "next_action": "直接生成定制简历版本。",
        }
    )

    assert "下一次工具参数提示" in notice
    assert "career_resume_version_create" in notice
    assert "base_resume_profile_id" in notice
    assert "content_or_artifact_id" in notice


def test_runtime_plan_notice_warns_not_to_search_upcoming_tool_schema() -> None:
    notice = runtime_plan_notice(
        {
            "phase": "interview_review_update",
            "next_allowed_tools": ["note_create", "note_append"],
            "required_tools": ["note_create", "note_append"],
            "upcoming_required_tools": ["career_application_merge"],
            "missing_outputs": ["note", "career_application_update"],
            "next_action": "先保存面试复盘 Note，之后再更新求职项目。",
        }
    )

    assert "后续必需工具：career_application_merge" in notice
    assert "当前不要提前调用或搜索 schema" in notice


def test_terminal_workflow_result_becomes_final_answer_ready_plan() -> None:
    plan = pending_runtime_plan_from_workflow_result(
        json.dumps(
            {
                "workflow_runtime_result": True,
                "policy": "block",
                "terminal": True,
                "stage": "resume_diagnosis",
                "stage_status": "completed",
                "next_action": "ResumeProfile 和 CareerProfile 已完成；直接给用户最终答复。",
                "missing_outputs": [],
                "completed_refs": {
                    "resume_profile_id": "resume_profile_alpha",
                    "career_profile_id": "career_profile_default",
                    "diagnosis_artifact_id": "artifact_diagnosis",
                },
                "next_allowed_tools": [],
            },
            ensure_ascii=False,
        )
    )

    assert plan is not None
    assert plan["final_answer_ready"] is True
    assert plan["phase"] == "resume_diagnosis"
    assert plan["next_allowed_tools"] == []
    assert plan["required_tools"] == []
    assert plan["known_refs"]["resume_profile_id"] == "resume_profile_alpha"
    assert plan["known_refs"]["career_profile_id"] == "career_profile_default"


def test_runtime_tool_plan_reads_application_before_project_resume_version() -> None:
    plan = build_runtime_tool_plan(
        workflow_phase=WorkflowPhaseSnapshot(
            phase_name="resume_version",
            confidence="high",
            required_outputs=[
                _output("resume_profile", "resume_profile_id", "resume_profile_alpha"),
                _output("jd_analysis", "jd_analysis_id", "jd_alpha"),
                _output("job_fit_report", "job_fit_report_id", "fit_alpha"),
                _output("career_application", "application_id", "application_alpha"),
                _output("career_application_read", "application_id"),
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
    assert plan.next_allowed_tools == ["career_application_get"]
    assert plan.missing_outputs == [
        "career_application_read",
        "resume_version",
        "career_application_resume_version_link",
    ]
    assert plan.schema_groups == ["career_application"]
    assert "career_resume_version_create" in plan.discouraged_tools
    assert "先调用 career_application_get" in (plan.next_action or "")


def test_runtime_tool_plan_uses_completed_phase_refs_from_current_message() -> None:
    plan = build_runtime_tool_plan(
        workflow_phase=WorkflowPhaseSnapshot(
            phase_name="resume_version",
            confidence="high",
            required_outputs=[
                _output("resume_profile", "resume_profile_id"),
                _output("jd_analysis", "jd_analysis_id"),
                _output("job_fit_report", "job_fit_report_id"),
                _output("career_application", "application_id", "application_alpha"),
                _output("career_application_read", "application_id"),
                _output("resume_version", "resume_version_id"),
                _output("career_application_resume_version_link", "application_id"),
            ],
        ),
        career_flow_state=CareerFlowState(),
        workflow_state=CurrentWorkflowState(),
    )

    assert plan.phase == "resume_version"
    assert plan.known_refs["application_id"] == "application_alpha"
    assert plan.next_allowed_tools == ["career_application_get"]
    assert "career_resume_version_create" in plan.discouraged_tools


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


def test_application_action_plan_survives_hidden_search_before_application_get() -> None:
    current = {
        "phase": "application_action",
        "next_action": "项目动作必须先读取当前 CareerApplication，再基于其中关联记录更新项目。",
        "next_allowed_tools": ["career_application_get"],
        "required_tools": ["career_application_get"],
        "known_refs": {"application_id": "application_alpha"},
        "missing_outputs": ["career_application_read"],
        "discouraged_tools": ["tool_search"],
    }
    hidden_result = hidden_tool_result("tool_search", runtime_plan=current)
    hidden_plan = pending_runtime_plan_from_workflow_result(hidden_result.content)
    assert hidden_plan is not None

    merged = merge_pending_runtime_plan(current=current, incoming=hidden_plan)
    assert merged["phase"] == "application_action"

    next_plan = pending_runtime_plan_from_successful_tool_result(
        "career_application_get",
        (
            '{"record_type": "career_application", "record_id": "application_alpha", '
            '"record": {"application_id": "application_alpha", "resume_profile_id": "resume_profile_alpha", '
            '"career_profile_id": "career_profile_default", "jd_analysis_id": "jd_alpha", '
            '"job_fit_report_id": "fit_alpha", "resume_version_ids": ["resume_version_alpha"]}}'
        ),
        previous_pending_plan=merged,
    )

    assert next_plan is not None
    assert next_plan["phase"] == "application_action"
    assert next_plan["next_allowed_tools"] == ["career_application_merge"]
    assert next_plan["required_tools"] == ["career_application_merge"]
    assert next_plan["missing_outputs"] == ["career_application_update"]


def test_workflow_result_runtime_plan_preserves_report_artifact_contract() -> None:
    content = json.dumps(
        {
            "workflow_runtime_result": True,
            "policy": "block",
            "reason": "job_fit_report_artifact_candidate_facts_conflict",
            "stage": "jd_fit",
            "next_allowed_tools": ["session_create_text_artifact"],
            "required_tools": ["session_create_text_artifact"],
            "missing_outputs": ["valid_job_fit_report_artifact"],
            "report_artifact_contract": {
                "supported_candidate_facts": ["Python", "FastAPI"],
                "unsupported_candidate_facts": ["Spring"],
                "rewrite_rules": ["Spring 只能作为差距或风险。"],
                "artifact_rules": {"content": "完整 Markdown 正文"},
            },
        },
        ensure_ascii=False,
    )

    plan = pending_runtime_plan_from_workflow_result(content)

    assert plan is not None
    assert plan["required_tools"] == ["session_create_text_artifact"]
    assert plan["report_artifact_contract"]["unsupported_candidate_facts"] == ["Spring"]


def test_job_fit_report_save_hint_defaults_career_profile_id() -> None:
    result = hidden_tool_result(
        "session_read_artifact",
        runtime_plan={
            "phase": "jd_fit",
            "next_allowed_tools": ["career_job_fit_report_save"],
            "required_tools": ["career_job_fit_report_save"],
            "known_refs": {
                "jd_analysis_id": "jd_alpha",
                "resume_profile_id": "resume_profile_alpha",
                "source_artifact_id": "artifact_jd_alpha",
                "report_artifact_id": "artifact_report_alpha",
            },
            "missing_outputs": ["job_fit_report"],
        },
        strict_runtime_plan=True,
    )

    payload = json.loads(result.content)
    hint = payload["required_tool_call_hint"]

    assert hint["available_args"]["career_profile_id"] == "career_profile_default"
    assert hint["missing_args"] == []


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


def test_successful_application_create_finishes_jd_fit_plan() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "career_application_create",
        """
        {
          "record_type": "career_application",
          "record_id": "application_alpha",
          "record": {
            "application_id": "application_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "jd_analysis_id": "jd_alpha",
            "job_fit_report_id": "fit_alpha"
          }
        }
        """,
        previous_pending_plan={
            "phase": "jd_fit",
            "next_allowed_tools": ["career_application_create"],
            "required_tools": ["career_application_create"],
            "known_refs": {
                "resume_profile_id": "resume_profile_alpha",
                "career_profile_id": "career_profile_default",
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
            },
            "missing_outputs": ["career_application"],
        },
    )

    assert plan is not None
    assert plan["phase"] == "jd_fit"
    assert plan["final_answer_ready"] is True
    assert plan["missing_outputs"] == []
    assert plan["known_refs"]["application_id"] == "application_alpha"
    assert plan["known_refs"]["job_fit_report_id"] == "fit_alpha"


def test_successful_application_create_finishes_resume_version_plan() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "career_application_create",
        """
        {
          "record_type": "career_application",
          "record_id": "application_alpha",
          "record": {
            "application_id": "application_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "jd_analysis_id": "jd_alpha",
            "job_fit_report_id": "fit_alpha",
            "resume_version_ids": ["resume_version_alpha"]
          }
        }
        """,
        previous_pending_plan={
            "phase": "resume_version",
            "next_allowed_tools": ["career_application_create"],
            "required_tools": ["career_application_create"],
            "known_refs": {
                "resume_profile_id": "resume_profile_alpha",
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
                "resume_version_id": "resume_version_alpha",
            },
            "missing_outputs": ["career_application"],
        },
    )

    assert plan is not None
    assert plan["phase"] == "resume_version"
    assert plan["final_answer_ready"] is True
    assert plan["missing_outputs"] == []
    assert plan["known_refs"]["application_id"] == "application_alpha"
    assert plan["known_refs"]["resume_version_id"] == "resume_version_alpha"


def test_runtime_tool_plan_application_action_reads_application_first() -> None:
    plan = build_runtime_tool_plan(
        workflow_phase=WorkflowPhaseSnapshot(
            phase_name="application_action",
            confidence="high",
            required_outputs=[
                _output("career_application", "application_id", "application_alpha"),
            ],
        ),
        career_flow_state=CareerFlowState(),
        workflow_state=CurrentWorkflowState(refs={"application_id": "application_alpha"}),
    )

    assert plan.phase == "application_action"
    assert plan.next_allowed_tools == ["career_application_get"]
    assert plan.missing_outputs == ["career_application_read"]
    assert "career_application_list" in plan.discouraged_tools
    assert "session_search_artifact" in plan.discouraged_tools

    pending = pending_runtime_plan_from_context_bundle(
        {
            "phase": plan.phase,
            "known_refs": plan.known_refs,
            "missing_outputs": plan.missing_outputs,
            "next_allowed_tools": plan.next_allowed_tools,
            "discouraged_tools": plan.discouraged_tools,
            "final_answer_ready": plan.final_answer_ready,
            "next_action": plan.next_action,
        }
    )

    assert pending is not None
    assert pending["required_tools"] == ["career_application_get"]


def test_runtime_tool_plan_application_action_merges_after_application_read() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "career_application_get",
        """
        {
          "record_type": "career_application",
          "record_id": "application_alpha",
          "record": {
            "application_id": "application_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "jd_analysis_id": "jd_alpha",
            "job_fit_report_id": "fit_alpha",
            "resume_version_ids": ["resume_version_alpha"]
          }
        }
        """,
        previous_pending_plan={
            "phase": "application_action",
            "next_allowed_tools": ["career_application_get"],
            "required_tools": ["career_application_get"],
            "known_refs": {"application_id": "application_alpha"},
            "missing_outputs": ["career_application_read"],
        },
    )

    assert plan is not None
    assert plan["phase"] == "application_action"
    assert plan["next_allowed_tools"] == ["career_application_merge"]
    assert plan["required_tools"] == ["career_application_merge"]
    assert plan["known_refs"]["application_id"] == "application_alpha"
    assert plan["known_refs"]["resume_profile_id"] == "resume_profile_alpha"
    assert plan["known_refs"]["resume_version_ids"] == ["resume_version_alpha"]
    assert "session_create_text_artifact" in plan["discouraged_tools"]


def test_runtime_tool_plan_project_resume_version_creates_after_application_read() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "career_application_get",
        """
        {
          "record_type": "career_application",
          "record_id": "application_alpha",
          "record": {
            "application_id": "application_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "jd_analysis_id": "jd_alpha",
            "job_fit_report_id": "fit_alpha",
            "resume_version_ids": []
          }
        }
        """,
        previous_pending_plan={
            "phase": "resume_version",
            "next_allowed_tools": ["career_application_get"],
            "required_tools": ["career_application_get"],
            "known_refs": {"application_id": "application_alpha"},
            "missing_outputs": [
                "career_application_read",
                "resume_version",
                "career_application_resume_version_link",
            ],
        },
    )

    assert plan is not None
    assert plan["phase"] == "resume_version"
    assert plan["next_allowed_tools"] == ["career_resume_version_create"]
    assert plan["required_tools"] == ["career_resume_version_create"]
    assert plan["missing_outputs"] == ["resume_version", "career_application_resume_version_link"]
    assert plan["known_refs"]["resume_profile_id"] == "resume_profile_alpha"
    assert plan["known_refs"]["jd_analysis_id"] == "jd_alpha"
    assert plan["known_refs"]["job_fit_report_id"] == "fit_alpha"
    assert "career_application_get" in plan["discouraged_tools"]


def test_context_runtime_plan_application_action_requires_merge_after_read() -> None:
    plan = pending_runtime_plan_from_context_bundle(
        {
            "phase": "application_action",
            "known_refs": {"application_id": "application_alpha"},
            "missing_outputs": ["career_application_update"],
            "next_allowed_tools": ["career_application_merge"],
            "discouraged_tools": ["career_application_get", "delegate_agents"],
            "final_answer_ready": False,
            "next_action": "CareerApplication 已读取；只更新当前求职项目。",
        }
    )

    assert plan is not None
    assert plan["required_tools"] == ["career_application_merge"]
    assert plan["next_allowed_tools"] == ["career_application_merge"]


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


def test_job_fit_pending_plan_preserves_profile_refs_until_fit_save() -> None:
    known_refs = {}
    known_refs.update(
        known_refs_from_successful_tool_result(
            "session_read_artifact",
            """
            {
              "artifact_id": "artifact_jd_alpha",
              "title": "JD.txt",
              "content": "岗位要求：Python、RAG。"
            }
            """,
        )
    )
    known_refs.update(
        known_refs_from_successful_tool_result(
            "career_resume_profile_get",
            """
            {
              "record_type": "resume_profile",
              "record_id": "resume_profile_alpha",
              "record": {
                "resume_profile_id": "resume_profile_alpha",
                "source_artifact_id": "artifact_resume_alpha"
              }
            }
            """,
        )
    )
    known_refs.update(
        known_refs_from_successful_tool_result(
            "career_profile_get",
            """
            {
              "record_type": "career_profile",
              "record_id": "career_profile_default",
              "record": {"career_profile_id": "career_profile_default"}
            }
            """,
        )
    )

    plan = pending_runtime_plan_from_successful_tool_result(
        "career_jd_analysis_save",
        """
        {
          "record_type": "jd_analysis",
          "record_id": "jd_alpha",
          "record": {
            "jd_analysis_id": "jd_alpha",
            "source_artifact_id": "artifact_jd_alpha"
          }
        }
        """,
        previous_pending_plan={"known_refs": known_refs},
    )

    assert plan is not None
    assert plan["next_allowed_tools"] == ["session_create_text_artifact"]
    assert plan["known_refs"]["resume_profile_id"] == "resume_profile_alpha"
    assert plan["known_refs"]["career_profile_id"] == "career_profile_default"
    assert plan["known_refs"]["jd_analysis_id"] == "jd_alpha"
    assert plan["known_refs"]["source_artifact_id"] == "artifact_jd_alpha"

    plan = pending_runtime_plan_from_successful_tool_result(
        "session_create_text_artifact",
        """
        {
          "artifact_id": "artifact_fit_report",
          "title": "岗位匹配报告 - AI 应用开发工程师",
          "kind": "generated_file"
        }
        """,
        previous_pending_plan=plan,
    )

    assert plan is not None
    assert plan["next_allowed_tools"] == ["career_job_fit_report_save"]
    hint_payload = hidden_tool_result("session_read_artifact", runtime_plan=plan)
    hint = json.loads(hint_payload.content)["required_tool_call_hint"]
    assert hint["available_args"] == {
        "jd_analysis_id": "jd_alpha",
        "resume_profile_id": "resume_profile_alpha",
        "career_profile_id": "career_profile_default",
        "source_artifact_id": "artifact_jd_alpha",
        "report_artifact_id": "artifact_fit_report",
    }
    assert hint["missing_args"] == []


def test_successful_match_analysis_artifact_title_guides_fit_save_when_jd_is_known() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "session_create_text_artifact",
        """
        {
          "artifact_id": "artifact_fit_report",
          "title": "AI应用开发工程师匹配分析报告",
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


def test_successful_job_fit_report_save_finishes_child_jd_fit_plan() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "career_job_fit_report_save",
        """
        {
          "record_type": "job_fit_report",
          "record_id": "fit_alpha",
          "record": {
            "job_fit_report_id": "fit_alpha",
            "jd_analysis_id": "jd_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "report_artifact_id": "artifact_fit_report"
          }
        }
        """,
        previous_pending_plan={
            "phase": "jd_fit",
            "next_allowed_tools": ["career_job_fit_report_save"],
            "required_tools": ["career_job_fit_report_save"],
            "known_refs": {
                "jd_analysis_id": "jd_alpha",
                "resume_profile_id": "resume_profile_alpha",
                "report_artifact_id": "artifact_fit_report",
            },
            "missing_outputs": ["job_fit_report"],
        },
    )

    assert plan is not None
    assert plan["phase"] == "jd_fit"
    assert plan["final_answer_ready"] is True
    assert plan["next_allowed_tools"] == []
    assert plan["required_tools"] == []
    assert plan["missing_outputs"] == []
    assert plan["known_refs"]["jd_analysis_id"] == "jd_alpha"
    assert plan["known_refs"]["job_fit_report_id"] == "fit_alpha"
    assert plan["known_refs"]["report_artifact_id"] == "artifact_fit_report"
    assert "session_create_text_artifact" in runtime_plan_discouraged_tools(plan)
    assert "career_jd_analysis_save" in runtime_plan_discouraged_tools(plan)


def test_successful_job_fit_report_save_finishes_even_without_pending_plan() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "career_job_fit_report_save",
        """
        {
          "record_type": "job_fit_report",
          "record_id": "fit_alpha",
          "record": {
            "job_fit_report_id": "fit_alpha",
            "jd_analysis_id": "jd_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "report_artifact_id": "artifact_fit_report"
          }
        }
        """,
        previous_pending_plan=None,
    )

    assert plan is not None
    assert plan["phase"] == "jd_fit"
    assert plan["final_answer_ready"] is True
    assert plan["next_allowed_tools"] == []
    assert plan["required_tools"] == []
    assert plan["known_refs"]["job_fit_report_id"] == "fit_alpha"
    assert plan["known_refs"]["jd_analysis_id"] == "jd_alpha"
    assert plan["known_refs"]["resume_profile_id"] == "resume_profile_alpha"
    assert plan["known_refs"]["career_profile_id"] == "career_profile_default"
    assert plan["known_refs"]["report_artifact_id"] == "artifact_fit_report"
    assert "session_create_text_artifact" in runtime_plan_discouraged_tools(plan)
    assert "career_job_fit_report_save" in runtime_plan_discouraged_tools(plan)


def test_merge_pending_runtime_plan_keeps_completed_jd_fit_from_regressing() -> None:
    current = {
        "phase": "jd_fit",
        "next_action": "JDAnalysis 和 JobFitReport 已完成；停止工具调用。",
        "next_allowed_tools": [],
        "required_tools": [],
        "known_refs": {
            "jd_analysis_id": "jd_alpha",
            "job_fit_report_id": "fit_alpha",
            "report_artifact_id": "artifact_fit_report",
        },
        "missing_outputs": [],
        "final_answer_ready": True,
        "discouraged_tools": ["session_create_text_artifact", "career_jd_analysis_save"],
    }
    incoming = {
        "phase": "jd_fit",
        "next_action": "匹配报告 artifact 已创建；下一步只调用 career_jd_analysis_save 保存 JDAnalysis。",
        "next_allowed_tools": ["career_jd_analysis_save"],
        "required_tools": ["career_jd_analysis_save"],
        "known_refs": {"report_artifact_id": "artifact_fit_report"},
        "missing_outputs": ["jd_analysis", "job_fit_report"],
        "discouraged_tools": ["career_job_fit_report_save"],
    }

    merged = merge_pending_runtime_plan(current=current, incoming=incoming)

    assert merged is current
    assert merged["final_answer_ready"] is True
    assert merged["next_allowed_tools"] == []
    assert merged["missing_outputs"] == []


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


def test_successful_delegate_agents_jd_fit_without_application_requirement_finishes() -> None:
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
            "missing_outputs": ["jd_analysis", "job_fit_report"],
        },
    )

    assert plan is not None
    assert plan["phase"] == "jd_fit"
    assert plan["final_answer_ready"] is True
    assert plan["next_allowed_tools"] == []
    assert plan["missing_outputs"] == []
    assert plan["known_refs"]["jd_analysis_id"] == "jd_alpha"
    assert plan["known_refs"]["job_fit_report_id"] == "fit_alpha"


def test_runtime_tool_plan_read_only_retrieval_requires_search_then_context_pack() -> None:
    search_plan = build_runtime_tool_plan(
        workflow_phase=WorkflowPhaseSnapshot(
            phase_name="retrieval_read_only",
            confidence="medium",
            required_outputs=[
                _output("retrieval_search", "retrieval_search"),
                _output("retrieval_context_pack", "retrieval_context_pack"),
            ],
        ),
        career_flow_state=CareerFlowState(),
        workflow_state=CurrentWorkflowState(refs={"application_id": "application_alpha"}),
    )

    assert search_plan.phase == "retrieval_read_only"
    assert search_plan.next_allowed_tools == ["retrieval_search"]
    assert search_plan.required_tools == ["retrieval_search"]
    assert "career_application_merge" in search_plan.discouraged_tools
    assert "memory_write" in search_plan.discouraged_tools

    context_pack_plan = build_runtime_tool_plan(
        workflow_phase=WorkflowPhaseSnapshot(
            phase_name="retrieval_read_only",
            confidence="medium",
            required_outputs=[
                _output("retrieval_search", "retrieval_search", "retrieval_search"),
                _output("retrieval_context_pack", "retrieval_context_pack"),
            ],
        ),
        career_flow_state=CareerFlowState(do_not_repeat_tools=["retrieval_search"]),
        workflow_state=CurrentWorkflowState(refs={"application_id": "application_alpha"}),
    )

    assert context_pack_plan.next_allowed_tools == ["retrieval_context_pack"]
    assert context_pack_plan.required_tools == ["retrieval_context_pack"]
    assert "retrieval_search" in context_pack_plan.discouraged_tools
    assert "career_application_get" in context_pack_plan.discouraged_tools


def test_retrieval_search_success_advances_read_only_plan_to_context_pack() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "retrieval_search",
        '{"query": "二面准备", "count": 2, "hits": []}',
        previous_pending_plan={
            "phase": "retrieval_read_only",
            "next_allowed_tools": ["retrieval_search"],
            "required_tools": ["retrieval_search"],
            "known_refs": {},
            "missing_outputs": ["retrieval_search", "retrieval_context_pack"],
        },
    )

    assert plan is not None
    assert plan["phase"] == "retrieval_read_only"
    assert plan["next_allowed_tools"] == ["retrieval_context_pack"]
    assert plan["required_tools"] == ["retrieval_context_pack"]
    assert plan["missing_outputs"] == ["retrieval_context_pack"]
    assert "retrieval_search" in runtime_plan_discouraged_tools(plan)


def test_retrieval_context_pack_success_finishes_read_only_plan() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "retrieval_context_pack",
        '{"context_pack": []}',
        previous_pending_plan={
            "phase": "retrieval_read_only",
            "next_allowed_tools": ["retrieval_context_pack"],
            "required_tools": ["retrieval_context_pack"],
            "known_refs": {},
            "missing_outputs": ["retrieval_context_pack"],
        },
    )

    assert plan is not None
    assert plan["final_answer_ready"] is True
    assert plan["next_allowed_tools"] == []
    assert plan["missing_outputs"] == []


def test_rag_note_write_plan_requires_retrieval_then_note() -> None:
    search_plan = build_runtime_tool_plan(
        workflow_phase=WorkflowPhaseSnapshot(
            phase_name="rag_note_write",
            confidence="high",
            required_outputs=[
                _output("retrieval_search", "retrieval_search"),
                _output("retrieval_context_pack", "retrieval_context_pack"),
                _output("note", "note_id"),
            ],
        ),
        career_flow_state=CareerFlowState(),
        workflow_state=CurrentWorkflowState(refs={"application_id": "application_alpha"}),
    )

    assert search_plan.phase == "rag_note_write"
    assert search_plan.next_allowed_tools == ["retrieval_search"]
    assert search_plan.required_tools == ["retrieval_search"]
    assert "career_application_merge" in search_plan.discouraged_tools

    context_pack_plan = pending_runtime_plan_from_successful_tool_result(
        "retrieval_search",
        '{"query": "复盘", "count": 1}',
        previous_pending_plan={
            "phase": "rag_note_write",
            "next_allowed_tools": ["retrieval_search"],
            "required_tools": ["retrieval_search"],
            "known_refs": {"application_id": "application_alpha"},
            "missing_outputs": ["retrieval_search", "retrieval_context_pack", "note"],
        },
    )

    assert context_pack_plan is not None
    assert context_pack_plan["next_allowed_tools"] == ["retrieval_context_pack"]
    assert context_pack_plan["missing_outputs"] == ["retrieval_context_pack", "note"]

    note_plan = pending_runtime_plan_from_successful_tool_result(
        "retrieval_context_pack",
        '{"context_pack": []}',
        previous_pending_plan=context_pack_plan,
    )

    assert note_plan is not None
    assert note_plan["final_answer_ready"] is not True
    assert note_plan["next_allowed_tools"] == ["note_create", "note_append"]
    assert note_plan["required_tools"] == ["note_create", "note_append"]
    assert note_plan["missing_outputs"] == ["note"]


def test_direct_note_write_plan_requires_note_create_only() -> None:
    plan = build_runtime_tool_plan(
        workflow_phase=WorkflowPhaseSnapshot(
            phase_name="note_write",
            confidence="high",
            required_outputs=[
                _output("note", "note_id"),
            ],
        ),
        career_flow_state=CareerFlowState(),
        workflow_state=CurrentWorkflowState(),
    )

    assert plan.phase == "note_write"
    assert plan.next_allowed_tools == ["note_create"]
    assert plan.required_tools == ["note_create"]
    assert "retrieval_search" in plan.discouraged_tools
    assert "memory_write" in plan.discouraged_tools


def test_rag_note_write_finalizes_only_after_note_write() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "note_create",
        '{"record_type": "note", "record_id": "note_alpha", "record": {"note_id": "note_alpha"}}',
        previous_pending_plan={
            "phase": "rag_note_write",
            "next_allowed_tools": ["note_create", "note_append"],
            "required_tools": ["note_create", "note_append"],
            "known_refs": {"application_id": "application_alpha"},
            "missing_outputs": ["note"],
        },
    )

    assert plan is not None
    assert plan["final_answer_ready"] is True
    assert plan["missing_outputs"] == []
    assert plan["known_refs"]["note_id"] == "note_alpha"


def test_learning_task_action_finalizes_only_after_task_create() -> None:
    task_plan = pending_runtime_plan_from_successful_tool_result(
        "retrieval_context_pack",
        '{"context_pack": []}',
        previous_pending_plan={
            "phase": "rag_learning_task_create",
            "next_allowed_tools": ["retrieval_context_pack"],
            "required_tools": ["retrieval_context_pack"],
            "known_refs": {},
            "missing_outputs": ["retrieval_context_pack", "learning_task"],
        },
    )

    assert task_plan is not None
    assert task_plan["next_allowed_tools"] == ["learning_task_create"]
    assert task_plan["missing_outputs"] == ["learning_task"]

    final_plan = pending_runtime_plan_from_successful_tool_result(
        "learning_task_create",
        (
            '{"record_type": "learning_task", "record_id": "learning_task_alpha", '
            '"record": {"learning_task_id": "learning_task_alpha"}}'
        ),
        previous_pending_plan=task_plan,
    )

    assert final_plan is not None
    assert final_plan["final_answer_ready"] is True
    assert final_plan["known_refs"]["learning_task_id"] == "learning_task_alpha"


def test_interview_review_requires_note_then_application_update() -> None:
    application_plan = pending_runtime_plan_from_successful_tool_result(
        "note_create",
        '{"record_type": "note", "record_id": "note_review", "record": {"note_id": "note_review"}}',
        previous_pending_plan={
            "phase": "interview_review_update",
            "next_allowed_tools": ["note_create", "note_append"],
            "required_tools": ["note_create", "note_append"],
            "known_refs": {"application_id": "application_alpha"},
            "missing_outputs": ["note", "career_application_update"],
        },
    )

    assert application_plan is not None
    assert application_plan["next_allowed_tools"] == ["career_application_merge"]
    assert application_plan["required_tools"] == ["career_application_merge"]
    assert application_plan["missing_outputs"] == ["career_application_update"]
    assert application_plan["known_refs"]["note_id"] == "note_review"

    final_plan = pending_runtime_plan_from_successful_tool_result(
        "career_application_merge",
        (
            '{"record_type": "career_application", "record_id": "application_alpha", '
            '"record": {"application_id": "application_alpha"}}'
        ),
        previous_pending_plan=application_plan,
    )

    assert final_plan is not None
    assert final_plan["final_answer_ready"] is True
    assert final_plan["known_refs"]["application_id"] == "application_alpha"


def test_turn_intent_boundary_ignores_artifact_preview_and_fact_rules() -> None:
    boundary = build_turn_intent_boundary(
        """
        你收到一个来自 agent_main 的子任务。

        instruction:
        请保存结构化 ResumeProfile，并创建诊断报告 artifact。
        不要创建求职项目，不要生成定制简历。
        JD 中提到了向量检索，但这只是岗位要求，不代表本轮只读。

        artifact_refs:
        - artifact_resume

        artifact 事实源规则:
        - 保存产品记录时，不要写入 artifact 中未出现的信息。

        artifact 内容预览:
        技能：RAG、Agent 工具调用
        """
    )

    assert boundary.read_only is False
    assert boundary.forbid_career_application_create is True
    assert boundary.forbid_resume_version_create is True


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


def test_failed_delegate_agents_does_not_advance_from_child_answer_refs() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "delegate_agents",
        """
        {
          "status": "failed",
          "results": [
            {
              "target_agent_id": "job_agent",
              "status": "failed",
              "summary": "job_agent JD 匹配子任务未完成：缺少 job_fit_report, report_artifact。",
              "answer": "我已保存 JDAnalysis jd_fake 和 JobFitReport fit_fake，报告 artifact_fake。",
              "product_refs": ["resume_profile_alpha", "career_profile_default"],
              "output_artifact_refs": []
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

    assert plan is None


def test_successful_delegate_agents_ignores_career_application_save_as_application_ref() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "delegate_agents",
        """
        {
          "status": "completed",
          "results": [
            {
              "target_agent_id": "job_agent",
              "status": "completed",
              "summary": "JDAnalysis `jd_b19176f42293` 和 JobFitReport `fit_ed9e2a3e5698` 已完成。`career_application_save` 工具不在本 agent 工具范围内，需由 main agent 完成。",
              "output_artifact_refs": ["artifact_96e9325eeaab"],
              "product_refs": ["jd_b19176f42293", "resume_profile_zhang3_006", "career_profile_default", "fit_ed9e2a3e5698"]
            }
          ]
        }
        """,
        previous_pending_plan={
            "phase": "jd_fit",
            "next_allowed_tools": ["delegate_agents"],
            "required_tools": ["delegate_agents"],
            "known_refs": {"resume_profile_id": "resume_profile_zhang3_006"},
            "missing_outputs": ["jd_analysis", "job_fit_report", "career_application"],
        },
    )

    assert plan is not None
    assert plan["next_allowed_tools"] == ["career_application_create"]
    assert "application_id" not in plan["known_refs"]
    assert plan["known_refs"]["jd_analysis_id"] == "jd_b19176f42293"
    assert plan["known_refs"]["job_fit_report_id"] == "fit_ed9e2a3e5698"


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


def test_successful_resume_read_requires_diagnosis_artifact_before_profile_save() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "session_read_artifact",
        """
        {
          "artifact_id": "artifact_resume",
          "title": "候选人简历.txt",
          "runtime_plan_applied": true,
          "runtime_plan_phase": "resume_diagnosis",
          "runtime_next_allowed_tools": ["session_create_text_artifact"],
          "required_tools": ["session_create_text_artifact"],
          "runtime_known_refs": {
            "source_artifact_id": "artifact_resume",
            "resume_source_artifact_id": "artifact_resume"
          },
          "runtime_missing_outputs": ["diagnosis_artifact", "resume_profile"],
          "runtime_next_action": "先创建简历诊断 artifact。"
        }
        """,
        previous_pending_plan=None,
    )

    assert plan is not None
    assert plan["phase"] == "resume_diagnosis"
    assert plan["next_allowed_tools"] == ["session_create_text_artifact"]
    assert plan["required_tools"] == ["session_create_text_artifact"]
    assert plan["missing_outputs"] == ["diagnosis_artifact", "resume_profile"]
    assert plan["known_refs"]["resume_source_artifact_id"] == "artifact_resume"


def test_successful_resume_diagnosis_artifact_requires_profile_save_when_profile_missing() -> None:
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
            "known_refs": {"resume_source_artifact_id": "artifact_resume"},
            "missing_outputs": ["diagnosis_artifact", "resume_profile"],
        },
    )

    assert plan is not None
    assert plan.get("final_answer_ready") is not True
    assert plan["next_allowed_tools"] == ["career_resume_profile_save"]
    assert plan["required_tools"] == ["career_resume_profile_save"]
    assert plan["missing_outputs"] == ["resume_profile"]
    assert plan["known_refs"]["diagnosis_artifact_id"] == "artifact_diagnosis"


def test_successful_resume_diagnosis_artifact_uses_runtime_step_not_title_guess() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "session_create_text_artifact",
        """
        {
          "artifact_id": "artifact_diagnosis",
          "title": "resume_diagnosis_artifact_resume_live_001.md",
          "kind": "generated_file"
        }
        """,
        previous_pending_plan={
            "phase": "resume_diagnosis",
            "next_allowed_tools": ["session_create_text_artifact"],
            "required_tools": ["session_create_text_artifact"],
            "known_refs": {"resume_source_artifact_id": "artifact_resume"},
            "missing_outputs": ["diagnosis_artifact", "resume_profile"],
        },
    )

    assert plan is not None
    assert plan["next_allowed_tools"] == ["career_resume_profile_save"]
    assert plan["required_tools"] == ["career_resume_profile_save"]
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
    assert "delegate_agents" in runtime_plan_discouraged_tools(plan)


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


def test_successful_application_merge_finalizes_resume_version_plan() -> None:
    plan = pending_runtime_plan_from_successful_tool_result(
        "career_application_merge",
        """
        {
          "record_type": "career_application",
          "record_id": "application_alpha",
          "record": {
            "application_id": "application_alpha",
            "resume_version_ids": ["resume_version_alpha"]
          }
        }
        """,
        previous_pending_plan={
            "phase": "resume_version",
            "next_allowed_tools": ["career_application_merge"],
            "required_tools": ["career_application_merge"],
            "known_refs": {
                "application_id": "application_alpha",
                "resume_version_id": "resume_version_alpha",
                "artifact_id": "artifact_resume_version"
            },
            "missing_outputs": ["career_application_resume_version_link"],
        },
    )

    assert plan is not None
    assert plan["phase"] == "resume_version"
    assert plan["final_answer_ready"] is True
    assert plan["next_allowed_tools"] == []
    assert plan["required_tools"] == []
    assert plan["missing_outputs"] == []
    assert plan["known_refs"]["application_id"] == "application_alpha"
    assert plan["known_refs"]["resume_version_id"] == "resume_version_alpha"
    assert "career_application_merge" in runtime_plan_discouraged_tools(plan)
    assert "career_resume_version_create" in runtime_plan_discouraged_tools(plan)


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
