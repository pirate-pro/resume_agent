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


def _graph_context(task_id: str) -> RunContext:
    return RunContext(
        session_id="sess_policy",
        run_id=f"run_{task_id}",
        agent_id="resume_agent",
        turn_id=f"turn_{task_id}",
        entry_agent_id="agent_main",
        parent_run_id="run_parent",
        task_id=task_id,
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


def test_graph_retry_attempts_use_distinct_product_write_keys() -> None:
    call = ToolCall(
        name="career_resume_profile_save",
        arguments={"source_artifact_id": "artifact_resume"},
    )
    plan = {
        "phase": "resume_analysis",
        "required_tools": ["career_resume_profile_save"],
        "missing_outputs": ["resume_profile_id"],
    }

    first = tool_idempotency_key(
        call,
        _graph_context("graph_task_attempt_1"),
        pending_runtime_plan=plan,
    )
    repeated = tool_idempotency_key(
        call,
        _graph_context("graph_task_attempt_1"),
        pending_runtime_plan=plan,
    )
    retried = tool_idempotency_key(
        call,
        _graph_context("graph_task_attempt_2"),
        pending_runtime_plan=plan,
    )

    assert first == repeated
    assert first != retried
    assert "graph_task_attempt_1" in (first or "")
    assert "graph_task_attempt_2" in (retried or "")


def test_graph_text_artifact_is_scoped_to_attempt() -> None:
    call = ToolCall(
        name="session_create_text_artifact",
        arguments={
            "title": "简历诊断报告.md",
            "content": "诊断内容",
            "kind": "generated_file",
        },
    )
    plan = {
        "phase": "resume_analysis",
        "required_tools": ["session_create_text_artifact"],
        "missing_outputs": ["diagnosis_artifact_id", "resume_profile_id"],
    }

    key = tool_idempotency_key(
        call,
        _graph_context("graph_task_attempt_2"),
        pending_runtime_plan=plan,
    )

    assert key == (
        "session_create_text_artifact:sess_policy:graph_task_attempt_2:resume_diagnosis"
    )


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


def test_text_artifact_idempotency_scopes_job_fit_report_by_jd_source() -> None:
    call = ToolCall(
        name="session_create_text_artifact",
        arguments={
            "title": "岗位匹配报告 - AI 应用开发工程师",
            "content": "候选人 Python/FastAPI 匹配，向量检索写入差距。",
            "kind": "generated_file",
        },
    )

    key = tool_idempotency_key(
        call,
        _context(),
        pending_runtime_plan={
            "phase": "jd_fit",
            "required_tools": ["session_create_text_artifact"],
            "missing_outputs": ["job_fit_report_artifact", "job_fit_report"],
            "known_refs": {"jd_source_artifact_id": "artifact_jd_alpha"},
        },
    )

    assert key == (
        "session_create_text_artifact:sess_policy:run_policy:jd=artifact_jd_alpha:job_fit_report"
    )


def test_note_create_idempotency_canonicalizes_reference_aliases() -> None:
    first = ToolCall(
        name="note_create",
        arguments={
            "title": "面试准备",
            "body_markdown": "复习 RAG chunk 策略。",
            "related_application_id": "application_alpha",
            "evidence_refs": [
                "application:application_alpha",
                "job_fit_report:fit_alpha",
            ],
            "source_refs": [
                {"source_type": "jd", "source_id": "jd_alpha"},
            ],
        },
    )
    second = ToolCall(
        name="note_create",
        arguments={
            "title": "面试准备",
            "body_markdown": "复习 RAG chunk 策略。",
            "related_application_id": "application_alpha",
            "evidence_refs": [
                "application_alpha",
                "fit_alpha",
            ],
            "source_refs": [
                {"source_type": "jd_analysis", "source_id": "jd_alpha"},
            ],
        },
    )

    assert tool_idempotency_key(first, _context()) == tool_idempotency_key(second, _context())


def test_policy_marks_read_only_cacheable() -> None:
    call = ToolCall(name="career_application_get", arguments={"application_id": "application_a"})
    policy = resolve_tool_execution_policy(call, _context())

    assert policy.kind == "read_only"
    assert policy.cacheable is True
    assert policy.input_hash is not None
