"""Tests for workflow tool policy and idempotency."""

from __future__ import annotations

from app.domain.models import RunContext, ToolCall
from app.runtime.workflow.tool_idempotency import tool_idempotency_key
from app.runtime.workflow.tool_policy import canonical_tool_input_hash, resolve_tool_execution_policy


def _context() -> RunContext:
    return RunContext(
        session_id="sess_policy",
        run_id="run_policy",
        agent_id="agent_main",
        turn_id="turn_policy",
        entry_agent_id="agent_main",
    )


def test_read_only_tool_hash_is_stable_and_ignores_dict_order() -> None:
    first = canonical_tool_input_hash(
        "career_application_get",
        {"application_id": "application_a", "extra": {"b": 2, "a": 1}},
    )
    second = canonical_tool_input_hash(
        "career_application_get",
        {"extra": {"a": 1, "b": 2}, "application_id": "application_a"},
    )

    assert first == second


def test_large_content_is_hashed_not_embedded_in_fingerprint() -> None:
    long_content = "x" * 2000
    digest = canonical_tool_input_hash("session_read_artifact", {"content": long_content})

    assert len(digest) == 64
    assert long_content not in digest


def test_idempotency_key_uses_business_natural_key() -> None:
    call = ToolCall(
        name="career_job_fit_report_save",
        arguments={"jd_analysis_id": "jd_a", "resume_profile_id": "resume_a"},
    )

    assert (
        tool_idempotency_key(call, _context())
        == "career_job_fit_report_save:sess_policy:jd_analysis_id=jd_a|resume_profile_id=resume_a"
    )


def test_text_artifact_idempotency_uses_runtime_plan_before_content_guess() -> None:
    call = ToolCall(
        name="session_create_text_artifact",
        arguments={
            "title": "resume_diagnosis_artifact_resume_live_001.md",
            "content": "项目经历包含岗位匹配报告能力，但本文件是简历诊断报告。",
            "kind": "generated_file",
        },
    )

    key = tool_idempotency_key(
        call,
        _context(),
        pending_runtime_plan={
            "phase": "resume_diagnosis",
            "next_allowed_tools": ["session_create_text_artifact"],
            "required_tools": ["session_create_text_artifact"],
            "missing_outputs": ["diagnosis_artifact", "resume_profile"],
        },
    )

    assert key == "session_create_text_artifact:sess_policy:run_policy:resume_diagnosis"


def test_text_artifact_idempotency_classifies_ascii_resume_diagnosis_title() -> None:
    call = ToolCall(
        name="session_create_text_artifact",
        arguments={
            "title": "resume_diagnosis_artifact_resume_live_001.md",
            "content": "候选人项目支持岗位匹配报告。",
            "kind": "generated_file",
        },
    )

    assert tool_idempotency_key(call, _context()) == (
        "session_create_text_artifact:sess_policy:run_policy:resume_diagnosis"
    )


def test_policy_marks_read_only_cacheable() -> None:
    call = ToolCall(name="career_application_get", arguments={"application_id": "application_a"})
    policy = resolve_tool_execution_policy(call, _context())

    assert policy.kind == "read_only"
    assert policy.cacheable is True
    assert policy.input_hash is not None
