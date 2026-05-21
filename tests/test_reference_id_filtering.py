"""Tests for reserved reference-id filtering."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.career.models import validate_evidence_refs
from app.core.errors import ValidationError
from app.domain.models import EventRecord, RunContext
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


def test_evidence_ref_validation_rejects_reserved_tool_like_refs() -> None:
    with pytest.raises(ValidationError, match="invalid reference format"):
        validate_evidence_refs(["career_profile_merge"])
    with pytest.raises(ValidationError, match="invalid reference format"):
        validate_evidence_refs(["resume_profile_and_diagnosis_ready_stop_low_level_actions"])

    assert validate_evidence_refs(["career_profile_default", "jd_alpha"]) == [
        "career_profile_default",
        "jd_alpha",
    ]
