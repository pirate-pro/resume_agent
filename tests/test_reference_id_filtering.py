"""Tests for reserved reference-id filtering."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.career.models import validate_evidence_refs
from app.core.errors import ValidationError
from app.domain.models import EventRecord, RunContext
from app.runtime.agent_events import AGENT_RESULT_SUMMARY_EVENT
from app.runtime.context.career_flow_state import extract_career_flow_state
from app.runtime.context.models import CurrentWorkflowState
from app.runtime.context.workflow_state import extract_current_workflow_state

__all__ = []


def _context() -> RunContext:
    return RunContext(
        session_id="sess_refs",
        run_id="run_current",
        agent_id="agent_main",
        turn_id="turn_current",
        entry_agent_id="agent_main",
    )


def _tool_result(content: dict[str, object], *, tool_name: str = "tool_search") -> EventRecord:
    return EventRecord(
        event_id="evt_tool_result",
        session_id="sess_refs",
        agent_id="agent_main",
        run_id="run_current",
        type="tool_result",
        payload={
            "tool_name": tool_name,
            "success": True,
            "content": json.dumps(content, ensure_ascii=False),
            "tool_call_id": "call_refs",
        },
        created_at=datetime.now(UTC),
    )


def test_current_workflow_state_ignores_tool_names_that_match_id_prefixes() -> None:
    state = extract_current_workflow_state(
        [
            _tool_result(
                {
                    "event_type": "tool_schema_not_revealed",
                    "tool_name": "career_profile_merge",
                    "message": (
                        "请先搜索 career_profile_get 或 career_profile_merge。"
                        "原因 resume_profile_and_diagnosis_ready_stop_low_level_actions。"
                    ),
                },
                tool_name="career_profile_merge",
            )
        ],
        _context(),
    )

    assert "career_profile_id" not in state.refs
    assert "resume_profile_id" not in state.refs


def test_career_flow_state_ignores_reserved_refs_from_summary_text() -> None:
    state = extract_career_flow_state(
        [
            _tool_result(
                {
                    "record_type": "career_application",
                    "record_id": "application_alpha",
                    "summary": "career_profile_merge 是工具名，不是职业画像；有效记录是 career_profile_default。",
                },
                tool_name="career_application_get",
            )
        ],
        _context(),
        user_message="继续这个求职项目",
        workflow_state=CurrentWorkflowState(),
    )

    assert state.refs["application_id"] == "application_alpha"
    assert state.refs["career_profile_id"] == "career_profile_default"


def test_career_flow_state_ignores_action_like_career_profile_update_ref() -> None:
    state = extract_career_flow_state(
        [
            _tool_result(
                {
                    "summary": (
                        "resume_profile_id: resume_profile_real; "
                        "career_profile_update: 未执行；有效记录是 career_profile_default。"
                    ),
                    "product_refs": ["resume_profile_real", "career_profile_update"],
                },
                tool_name="delegate_agents",
            )
        ],
        _context(),
        user_message="继续求职任务",
        workflow_state=CurrentWorkflowState(),
    )

    assert state.refs["resume_profile_id"] == "resume_profile_real"
    assert state.refs.get("career_profile_id") != "career_profile_update"


def test_resume_version_artifact_like_text_is_not_product_ref() -> None:
    events = [
        _tool_result(
            {
                "summary": (
                    "错误示例：resume_version_artifact_5afb45ee8291 只是伪造字符串，"
                    "不是真实 ResumeVersion；有效项目是 application_alpha。"
                ),
                "product_refs": ["application_alpha", "resume_version_artifact_5afb45ee8291"],
            },
            tool_name="delegate_agents",
        )
    ]

    workflow_state = extract_current_workflow_state(events, _context())
    career_state = extract_career_flow_state(
        events,
        _context(),
        user_message="请生成定制简历版本",
        workflow_state=CurrentWorkflowState(refs={"application_id": "application_alpha"}),
    )

    assert "resume_version_id" not in workflow_state.refs
    assert "resume_version_ids" not in career_state.multi_refs
    assert career_state.missing_steps == ["resume_version"]


def test_failed_delegate_result_text_refs_do_not_become_workflow_refs() -> None:
    failed_delegate = _tool_result(
        {
            "status": "failed",
            "results": [
                {
                    "target_agent_id": "job_agent",
                    "status": "failed",
                    "summary": "job_agent JD 匹配子任务未完成：缺少 job_fit_report, report_artifact。",
                    "answer": "我已保存 JDAnalysis jd_fake_hallucinated 和 JobFitReport fit_fake_hallucinated。",
                    "product_refs": ["resume_profile_real", "career_profile_default"],
                    "output_artifact_refs": [],
                }
            ],
        },
        tool_name="delegate_agents",
    )
    stale_child_summary = EventRecord(
        event_id="evt_child_summary",
        session_id="sess_refs",
        agent_id="job_agent",
        run_id="run_child",
        parent_run_id="run_current",
        type=AGENT_RESULT_SUMMARY_EVENT,
        payload={
            "task_id": "task_job",
            "source_agent_id": "job_agent",
            "target_agent_id": "agent_main",
            "status": "completed",
            "summary": "我已保存 JDAnalysis jd_fake_summary 和 JobFitReport fit_fake_summary。",
            "artifact_refs": ["artifact_jd_input"],
            "output_artifact_refs": [],
            "product_refs": ["resume_profile_real", "career_profile_default"],
        },
        created_at=datetime.now(UTC),
    )
    events = [failed_delegate, stale_child_summary]

    workflow_state = extract_current_workflow_state(events, _context())
    career_state = extract_career_flow_state(
        events,
        _context(),
        user_message="请分析 JD 并生成岗位匹配报告",
        workflow_state=CurrentWorkflowState(refs={"resume_profile_id": "resume_profile_real"}),
    )

    assert "jd_analysis_id" not in workflow_state.refs
    assert "job_fit_report_id" not in workflow_state.refs
    assert "jd_analysis_id" not in career_state.refs
    assert "job_fit_report_id" not in career_state.refs
    assert career_state.missing_steps == ["jd_analysis", "job_fit_report"]


def test_evidence_ref_validation_rejects_reserved_tool_like_refs() -> None:
    with pytest.raises(ValidationError, match="invalid reference format"):
        validate_evidence_refs(["career_profile_merge"])
    with pytest.raises(ValidationError, match="invalid reference format"):
        validate_evidence_refs(["resume_profile_and_diagnosis_ready_stop_low_level_actions"])
    with pytest.raises(ValidationError, match="invalid reference format"):
        validate_evidence_refs(["resume_version_artifact_5afb45ee8291"])

    assert validate_evidence_refs(["career_profile_default", "jd_alpha"]) == [
        "career_profile_default",
        "jd_alpha",
    ]
