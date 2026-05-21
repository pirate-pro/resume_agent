"""Tests for deterministic career flow state extraction."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.models import EventRecord, RunContext
from app.runtime.context.career_flow_state import extract_career_flow_state, format_career_flow_state_lines
from app.runtime.context.models import CurrentWorkflowState

__all__ = []


def _context(session_id: str = "sess_career_flow") -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id="run_current",
        agent_id="agent_main",
        turn_id="turn_current",
        entry_agent_id="agent_main",
    )


def _tool_result(
    *,
    index: int,
    tool_name: str,
    content: dict[str, Any],
    run_id: str = "run_current",
) -> EventRecord:
    return EventRecord(
        event_id=f"evt_{index}",
        session_id="sess_career_flow",
        agent_id="agent_main",
        run_id=run_id,
        type="tool_result",
        payload={
            "tool_name": tool_name,
            "success": True,
            "content": json.dumps(content, ensure_ascii=False),
            "tool_call_id": f"call_{index}",
        },
        created_at=datetime(2026, 5, 19, 12, 0, tzinfo=UTC) + timedelta(seconds=index),
    )


def test_extract_career_flow_state_marks_completed_resume_version_flow() -> None:
    events = [
        _tool_result(
            index=1,
            tool_name="career_application_get",
            content={
                "record_type": "career_application",
                "record_id": "application_alpha",
                "record": {
                    "application_id": "application_alpha",
                    "resume_profile_id": "resume_profile_alpha",
                    "career_profile_id": "career_profile_default",
                    "jd_analysis_id": "jd_alpha",
                    "job_fit_report_id": "fit_alpha",
                    "resume_version_ids": ["resume_version_old"],
                    "source_artifact_id": "artifact_jd_alpha",
                },
            },
        ),
        _tool_result(
            index=2,
            tool_name="career_resume_version_create",
            content={
                "record_type": "resume_version",
                "record_id": "resume_version_new",
                "source_artifact_id": "artifact_resume_version_new",
                "record": {
                    "resume_version_id": "resume_version_new",
                    "base_resume_profile_id": "resume_profile_alpha",
                    "target_jd_analysis_id": "jd_alpha",
                    "artifact_id": "artifact_resume_version_new",
                },
            },
        ),
        _tool_result(
            index=3,
            tool_name="career_application_merge",
            content={
                "record_type": "career_application",
                "record_id": "application_alpha",
                "record": {
                    "application_id": "application_alpha",
                    "resume_version_ids": ["resume_version_old", "resume_version_new"],
                },
            },
        ),
    ]

    state = extract_career_flow_state(
        events,
        _context(),
        user_message="请基于 application_alpha 生成或更新一版定制简历",
        workflow_state=CurrentWorkflowState(),
    )
    lines = format_career_flow_state_lines(state)

    assert state.refs["application_id"] == "application_alpha"
    assert state.refs["resume_profile_id"] == "resume_profile_alpha"
    assert state.refs["jd_analysis_id"] == "jd_alpha"
    assert state.refs["job_fit_report_id"] == "fit_alpha"
    assert state.multi_refs["resume_version_ids"] == ["resume_version_old", "resume_version_new"]
    assert state.final_answer_ready is True
    assert "resume_version" in state.completed_steps
    assert "career_resume_version_create" in state.do_not_repeat_tools
    assert "career_jd_analysis_get" in state.do_not_repeat_tools
    assert any("resume_version_fact_policy=" in line for line in lines)
    assert any("resume_version_retry_policy=" in line for line in lines)
    assert any("- next_action=定制简历已创建并合并进求职项目，应直接给最终答复。" == line for line in lines)


def test_extract_career_flow_state_ignores_runtime_block_as_product_output() -> None:
    state = extract_career_flow_state(
        [
            _tool_result(
                index=1,
                tool_name="career_resume_version_create",
                content={
                    "workflow_runtime_result": True,
                    "policy": "block",
                    "tool_executed": False,
                    "reason": "resume_version_missing_career_application",
                    "next_action": "先创建 CareerApplication。",
                },
            )
        ],
        _context(),
        user_message="请基于 application_alpha 生成或更新一版定制简历",
        workflow_state=CurrentWorkflowState(
            refs={
                "application_id": "application_alpha",
                "resume_profile_id": "resume_profile_alpha",
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
            }
        ),
    )

    assert "resume_version" not in state.completed_steps
    assert state.missing_steps == ["resume_version"]
    assert "resume_version_ids" not in state.multi_refs
    assert "career_resume_version_create" not in state.do_not_repeat_tools
    assert state.final_answer_ready is False


def test_extract_career_flow_state_skips_plain_chat_without_refs() -> None:
    state = extract_career_flow_state(
        [],
        _context("sess_plain"),
        user_message="你好，今天上海天气怎么样",
        workflow_state=CurrentWorkflowState(),
    )

    assert state.is_empty()


def test_extract_career_flow_state_ignores_child_agent_context() -> None:
    context = RunContext(
        session_id="sess_child",
        run_id="run_current",
        agent_id="resume_agent",
        turn_id="turn_current",
        entry_agent_id="agent_main",
    )

    state = extract_career_flow_state(
        [
            _tool_result(
                index=1,
                tool_name="career_resume_profile_save",
                content={
                    "record_type": "resume_profile",
                    "record_id": "resume_profile_alpha",
                },
            )
        ],
        context,
        user_message="解析简历",
        workflow_state=CurrentWorkflowState(),
    )

    assert state.is_empty()
