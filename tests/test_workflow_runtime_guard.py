"""Tests for deterministic career workflow runtime guard."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.career.models import (
    CareerApplication,
    CareerProfile,
    CareerRecordStatus,
    JDAnalysis,
    JobFitReport,
    ResumeProfile,
    ResumeVersion,
)
from app.career.store import CareerProductStore
from app.domain.models import EventRecord, RunContext, SessionArtifact, ToolCall
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.runtime.workflow import WorkflowRuntimeGuard

__all__ = []


def _now() -> datetime:
    return datetime(2026, 5, 19, 12, 0, tzinfo=UTC)


def _context(session_id: str = "sess_guard", run_id: str = "run_guard") -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=run_id,
        agent_id="agent_main",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )


def _append_user_message(repo: JsonlSessionRepository, context: RunContext, content: str) -> None:
    repo.append_event(
        context.session_id,
        EventRecord(
            event_id=f"evt_user_{context.run_id}",
            session_id=context.session_id,
            type="user_message",
            payload={"content": content},
            created_at=_now(),
            agent_id=context.agent_id,
            run_id=context.run_id,
        ),
    )


def _append_tool_result(
    repo: JsonlSessionRepository,
    context: RunContext,
    *,
    tool_name: str,
    content: dict[str, object] | None = None,
) -> None:
    repo.append_event(
        context.session_id,
        EventRecord(
            event_id=f"evt_tool_{tool_name}_{context.run_id}",
            session_id=context.session_id,
            type="tool_result",
            payload={
                "tool_name": tool_name,
                "success": True,
                "tool_call_id": f"call_{tool_name}",
                "content": json.dumps(content or {"ok": True}, ensure_ascii=False),
            },
            created_at=_now(),
            agent_id=context.agent_id,
            run_id=context.run_id,
        ),
    )


def _store(tmp_path: Path) -> CareerProductStore:
    return CareerProductStore(root_dir=tmp_path / "career", clock=_now)


def _repo(tmp_path: Path, session_id: str = "sess_guard") -> JsonlSessionRepository:
    repo = JsonlSessionRepository(data_dir=tmp_path / "sessions")
    repo.create_session(session_id)
    return repo


def _guard(tmp_path: Path) -> tuple[WorkflowRuntimeGuard, CareerProductStore, JsonlSessionRepository]:
    store = _store(tmp_path)
    repo = _repo(tmp_path)
    return WorkflowRuntimeGuard(career_store=store, session_repository=repo), store, repo


def _resume_profile(record_id: str = "resume_profile_real", *, skills: list[str] | None = None) -> ResumeProfile:
    return ResumeProfile(
        resume_profile_id=record_id,
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_guard",
        source_artifact_id="artifact_resume",
        evidence_refs=["artifact_resume"],
        created_at=_now(),
        updated_at=_now(),
        basic_info={"name": "张明"},
        skills=skills or ["Python", "FastAPI"],
    )


def _career_profile(record_id: str = "career_profile_default") -> CareerProfile:
    return CareerProfile(
        career_profile_id=record_id,
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_guard",
        source_artifact_id="artifact_resume",
        evidence_refs=["artifact_resume", "resume_profile_real"],
        created_at=_now(),
        updated_at=_now(),
        target_roles=["AI Agent 后端工程师"],
    )


def _jd_analysis(record_id: str = "jd_real") -> JDAnalysis:
    return JDAnalysis(
        jd_analysis_id=record_id,
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_guard",
        source_artifact_id="artifact_jd",
        evidence_refs=["artifact_jd"],
        created_at=_now(),
        updated_at=_now(),
        company="星河智能",
        position="AI Agent 后端工程师",
        required_skills=["Python", "RAG"],
    )


def _fit_report(record_id: str = "fit_real") -> JobFitReport:
    return JobFitReport(
        job_fit_report_id=record_id,
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_guard",
        source_artifact_id="artifact_jd",
        evidence_refs=["artifact_jd", "resume_profile_real", "jd_real", "career_profile_default"],
        created_at=_now(),
        updated_at=_now(),
        jd_analysis_id="jd_real",
        resume_profile_id="resume_profile_real",
        career_profile_id="career_profile_default",
        overall_score=76,
        score_breakdown={"skills": 80},
        matched_evidence=["Python 后端经验"],
        gaps=["RAG 深度实践需要补充"],
        recommendation="cautious",
        report_artifact_id="artifact_fit_report",
    )


def _resume_version(record_id: str = "resume_version_real") -> ResumeVersion:
    return ResumeVersion(
        resume_version_id=record_id,
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_guard",
        source_artifact_id="artifact_resume_version",
        evidence_refs=["artifact_resume_version", "resume_profile_real", "jd_real"],
        created_at=_now(),
        updated_at=_now(),
        base_resume_profile_id="resume_profile_real",
        target_jd_analysis_id="jd_real",
        title="星河智能定制简历",
        format="markdown",
        artifact_id="artifact_resume_version",
        change_summary=["强化 RAG 项目"],
    )


def _application(record_id: str = "application_real") -> CareerApplication:
    return CareerApplication(
        application_id=record_id,
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_guard",
        source_artifact_id="artifact_jd",
        evidence_refs=["artifact_jd", "resume_profile_real", "jd_real", "fit_real"],
        created_at=_now(),
        updated_at=_now(),
        company="星河智能",
        position="AI Agent 后端工程师",
        stage="ready_to_apply",
        priority="high",
        resume_profile_id="resume_profile_real",
        career_profile_id="career_profile_default",
        jd_analysis_id="jd_real",
        job_fit_report_id="fit_real",
        summary="建议谨慎投递。",
    )


def test_resume_profile_save_reuses_same_source_artifact(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())

    decision = guard.inspect(
        ToolCall(
            name="career_resume_profile_save",
            arguments={"source_artifact_id": "artifact_resume", "resume_profile_id": "resume_profile_duplicate"},
            tool_call_id="call_resume_profile",
        ),
        _context(),
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["record_id"] == "resume_profile_real"
    assert payload["idempotent_reused"] is True
    assert payload["policy"] == "reuse"
    assert decision.event_payload is not None
    assert decision.event_payload["record_type"] == "resume_profile"


def test_session_create_text_artifact_blocks_empty_content_as_noop(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    repo.add_or_update_session_artifact(
        SessionArtifact(
            artifact_id="artifact_existing",
            session_id="sess_guard",
            kind="generated_file",
            title="已有报告.md",
            media_type="text/markdown",
            size_bytes=12,
            status="ready",
            visibility="user_visible",
            created_at=_now(),
            updated_at=_now(),
            storage_relpath="artifacts/artifact_existing/original.bin",
            text_relpath="artifacts/artifact_existing/content.txt",
        )
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={"title": "空报告.md", "content": "   ", "kind": "generated_file"},
            tool_call_id="call_empty_artifact",
        ),
        _context(),
    )

    assert decision.result is not None
    assert decision.result.success is True
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["skipped"] is True
    assert payload["reason"] == "empty_content"
    assert payload["recent_artifacts"][0]["artifact_id"] == "artifact_existing"
    assert decision.event_payload is not None
    assert decision.event_payload["reason"] == "empty_content"


def test_child_agent_cannot_create_pasted_text_artifact(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    repo.add_or_update_session_artifact(
        SessionArtifact(
            artifact_id="artifact_resume",
            session_id="sess_guard",
            kind="uploaded_file",
            title="候选人简历.txt",
            media_type="text/plain",
            size_bytes=12,
            status="ready",
            visibility="session_shared",
            created_at=_now(),
            updated_at=_now(),
            storage_relpath="artifacts/artifact_resume/original.bin",
            text_relpath="artifacts/artifact_resume/content.txt",
        )
    )
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child",
        agent_id="resume_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={"title": "伪造简历.txt", "content": "姓名：张三", "kind": "pasted_text"},
            tool_call_id="call_child_pasted_text",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "child_agent_cannot_create_pasted_text"
    assert payload["recent_artifacts"][0]["artifact_id"] == "artifact_resume"


def test_child_job_agent_reuses_existing_current_run_match_report_artifact(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_existing_report",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "session_create_text_artifact",
                "success": True,
                "tool_call_id": "call_existing_report",
                "content": json.dumps(
                    {
                        "artifact_id": "artifact_fit_report",
                        "title": "岗位匹配报告 - AI应用开发工程师",
                        "kind": "generated_file",
                        "media_type": "text/markdown",
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="job_agent",
            run_id="run_child_job",
            parent_run_id="run_parent",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={
                "title": "岗位匹配报告 - AI应用开发工程师",
                "kind": "generated_file",
                "media_type": "text/markdown",
                "content": "# 新报告\n\n不应继续重写。",
            },
            tool_call_id="call_duplicate_report",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "reuse"
    assert payload["reason"] == "child_output_artifact_already_ready"
    assert payload["artifact_id"] == "artifact_fit_report"
    assert payload["output_kind"] == "job_fit_report"
    assert "career_job_fit_report_save" in payload["next_action"]
    assert payload["next_allowed_tools"] == ["career_jd_analysis_save"]
    assert payload["required_tools"] == ["career_jd_analysis_save"]
    assert payload["completed_refs"] == {"report_artifact_id": "artifact_fit_report"}
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "reuse"


def test_child_job_agent_reuses_report_artifact_and_points_to_fit_save_after_jd_saved(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_existing_report",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "session_create_text_artifact",
                "success": True,
                "tool_call_id": "call_existing_report",
                "content": json.dumps(
                    {
                        "artifact_id": "artifact_fit_report",
                        "title": "岗位匹配报告 - AI应用开发工程师",
                        "kind": "generated_file",
                        "media_type": "text/markdown",
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="job_agent",
            run_id="run_child_job",
            parent_run_id="run_parent",
        ),
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_jd_saved",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "career_jd_analysis_save",
                "success": True,
                "tool_call_id": "call_jd_save",
                "content": json.dumps({"record_id": "jd_real"}, ensure_ascii=False),
            },
            created_at=_now(),
            agent_id="job_agent",
            run_id="run_child_job",
            parent_run_id="run_parent",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={
                "title": "岗位匹配报告 - AI应用开发工程师",
                "kind": "generated_file",
                "media_type": "text/markdown",
                "content": "# 新报告\n\n不应继续重写。",
            },
            tool_call_id="call_duplicate_report",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "reuse"
    assert payload["reason"] == "child_output_artifact_already_ready"
    assert payload["missing_outputs"] == ["job_fit_report"]
    assert "career_job_fit_report_save" in payload["next_action"]
    assert "career_jd_analysis_save" not in payload["next_action"]
    assert payload["next_allowed_tools"] == ["career_job_fit_report_save"]
    assert payload["required_tools"] == ["career_job_fit_report_save"]
    assert payload["completed_refs"]["report_artifact_id"] == "artifact_fit_report"
    assert payload["completed_refs"]["jd_analysis_id"] == "jd_real"
    assert payload["completed_refs"]["career_profile_id"] == "career_profile_default"


def test_job_fit_report_save_repairs_invalid_career_profile_ref(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    store.save_jd_analysis(_jd_analysis())
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )

    decision = guard.inspect(
        ToolCall(
            name="career_job_fit_report_save",
            arguments={
                "source_artifact_id": "artifact_jd",
                "jd_analysis_id": "jd_real",
                "resume_profile_id": "resume_profile_real",
                "career_profile_id": "career_profile_status",
                "report_artifact_id": "artifact_fit_report",
                "evidence_refs": [
                    "resume_profile_real",
                    "career_profile_status",
                    "jd_real",
                    "artifact_jd",
                    "artifact_fit_report",
                ],
                "matched_evidence": ["Python 后端经验"],
                "gaps": ["向量检索未体现"],
                "recommendation": "cautious",
                "overall_score": 70,
            },
            tool_call_id="call_fit_save_bad_career_profile",
        ),
        context,
    )

    assert decision.result is None
    repaired_args = decision.tool_call.arguments
    assert repaired_args["career_profile_id"] == "career_profile_default"
    assert "career_profile_status" not in repaired_args["evidence_refs"]
    assert "career_profile_default" in repaired_args["evidence_refs"]
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"
    assert decision.event_payload["repair_actions"] == [
        {
            "field": "career_profile_id",
            "from": "career_profile_status",
            "to": "career_profile_default",
            "reason": "single_current_session_career_profile",
        }
    ]


def test_child_job_agent_terminal_after_job_fit_report_saved(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_existing_report",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "session_create_text_artifact",
                "success": True,
                "tool_call_id": "call_existing_report",
                "content": json.dumps(
                    {
                        "artifact_id": "artifact_fit_report",
                        "title": "岗位匹配报告 - AI应用开发工程师",
                        "kind": "generated_file",
                        "media_type": "text/markdown",
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="job_agent",
            run_id="run_child_job",
            parent_run_id="run_parent",
        ),
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_fit_saved",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "career_job_fit_report_save",
                "success": True,
                "tool_call_id": "call_fit_save",
                "content": json.dumps(
                    {
                        "record_type": "job_fit_report",
                        "record_id": "fit_real",
                        "record": {
                            "job_fit_report_id": "fit_real",
                            "jd_analysis_id": "jd_real",
                            "resume_profile_id": "resume_profile_real",
                            "report_artifact_id": "artifact_fit_report",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="job_agent",
            run_id="run_child_job",
            parent_run_id="run_parent",
        ),
    )

    calls = [
        ToolCall(
            name="session_create_text_artifact",
            arguments={
                "title": "岗位匹配报告 - AI应用开发工程师",
                "kind": "generated_file",
                "media_type": "text/markdown",
                "content": "# 重复报告\n\n不应继续重写。",
            },
            tool_call_id="call_duplicate_report",
        ),
        ToolCall(
            name="career_jd_analysis_save",
            arguments={
                "source_artifact_id": "artifact_jd",
                "company": "星河智能",
                "position": "AI Agent 后端工程师",
            },
            tool_call_id="call_duplicate_jd_save",
        ),
        ToolCall(
            name="career_job_fit_report_save",
            arguments={
                "jd_analysis_id": "jd_real",
                "resume_profile_id": "resume_profile_real",
                "report_artifact_id": "artifact_fit_report",
            },
            tool_call_id="call_duplicate_fit_save",
        ),
        ToolCall(
            name="career_resume_profile_get",
            arguments={"resume_profile_id": "resume_profile_real"},
            tool_call_id="call_redundant_resume_profile_get",
        ),
        ToolCall(
            name="tool_search",
            arguments={"query": "career_job_fit_report_save"},
            tool_call_id="call_redundant_search",
        ),
    ]

    for call in calls:
        decision = guard.inspect(call, context)
        assert decision.result is not None
        payload = json.loads(decision.result.content)
        assert payload["policy"] == "block"
        assert payload["terminal"] is True
        assert payload["final_answer_ready"] is True
        assert payload["missing_outputs"] == []
        assert payload["next_allowed_tools"] == []
        assert payload["required_tools"] == []
        assert payload["completed_refs"]["jd_analysis_id"] == "jd_real"
        assert payload["completed_refs"]["job_fit_report_id"] == "fit_real"
        assert payload["completed_refs"]["report_artifact_id"] == "artifact_fit_report"


def test_child_job_fit_terminal_ignores_hidden_job_fit_save_result(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_jd_analysis(_jd_analysis())
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_hidden_fit_save",
        agent_id="job_agent",
        turn_id="turn_child_hidden_fit_save",
        entry_agent_id="agent_main",
        parent_run_id="run_parent",
    )
    _append_tool_result(
        repo,
        context,
        tool_name="career_job_fit_report_save",
        content={
            "recoverable": True,
            "event_type": "tool_schema_not_revealed",
            "tool_name": "career_job_fit_report_save",
            "workflow_runtime_result": True,
            "policy": "block",
            "reason": "tool_hidden_by_runtime_plan",
            "next_allowed_tools": ["career_jd_analysis_save"],
            "required_tools": ["career_jd_analysis_save"],
            "known_refs": {"report_artifact_id": "artifact_fit_report"},
        },
    )

    decision = guard.inspect(
        ToolCall(
            name="career_jd_analysis_save",
            arguments={"source_artifact_id": "artifact_jd", "evidence_refs": ["artifact_jd"]},
            tool_call_id="call_reuse_jd",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "reuse"
    assert payload["record_type"] == "jd_analysis"
    assert payload["record_id"] == "jd_real"
    assert payload.get("reason") != "child_job_fit_stage_complete_final_answer"


def test_child_job_agent_blocks_match_report_with_conflicting_candidate_facts(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={
                "title": "岗位匹配报告 - AI应用开发工程师",
                "kind": "generated_file",
                "media_type": "text/markdown",
                "content": (
                    "# 岗位匹配报告\n\n"
                    "| 岗位要求 | 候选人情况 |\n"
                    "| --- | --- |\n"
                    "| Python | Java 为主 |\n"
                    "| FastAPI | 候选人使用 Spring Boot |\n"
                    "| 部署 | Docker/K8s 有经验 |\n"
                ),
            },
            tool_call_id="call_bad_report",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "job_fit_report_artifact_candidate_facts_conflict"
    assert payload["missing_outputs"] == ["valid_job_fit_report_artifact"]
    assert any("java" in item for item in payload["unsupported_candidate_facts"])
    assert any("spring" in item for item in payload["unsupported_candidate_facts"])
    assert payload["invalid_claims"]
    assert any(item["term"] == "java" for item in payload["invalid_claims"])
    assert any(item["term"] == "spring" for item in payload["invalid_claims"])
    assert all(item["rewrite_to"] == "gap_or_risk_or_interview_focus" for item in payload["invalid_claims"])
    assert payload["repair_actions"]
    assert any(item["action"] == "move_unsupported_term_to_gap_or_risk" for item in payload["repair_actions"])
    assert "Python" in payload["supported_candidate_facts"]
    assert "FastAPI" in payload["supported_candidate_facts"]
    fact_boundary = payload["report_fact_boundary"]
    assert fact_boundary["unsupported_candidate_facts"] == payload["unsupported_candidate_facts"]
    assert fact_boundary["invalid_claims"] == payload["invalid_claims"]
    assert fact_boundary["supported_candidate_facts"] == payload["supported_candidate_facts"]
    assert payload["rewrite_rules"] == fact_boundary["rewrite_rules"]
    assert "完整 Markdown 正文" in fact_boundary["artifact_rules"]["content"]
    assert any("RAG 通常涉及向量检索" in rule for rule in payload["rewrite_rules"])
    assert any("Docker/K8s" in rule for rule in payload["rewrite_rules"])
    assert "report_artifact_contract" in payload
    assert "重新生成匹配报告正文" in payload["next_action"]
    assert payload["next_allowed_tools"] == ["session_create_text_artifact"]
    assert payload["required_tools"] == ["session_create_text_artifact"]
    assert "session_read_artifact" in payload["blocked_tools"]


def test_child_job_agent_allows_missing_jd_keyword_as_gap_in_match_report(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={
                "title": "岗位匹配报告 - AI应用开发工程师",
                "kind": "generated_file",
                "media_type": "text/markdown",
                "content": (
                    "# 岗位匹配报告\n\n"
                    "- 候选人具备 Python / FastAPI 后端经验。\n"
                    "- 向量检索经验未在简历中体现，需要补充。\n"
                    "- 需要确认候选人是否有 Milvus、Pinecone、Chroma 等向量数据库经验。\n"
                    "- 如果向量检索经验薄弱，可能影响面试通过率。\n"
                    "- 建议强化简历诊断 Agent 项目的技术深度描述（向量检索、RAG 链路、Agent 编排）。\n"
                    "- 技能补齐：优先通过实战项目补齐 RAG + Agent 工程经验，可参考 LangChain/LlamaIndex。\n"
                    "### 1. LangChain 使用深度\n"
                    "- 增加 LangChain/LangGraph 的了解，并在面试中说明学习计划。\n"
                ),
            },
            tool_call_id="call_good_report",
        ),
        context,
    )

    assert decision.result is None
    assert decision.tool_call.name == "session_create_text_artifact"


def test_child_job_agent_blocks_mysql_claim_when_only_postgresql_supported(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile(skills=["Python", "PostgreSQL"]))
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={
                "title": "岗位匹配报告 - AI应用开发工程师",
                "kind": "generated_file",
                "media_type": "text/markdown",
                "content": (
                    "# 岗位匹配报告\n\n"
                    "- 候选人有 PostgreSQL 使用经验，覆盖 JD 要求的关系型数据库（PostgreSQL / MySQL）。\n"
                ),
            },
            tool_call_id="call_mysql_claim_report",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert any("mysql" in item for item in payload["unsupported_candidate_facts"])
    assert "PostgreSQL" in payload["supported_candidate_facts"]
    assert any("不能扩写成 MySQL" in rule for rule in payload["rewrite_rules"])


def test_child_job_agent_allows_mysql_as_gap_when_postgresql_supported(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile(skills=["Python", "PostgreSQL"]))
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={
                "title": "岗位匹配报告 - AI应用开发工程师",
                "kind": "generated_file",
                "media_type": "text/markdown",
                "content": (
                    "# 岗位匹配报告\n\n"
                    "- 候选人有 PostgreSQL 使用经验，可部分支持关系型数据库要求。\n"
                    "- MySQL 具体经验未在简历中体现，需要确认。\n"
                ),
            },
            tool_call_id="call_mysql_gap_report",
        ),
        context,
    )

    assert decision.result is None
    assert decision.tool_call.name == "session_create_text_artifact"


def test_child_job_agent_allows_interview_probe_for_missing_vector_search(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={
                "title": "岗位匹配报告 - AI应用开发工程师",
                "kind": "generated_file",
                "media_type": "text/markdown",
                "content": (
                    "# 岗位匹配报告\n\n"
                    "- 候选人具备 Python / FastAPI 后端经验。\n"
                    "## 面试追问\n"
                    "1. 询问候选人在 RAG 项目中处理文档检索的具体技术选型，以评估向量检索能力。\n"
                    "2. 可考察候选人是否了解 LangGraph 在多 Agent 编排中的适用边界。\n"
                ),
            },
            tool_call_id="call_probe_report",
        ),
        context,
    )

    assert decision.result is None
    assert decision.tool_call.name == "session_create_text_artifact"


def test_child_job_agent_blocks_assertive_candidate_claim_even_in_interview_text(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={
                "title": "岗位匹配报告 - AI应用开发工程师",
                "kind": "generated_file",
                "media_type": "text/markdown",
                "content": (
                    "# 岗位匹配报告\n\n"
                    "- 候选人具备 Python / FastAPI 后端经验。\n"
                    "- 面试中可以强调候选人使用 Qdrant 向量数据库实现语义匹配。\n"
                ),
            },
            tool_call_id="call_bad_probe_report",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "job_fit_report_artifact_candidate_facts_conflict"
    assert any("qdrant" in item for item in payload["unsupported_candidate_facts"])


def test_child_job_agent_blocks_separate_jd_analysis_artifact_when_fit_report_required(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_assign_job_fit",
            session_id="sess_guard",
            type="agent_task_assigned",
            payload={
                "task_id": "task_job_fit",
                "source_agent_id": "agent_main",
                "target_agent_id": "job_agent",
                "instruction": "分析 JD，保存 JDAnalysis，并生成岗位匹配报告和 JobFitReport。",
                "constraints": [],
                "artifact_refs": ["artifact_resume", "artifact_jd"],
                "parent_run_id": "run_parent",
                "child_run_id": "run_child_job",
            },
            created_at=_now(),
            agent_id="agent_main",
            run_id="run_parent",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={
                "title": "JD分析报告.md",
                "kind": "generated_file",
                "media_type": "text/markdown",
                "content": "# JD 分析报告\n\n岗位要求：Python、RAG。",
            },
            tool_call_id="call_jd_analysis_artifact",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "job_agent_should_not_create_separate_jd_analysis_artifact"
    assert payload["output_kind"] == "jd_analysis_report"
    assert payload["missing_outputs"] == ["job_fit_report_artifact", "job_fit_report"]
    assert "JDAnalysis 只保存为产品记录" in payload["next_action"]
    assert "岗位匹配报告 artifact" in payload["next_action"]
    assert payload["next_allowed_tools"] == ["session_create_text_artifact"]
    assert payload["required_tools"] == ["session_create_text_artifact"]


def test_child_job_agent_allows_jd_analysis_artifact_when_fit_report_not_required(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_assign_jd_only",
            session_id="sess_guard",
            type="agent_task_assigned",
            payload={
                "task_id": "task_jd_only",
                "source_agent_id": "agent_main",
                "target_agent_id": "job_agent",
                "instruction": "只分析 JD，保存 JDAnalysis。",
                "constraints": [],
                "artifact_refs": ["artifact_resume", "artifact_jd"],
                "parent_run_id": "run_parent",
                "child_run_id": "run_child_job",
            },
            created_at=_now(),
            agent_id="agent_main",
            run_id="run_parent",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={
                "title": "JD分析报告.md",
                "kind": "generated_file",
                "media_type": "text/markdown",
                "content": "# JD 分析报告\n\n岗位要求：Python、RAG。",
            },
            tool_call_id="call_jd_analysis_artifact",
        ),
        context,
    )

    assert decision.result is None
    assert decision.tool_call.name == "session_create_text_artifact"


def test_child_job_agent_blocks_match_report_artifact_without_content_field(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_assign_job_fit",
            session_id="sess_guard",
            type="agent_task_assigned",
            payload={
                "task_id": "task_job_fit",
                "source_agent_id": "agent_main",
                "target_agent_id": "job_agent",
                "instruction": "分析 JD，保存 JDAnalysis，并生成岗位匹配报告和 JobFitReport。",
                "constraints": [],
                "artifact_refs": ["artifact_resume", "artifact_jd"],
                "parent_run_id": "run_parent",
                "child_run_id": "run_child_job",
            },
            created_at=_now(),
            agent_id="agent_main",
            run_id="run_parent",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={
                "title": "岗位匹配报告 - AI应用开发工程师",
                "kind": "generated_file",
                "media_type": "text/markdown",
                "content_chars": 1200,
            },
            tool_call_id="call_empty_fit_report",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "job_fit_report_artifact_missing_content"
    assert payload["missing_outputs"] == ["job_fit_report_artifact", "job_fit_report"]
    assert "content 字段" in payload["next_action"]
    assert "不要传 content_chars" in payload["next_action"]
    assert payload["next_allowed_tools"] == ["session_create_text_artifact"]
    assert payload["required_tools"] == ["session_create_text_artifact"]


def test_child_job_agent_blocks_low_level_action_after_invalid_report_artifact(
    tmp_path: Path,
) -> None:
    guard, _, repo = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_invalid_report",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "session_create_text_artifact",
                "success": True,
                "tool_call_id": "call_bad_report",
                "content": json.dumps(
                    {
                        "workflow_runtime_result": True,
                        "policy": "block",
                        "reason": "job_fit_report_artifact_candidate_facts_conflict",
                        "output_kind": "job_fit_report",
                        "unsupported_candidate_facts": ["spring: 候选人使用 Spring Boot"],
                        "supported_candidate_facts": ["Python", "FastAPI", "RAG"],
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="job_agent",
            run_id="run_child_job",
            parent_run_id="run_parent",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="session_list_artifacts",
            arguments={},
            tool_call_id="call_list_after_invalid_report",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "job_fit_report_invalid_artifact_retry_required"
    assert payload["missing_outputs"] == ["valid_job_fit_report_artifact"]
    assert payload["supported_candidate_facts"] == ["Python", "FastAPI", "RAG"]
    assert payload["report_fact_boundary"]["unsupported_candidate_facts"] == ["spring: 候选人使用 Spring Boot"]
    assert payload["report_fact_boundary"]["supported_candidate_facts"] == ["Python", "FastAPI", "RAG"]
    assert payload["rewrite_rules"] == payload["report_fact_boundary"]["rewrite_rules"]
    assert "不要继续读取或 get/list" in payload["next_action"]
    assert payload["next_allowed_tools"] == ["session_create_text_artifact"]
    assert payload["required_tools"] == ["session_create_text_artifact"]


def test_child_job_agent_low_level_read_points_to_jd_and_fit_save_after_report_artifact(
    tmp_path: Path,
) -> None:
    guard, _, repo = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_existing_report",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "session_create_text_artifact",
                "success": True,
                "tool_call_id": "call_existing_report",
                "content": json.dumps(
                    {
                        "artifact_id": "artifact_fit_report",
                        "title": "岗位匹配报告 - AI应用开发工程师",
                        "kind": "generated_file",
                        "media_type": "text/markdown",
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="job_agent",
            run_id="run_child_job",
            parent_run_id="run_parent",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="career_resume_profile_get",
            arguments={"resume_profile_id": "resume_profile_real"},
            tool_call_id="call_resume_profile_get",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "job_fit_report_artifact_ready_stop_low_level_actions"
    assert payload["report_artifact_id"] == "artifact_fit_report"
    assert payload["missing_outputs"] == ["jd_analysis", "job_fit_report"]
    assert "career_jd_analysis_save" in payload["next_action"]
    assert "career_job_fit_report_save" in payload["next_action"]
    assert payload["next_allowed_tools"] == ["career_jd_analysis_save"]
    assert payload["required_tools"] == ["career_jd_analysis_save"]
    assert payload["completed_refs"] == {"report_artifact_id": "artifact_fit_report"}


def test_child_job_agent_low_level_read_points_to_fit_save_after_jd_saved(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_existing_report",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "session_create_text_artifact",
                "success": True,
                "tool_call_id": "call_existing_report",
                "content": json.dumps(
                    {
                        "artifact_id": "artifact_fit_report",
                        "title": "岗位匹配报告 - AI应用开发工程师",
                        "kind": "generated_file",
                        "media_type": "text/markdown",
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="job_agent",
            run_id="run_child_job",
            parent_run_id="run_parent",
        ),
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_jd_saved",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "career_jd_analysis_save",
                "success": True,
                "tool_call_id": "call_jd_save",
                "content": json.dumps({"record_id": "jd_real"}, ensure_ascii=False),
            },
            created_at=_now(),
            agent_id="job_agent",
            run_id="run_child_job",
            parent_run_id="run_parent",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="career_profile_get",
            arguments={"career_profile_id": "career_profile_default"},
            tool_call_id="call_career_profile_get",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["missing_outputs"] == ["job_fit_report"]
    assert "career_job_fit_report_save" in payload["next_action"]
    assert "career_jd_analysis_save" not in payload["next_action"]
    assert payload["next_allowed_tools"] == ["career_job_fit_report_save"]
    assert payload["required_tools"] == ["career_job_fit_report_save"]


def test_child_job_agent_fit_save_plan_keeps_refs_without_career_profile_get(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_assign_job_fit_full_refs",
            session_id="sess_guard",
            type="agent_task_assigned",
            payload={
                "task_id": "task_job_fit",
                "source_agent_id": "agent_main",
                "target_agent_id": "job_agent",
                "instruction": "分析 JD，保存 JDAnalysis，并生成岗位匹配报告和 JobFitReport。",
                "artifact_refs": ["artifact_jd"],
                "parent_run_id": "run_parent",
                "child_run_id": "run_child_job",
            },
            created_at=_now(),
            agent_id="agent_main",
            run_id="run_parent",
        ),
    )
    tool_results: list[tuple[str, dict[str, object]]] = [
        (
            "session_read_artifact",
            {
                "artifact_id": "artifact_jd",
                "title": "JD.txt",
                "content": "岗位要求：Python、RAG、Agent 工程。",
            },
        ),
        (
            "career_resume_profile_get",
            {
                "record_type": "resume_profile",
                "record_id": "resume_profile_real",
                "record": {"resume_profile_id": "resume_profile_real"},
            },
        ),
        (
            "career_jd_analysis_save",
            {
                "record_type": "jd_analysis",
                "record_id": "jd_real",
                "record": {"jd_analysis_id": "jd_real", "source_artifact_id": "artifact_jd"},
            },
        ),
        (
            "session_create_text_artifact",
            {
                "artifact_id": "artifact_fit_report",
                "title": "岗位匹配报告 - AI应用开发工程师",
                "kind": "generated_file",
                "media_type": "text/markdown",
            },
        ),
    ]
    for tool_name, content in tool_results:
        _append_tool_result(repo, context, tool_name=tool_name, content=content)

    decision = guard.inspect(
        ToolCall(
            name="career_resume_profile_get",
            arguments={"resume_profile_id": "resume_profile_real"},
            tool_call_id="call_duplicate_resume_get_after_report",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "job_fit_report_artifact_ready_stop_low_level_actions"
    assert payload["next_allowed_tools"] == ["career_job_fit_report_save"]
    assert payload["required_tools"] == ["career_job_fit_report_save"]
    assert payload["known_refs"]["resume_profile_id"] == "resume_profile_real"
    assert payload["known_refs"]["career_profile_id"] == "career_profile_default"
    assert payload["known_refs"]["jd_analysis_id"] == "jd_real"
    assert payload["known_refs"]["source_artifact_id"] == "artifact_jd"
    assert payload["known_refs"]["report_artifact_id"] == "artifact_fit_report"


def test_child_job_agent_blocks_low_level_reads_after_fit_inputs_loaded(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_assign_job_fit_inputs",
            session_id="sess_guard",
            type="agent_task_assigned",
            payload={
                "task_id": "task_job_fit",
                "source_agent_id": "agent_main",
                "target_agent_id": "job_agent",
                "instruction": "分析 JD，保存 JDAnalysis，并生成岗位匹配报告和 JobFitReport。",
                "constraints": [],
                "artifact_refs": ["artifact_jd"],
                "parent_run_id": "run_parent",
                "child_run_id": "run_child_job",
            },
            created_at=_now(),
            agent_id="agent_main",
            run_id="run_parent",
        ),
    )
    for index, (tool_name, content) in enumerate(
        [
            (
                "session_read_artifact",
                {
                    "artifact_id": "artifact_jd",
                    "title": "JD.txt",
                    "content": "岗位要求：Python、RAG、Agent 工程。",
                },
            ),
            (
                "career_resume_profile_get",
                {
                    "record_type": "resume_profile",
                    "record_id": "resume_profile_real",
                    "record": {"resume_profile_id": "resume_profile_real"},
                },
            ),
            (
                "career_profile_get",
                {
                    "record_type": "career_profile",
                    "record_id": "career_profile_default",
                    "record": {"career_profile_id": "career_profile_default"},
                },
            ),
        ],
        start=1,
    ):
        repo.append_event(
            "sess_guard",
            EventRecord(
                event_id=f"evt_fit_input_{index}",
                session_id="sess_guard",
                type="tool_result",
                payload={
                    "tool_name": tool_name,
                    "success": True,
                    "tool_call_id": f"call_fit_input_{index}",
                    "content": json.dumps(content, ensure_ascii=False),
                },
                created_at=_now(),
                agent_id="job_agent",
                run_id="run_child_job",
                parent_run_id="run_parent",
            ),
        )

    decision = guard.inspect(
        ToolCall(
            name="career_resume_profile_get",
            arguments={"resume_profile_id": "resume_profile_real"},
            tool_call_id="call_duplicate_resume_profile_get",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "job_fit_inputs_already_loaded"
    assert payload["input_snapshot_complete"] is True
    assert payload["next_allowed_tools"] == ["career_jd_analysis_save"]
    assert payload["required_tools"] == [
        "career_jd_analysis_save",
        "session_create_text_artifact",
        "career_job_fit_report_save",
    ]
    assert payload["known_refs"]["jd_artifact_id"] == "artifact_jd"
    assert payload["known_refs"]["resume_profile_id"] == "resume_profile_real"
    assert payload["known_refs"]["career_profile_id"] == "career_profile_default"
    assert "career_resume_profile_get" in payload["blocked_tools"]


def test_duplicate_product_get_reuses_previous_result_in_same_run(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = _context(run_id="run_duplicate_get")
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_previous_resume_profile_get",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "career_resume_profile_get",
                "success": True,
                "tool_call_id": "call_previous_resume_profile_get",
                "content": json.dumps(
                    {
                        "record_type": "resume_profile",
                        "record_id": "resume_profile_real",
                        "found": True,
                        "record": {
                            "resume_profile_id": "resume_profile_real",
                            "source_artifact_id": "artifact_resume",
                            "skills": ["Python", "FastAPI"],
                        },
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="agent_main",
            run_id="run_duplicate_get",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="career_resume_profile_get",
            arguments={"resume_profile_id": "resume_profile_real"},
            tool_call_id="call_duplicate_resume_profile_get",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "reuse"
    assert payload["reason"] == "product_record_already_read_in_run"
    assert payload["record_id"] == "resume_profile_real"
    assert payload["ids"]["resume_profile_id"] == "resume_profile_real"
    assert "record" not in payload


def test_main_agent_blocks_career_working_state_memory_write(tmp_path: Path) -> None:
    guard, _, _ = _guard(tmp_path)
    context = _context(run_id="run_memory_state")

    decision = guard.inspect(
        ToolCall(
            name="memory_write",
            arguments={
                "content": (
                    "用户已完成简历解析和诊断，resume_profile_id=resume_profile_153aecf1033e，"
                    "career_profile已更新。岗位匹配时可直接复用该ResumeProfile。"
                ),
                "tags": ["resume", "career_context", "session_state"],
            },
            tool_call_id="call_memory_state",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "career_session_state_should_not_use_memory_write"
    assert payload["tool_executed"] is False
    assert payload["result_created"] is False
    assert "product store" in payload["next_action"]


def test_main_agent_allows_durable_preference_memory_write(tmp_path: Path) -> None:
    guard, _, _ = _guard(tmp_path)
    context = _context(run_id="run_memory_preference")

    decision = guard.inspect(
        ToolCall(
            name="memory_write",
            arguments={"content": "用户偏好回答简洁，先给结论再给细节。", "tags": ["preference"]},
            tool_call_id="call_memory_preference",
        ),
        context,
    )

    assert decision.result is None


def test_child_job_agent_can_read_own_report_artifact_before_fit_save(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_existing_report",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "session_create_text_artifact",
                "success": True,
                "tool_call_id": "call_existing_report",
                "content": json.dumps(
                    {
                        "artifact_id": "artifact_fit_report",
                        "title": "岗位匹配报告 - AI应用开发工程师",
                        "kind": "generated_file",
                        "media_type": "text/markdown",
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="job_agent",
            run_id="run_child_job",
            parent_run_id="run_parent",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="session_read_artifact",
            arguments={"artifact_id": "artifact_fit_report"},
            tool_call_id="call_read_report",
        ),
        context,
    )

    assert decision.result is None
    assert decision.tool_call.name == "session_read_artifact"


def test_child_job_agent_blocks_report_read_after_fit_save(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_job",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_existing_report",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "session_create_text_artifact",
                "success": True,
                "tool_call_id": "call_existing_report",
                "content": json.dumps(
                    {
                        "artifact_id": "artifact_fit_report",
                        "title": "岗位匹配报告 - AI应用开发工程师",
                        "kind": "generated_file",
                        "media_type": "text/markdown",
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="job_agent",
            run_id="run_child_job",
            parent_run_id="run_parent",
        ),
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_fit_saved",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "career_job_fit_report_save",
                "success": True,
                "tool_call_id": "call_fit_save",
                "content": json.dumps({"record_id": "fit_real"}, ensure_ascii=False),
            },
            created_at=_now(),
            agent_id="job_agent",
            run_id="run_child_job",
            parent_run_id="run_parent",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="session_read_artifact",
            arguments={"artifact_id": "artifact_fit_report"},
            tool_call_id="call_read_report_again",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "job_fit_report_record_already_saved"
    assert payload["terminal"] is True
    assert payload["final_answer_ready"] is True
    assert payload["next_allowed_tools"] == []
    assert payload["required_tools"] == []
    assert payload["missing_outputs"] == []
    assert "直接总结" in payload["next_action"]


def test_child_resume_agent_guides_profile_save_after_diagnosis_artifact_ready(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_resume",
        agent_id="resume_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_existing_diagnosis",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "session_create_text_artifact",
                "success": True,
                "tool_call_id": "call_existing_diagnosis",
                "content": json.dumps(
                    {
                        "artifact_id": "artifact_diagnosis",
                        "title": "简历诊断报告-张三",
                        "kind": "generated_file",
                        "media_type": "text/markdown",
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="resume_agent",
            run_id="run_child_resume",
            parent_run_id="run_parent",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="session_read_artifact",
            arguments={"artifact_id": "artifact_resume"},
            tool_call_id="call_read_resume_again",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "resume_diagnosis_artifact_ready_save_profile"
    assert payload["missing_outputs"] == ["resume_profile"]
    assert payload["next_allowed_tools"] == ["career_resume_profile_save"]
    assert payload["required_tools"] == ["career_resume_profile_save"]
    assert payload["known_refs"]["diagnosis_artifact_id"] == "artifact_diagnosis"
    assert "career_resume_profile_save" in payload["next_action"]


def test_child_resume_agent_blocks_profile_save_before_diagnosis_artifact(tmp_path: Path) -> None:
    guard, _, _ = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_resume",
        agent_id="resume_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )

    decision = guard.inspect(
        ToolCall(
            name="career_resume_profile_save",
            arguments={
                "resume_profile_id": "resume_profile_alpha",
                "source_artifact_id": "artifact_resume",
                "evidence_refs": ["artifact_resume"],
            },
            tool_call_id="call_profile_too_early",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "resume_profile_save_before_diagnosis_artifact"
    assert payload["next_allowed_tools"] == ["session_create_text_artifact"]
    assert payload["required_tools"] == ["session_create_text_artifact"]
    assert payload["missing_outputs"] == ["diagnosis_artifact", "resume_profile"]
    assert payload["known_refs"]["resume_source_artifact_id"] == "artifact_resume"


def test_child_resume_agent_repairs_profile_save_with_existing_diagnosis_artifact(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_resume",
        agent_id="resume_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_existing_diagnosis",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "session_create_text_artifact",
                "success": True,
                "tool_call_id": "call_existing_diagnosis",
                "content": json.dumps(
                    {
                        "artifact_id": "artifact_diagnosis",
                        "title": "简历诊断报告-张三",
                        "kind": "generated_file",
                        "media_type": "text/markdown",
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="resume_agent",
            run_id="run_child_resume",
            parent_run_id="run_parent",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="career_resume_profile_save",
            arguments={
                "resume_profile_id": "resume_profile_alpha",
                "source_artifact_id": "artifact_resume",
                "evidence_refs": ["artifact_resume"],
            },
            tool_call_id="call_profile_after_diagnosis",
        ),
        context,
    )

    assert decision.result is None
    assert decision.tool_call.arguments["diagnosis_artifact_id"] == "artifact_diagnosis"
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"


def test_child_resume_agent_blocks_low_level_read_after_profile_and_diagnosis_ready(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = RunContext(
        session_id="sess_guard",
        run_id="run_child_resume",
        agent_id="resume_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_existing_diagnosis",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "session_create_text_artifact",
                "success": True,
                "tool_call_id": "call_existing_diagnosis",
                "content": json.dumps(
                    {
                        "artifact_id": "artifact_diagnosis",
                        "title": "简历诊断报告-张三",
                        "kind": "generated_file",
                        "media_type": "text/markdown",
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="resume_agent",
            run_id="run_child_resume",
            parent_run_id="run_parent",
        ),
    )
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_resume_profile_saved",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "career_resume_profile_save",
                "success": True,
                "tool_call_id": "call_profile_save",
                "content": json.dumps({"record_id": "resume_profile_real"}, ensure_ascii=False),
            },
            created_at=_now(),
            agent_id="resume_agent",
            run_id="run_child_resume",
            parent_run_id="run_parent",
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="session_read_artifact",
            arguments={"artifact_id": "artifact_diagnosis"},
            tool_call_id="call_read_diagnosis_again",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "resume_profile_and_diagnosis_ready_stop_low_level_actions"
    assert payload["missing_outputs"] == []
    assert payload["diagnosis_artifact_id"] == "artifact_diagnosis"
    assert payload["final_answer_ready"] is True
    assert "直接总结" in payload["next_action"]


def test_child_output_artifact_reuse_is_scoped_to_current_run(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    repo.append_event(
        "sess_guard",
        EventRecord(
            event_id="evt_previous_report",
            session_id="sess_guard",
            type="tool_result",
            payload={
                "tool_name": "session_create_text_artifact",
                "success": True,
                "tool_call_id": "call_previous_report",
                "content": json.dumps(
                    {
                        "artifact_id": "artifact_old_fit_report",
                        "title": "岗位匹配报告 - 旧岗位",
                        "kind": "generated_file",
                        "media_type": "text/markdown",
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id="job_agent",
            run_id="run_previous_child",
            parent_run_id="run_parent",
        ),
    )
    context = RunContext(
        session_id="sess_guard",
        run_id="run_new_child",
        agent_id="job_agent",
        turn_id="turn_guard",
        entry_agent_id="agent_main",
    )

    decision = guard.inspect(
        ToolCall(
            name="session_create_text_artifact",
            arguments={
                "title": "岗位匹配报告 - 新岗位",
                "kind": "generated_file",
                "content": "# 新岗位报告",
            },
            tool_call_id="call_new_report",
        ),
        context,
    )

    assert decision.result is None
    assert decision.tool_call.name == "session_create_text_artifact"


def test_delegate_agents_jd_fit_task_is_repaired_to_complete_fit_report(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    context = _context()
    _append_user_message(
        repo,
        context,
        "请直接基于这个 JD artifact 分析我和岗位的匹配度，并保存岗位分析和匹配报告。",
    )

    decision = guard.inspect(
        ToolCall(
            name="delegate_agents",
            arguments={
                "tasks": [
                    {
                        "target_agent_id": "job_agent",
                        "instruction": "分析 artifact_jd_live_001 中的目标岗位 JD，创建并保存 JDAnalysis。",
                        "artifact_refs": ["artifact_jd_live_001"],
                    }
                ],
                "wait": True,
            },
            tool_call_id="call_delegate_jd_only",
        ),
        context,
    )

    assert decision.result is None
    task = decision.tool_call.arguments["tasks"][0]
    assert "JobFitReport" in task["instruction"]
    assert "career_jd_analysis_save" in task["instruction"]
    assert "career_job_fit_report_save" in task["instruction"]
    assert "resume_profile_id=resume_profile_real" in task["instruction"]
    assert "career_profile_id=career_profile_default" in task["instruction"]
    assert "JDAnalysis.source_artifact_id 必须使用 artifact_jd_live_001" in task["instruction"]
    assert "不要创建单独 JD 分析 artifact" in task["instruction"]
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"


def test_delegate_agents_moves_top_level_instruction_into_task(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = _context()
    _append_user_message(repo, context, "请委派 resume_agent 解析简历。")

    decision = guard.inspect(
        ToolCall(
            name="delegate_agents",
            arguments={
                "instruction": "请读取 artifact_resume 并生成 ResumeProfile 和诊断报告。",
                "tasks": [{"target_agent_id": "resume_agent", "artifact_refs": ["artifact_resume"]}],
            },
            tool_call_id="call_delegate_top_instruction",
        ),
        context,
    )

    assert decision.result is None
    task = decision.tool_call.arguments["tasks"][0]
    assert task["instruction"] == "请读取 artifact_resume 并生成 ResumeProfile 和诊断报告。"
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"
    assert decision.event_payload["repair_actions"][0]["reason"] == "delegate_task_requires_non_empty_instruction"


def test_delegate_agents_jd_fit_replaces_stale_profile_ids_in_instruction(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    context = _context()
    _append_user_message(
        repo,
        context,
        "请直接基于这个 JD artifact 分析我和岗位的匹配度，并保存岗位分析和匹配报告。",
    )

    decision = guard.inspect(
        ToolCall(
            name="delegate_agents",
            arguments={
                "tasks": [
                    {
                        "target_agent_id": "job_agent",
                        "instruction": (
                            "使用 resume_profile_id=resume_profile_stale 和 "
                            "career_profile_id=career_profile_facts 分析 artifact_jd_live_001。"
                            "必须调用 career_jd_analysis_save 和 career_job_fit_report_save，"
                            "生成 JobFitReport 和匹配报告。"
                        ),
                        "artifact_refs": ["artifact_jd_live_001"],
                    }
                ],
                "wait": True,
            },
            tool_call_id="call_delegate_stale_profile_refs",
        ),
        context,
    )

    assert decision.result is None
    task = decision.tool_call.arguments["tasks"][0]
    instruction = task["instruction"]
    assert "resume_profile_stale" not in instruction
    assert "career_profile_facts" not in instruction
    assert "resume_profile_id=resume_profile_real" in instruction
    assert "career_profile_id=career_profile_default" in instruction
    assert "resume_profile_real=resume_profile_real" not in instruction
    assert "career_profile_default=career_profile_default" not in instruction
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"
    assert any(
        item["reason"] == "delegate_instruction_product_refs_repaired"
        for item in decision.event_payload["repair_actions"]
    )


def test_delegate_agents_replaces_stale_profile_ids_even_when_user_message_is_broad(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    context = _context()
    _append_user_message(repo, context, "继续推进这个求职任务。")

    decision = guard.inspect(
        ToolCall(
            name="delegate_agents",
            arguments={
                "tasks": [
                    {
                        "target_agent_id": "job_agent",
                        "instruction": (
                            "基于 resume_profile_id=resume_profile_real 和 "
                            "career_profile_id=career_profile_update 生成 JobFitReport。"
                        ),
                        "artifact_refs": ["artifact_jd_live_001"],
                    }
                ],
                "wait": True,
            },
            tool_call_id="call_delegate_broad_stale_refs",
        ),
        context,
    )

    assert decision.result is None
    instruction = decision.tool_call.arguments["tasks"][0]["instruction"]
    assert "career_profile_update" not in instruction
    assert "career_profile_id=career_profile_default" in instruction
    assert decision.event_payload is not None
    assert any(
        item["reason"] == "delegate_instruction_product_refs_repaired"
        for item in decision.event_payload["repair_actions"]
    )


def test_delegate_agents_jd_fit_task_gets_single_report_artifact_boundary_without_profiles(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = _context()
    _append_user_message(
        repo,
        context,
        "请并发分析简历和 JD，最后生成岗位匹配报告。",
    )

    decision = guard.inspect(
        ToolCall(
            name="delegate_agents",
            arguments={
                "tasks": [
                    {
                        "target_agent_id": "job_agent",
                        "instruction": "分析 artifact_jd_live_001 中的目标岗位 JD，保存 JDAnalysis，并生成 JobFitReport。",
                        "artifact_refs": ["artifact_jd_live_001"],
                    }
                ],
                "wait": True,
            },
            tool_call_id="call_delegate_jd_fit_boundary",
        ),
        context,
    )

    assert decision.result is None
    task = decision.tool_call.arguments["tasks"][0]
    assert "JDAnalysis 是产品记录" in task["instruction"]
    assert "只允许生成一个用户可预览的岗位匹配报告 artifact" in task["instruction"]
    assert "完整 Markdown 正文传入 content 字段" in task["instruction"]
    assert "不要传 content_chars" in task["instruction"]
    assert "RAG 通常涉及向量检索" in task["instruction"]
    assert "Docker/K8s" in task["instruction"]
    assert "resume_profile_id=" not in task["instruction"]
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"
    assert any(
        item["reason"] == "jd_fit_stage_uses_single_user_visible_report_artifact"
        for item in decision.event_payload["repair_actions"]
    )


def test_delegate_agents_jd_fit_defers_dependent_application_task_to_main(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    context = _context()
    _append_user_message(
        repo,
        context,
        "请直接基于这个 JD artifact 分析我和岗位的匹配度，并保存岗位分析和匹配报告。",
    )

    decision = guard.inspect(
        ToolCall(
            name="delegate_agents",
            arguments={
                "tasks": [
                    {
                        "target_agent_id": "job_agent",
                        "instruction": "基于 artifact_jd_live_001 完成 JD 分析并保存 JDAnalysis。",
                        "artifact_refs": ["artifact_jd_live_001"],
                    },
                    {
                        "target_agent_id": "job_agent",
                        "instruction": (
                            "创建 CareerApplication 求职项目，关联 resume_profile_id=resume_profile_real、"
                            "career_profile_id=career_profile_default、job_fit_report_id=fit_placeholder。"
                        ),
                        "artifact_refs": [],
                    },
                ],
                "wait": True,
            },
            tool_call_id="call_delegate_with_application_child",
        ),
        context,
    )

    assert decision.result is None
    assert len(decision.tool_call.arguments["tasks"]) == 1
    task = decision.tool_call.arguments["tasks"][0]
    assert task["artifact_refs"] == ["artifact_jd_live_001"]
    assert "career_job_fit_report_save" in task["instruction"]
    assert decision.event_payload is not None
    assert any(
        item["reason"] == "jd_fit_delegation_defers_application_to_main"
        for item in decision.event_payload["repair_actions"]
    )


def test_delegate_agents_jd_fit_normalizes_malformed_mixed_task_list(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    context = _context()
    _append_user_message(
        repo,
        context,
        "请直接基于这个 JD artifact 分析我和岗位的匹配度，并保存岗位分析和匹配报告。",
    )

    decision = guard.inspect(
        ToolCall(
            name="delegate_agents",
            arguments={
                "tasks": [
                    {
                        "instruction": (
                            "基于当前 JD artifact 完成岗位分析与岗位匹配，并创建/复用求职项目。"
                            "先基于 artifact_jd_live_001 做 JDAnalysis，然后生成 JobFitReport。"
                        ),
                        "max_tool_rounds": 24,
                    },
                    {
                        "target_agent_id": "job_agent",
                        "instruction": "结合 artifact_jd_live_001 对岗位要求进行能力映射，并保存岗位匹配报告。",
                        "artifact_refs": ["artifact_jd_live_001"],
                        "max_tool_rounds": 24,
                    },
                ],
                "max_concurrency": 3,
            },
            tool_call_id="call_delegate_mixed_malformed",
        ),
        context,
    )

    assert decision.result is None
    tasks = decision.tool_call.arguments["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["target_agent_id"] == "job_agent"
    assert tasks[0]["artifact_refs"] == ["artifact_jd_live_001"]
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"
    assert any(
        item["reason"] == "delegate_task_schema_normalized"
        for item in decision.event_payload["repair_actions"]
    )


def test_delegate_agents_jd_fit_keeps_one_child_task_per_jd_source(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    context = _context()
    _append_user_message(
        repo,
        context,
        "请直接基于这个 JD artifact 分析我和岗位的匹配度，并保存岗位分析和匹配报告。",
    )

    decision = guard.inspect(
        ToolCall(
            name="delegate_agents",
            arguments={
                "tasks": [
                    {
                        "target_agent_id": "job_agent",
                        "instruction": "分析 artifact_jd_live_001，生成岗位匹配报告。",
                        "artifact_refs": ["artifact_jd_live_001"],
                    },
                    {
                        "target_agent_id": "job_agent",
                        "instruction": "读取 artifact_jd_live_001 后保存 JobFitReport。",
                        "artifact_refs": ["artifact_jd_live_001"],
                    },
                ],
                "wait": True,
            },
            tool_call_id="call_delegate_duplicate_job_fit_children",
        ),
        context,
    )

    assert decision.result is None
    assert len(decision.tool_call.arguments["tasks"]) == 1
    assert decision.event_payload is not None
    assert any(
        item["reason"] == "jd_fit_delegation_dedupes_same_source_job_task"
        for item in decision.event_payload["repair_actions"]
    )


def test_delegate_agents_moves_product_ids_out_of_artifact_refs(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    context = _context()
    _append_user_message(
        repo,
        context,
        "请直接基于这个 JD artifact 分析我和岗位的匹配度，并保存岗位分析和匹配报告。",
    )

    decision = guard.inspect(
        ToolCall(
            name="delegate_agents",
            arguments={
                "tasks": [
                    {
                        "target_agent_id": "job_agent",
                        "instruction": "使用 resume_profile_real 和 career_profile_default 分析 JD。",
                        "artifact_refs": [
                            "artifact_jd_live_001",
                            "resume_profile_real",
                            "career_profile_default",
                        ],
                    }
                ],
                "wait": True,
            },
            tool_call_id="call_delegate_product_refs",
        ),
        context,
    )

    assert decision.result is None
    task = decision.tool_call.arguments["tasks"][0]
    assert task["artifact_refs"] == ["artifact_jd_live_001"]
    assert "resume_profile_real" in task["instruction"]
    assert "career_profile_default" in task["instruction"]
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"
    assert any(
        item["reason"] == "delegate_artifact_refs_accept_only_session_artifacts"
        for item in decision.event_payload["repair_actions"]
    )


def test_delegate_agents_does_not_hide_workspace_path_artifact_refs(tmp_path: Path) -> None:
    guard, _, _ = _guard(tmp_path)
    context = _context()

    decision = guard.inspect(
        ToolCall(
            name="delegate_agents",
            arguments={
                "tasks": [
                    {
                        "target_agent_id": "job_agent",
                        "instruction": "读取文件。",
                        "artifact_refs": ["resume.txt"],
                    }
                ],
                "wait": True,
            },
            tool_call_id="call_delegate_path_ref",
        ),
        context,
    )

    assert decision.result is None
    assert decision.tool_call.arguments["tasks"][0]["artifact_refs"] == ["resume.txt"]
    assert decision.event_payload is None


def test_delegate_agents_jd_fit_does_not_reuse_until_fit_report_exists(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    context = _context()
    _append_user_message(
        repo,
        context,
        "请直接基于这个 JD artifact 分析我和岗位的匹配度，并保存岗位分析和匹配报告。",
    )
    arguments = {
        "tasks": [
            {
                "target_agent_id": "job_agent",
                "instruction": "分析 JD 并保存 JDAnalysis。",
                "artifact_refs": ["artifact_jd_live_001"],
                "max_tool_rounds": 10,
            }
        ],
        "wait": True,
    }
    repo.append_event(
        context.session_id,
        EventRecord(
            event_id="evt_delegate_call",
            session_id=context.session_id,
            type="tool_call",
            payload={"name": "delegate_agents", "arguments": arguments, "tool_call_id": "call_delegate_1"},
            created_at=_now(),
            agent_id=context.agent_id,
            run_id=context.run_id,
        ),
    )
    repo.append_event(
        context.session_id,
        EventRecord(
            event_id="evt_delegate_result",
            session_id=context.session_id,
            type="tool_result",
            payload={
                "tool_name": "delegate_agents",
                "success": True,
                "tool_call_id": "call_delegate_1",
                "content": json.dumps(
                    {"task_group_id": "task_group_jd_only", "status": "completed", "product_refs": ["jd_real"]},
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id=context.agent_id,
            run_id=context.run_id,
        ),
    )

    decision = guard.inspect(
        ToolCall(name="delegate_agents", arguments=arguments, tool_call_id="call_delegate_2"),
        context,
    )

    assert decision.result is None
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"


def test_resume_version_create_repairs_fake_product_ids(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())

    decision = guard.inspect(
        ToolCall(
            name="career_resume_version_create",
                arguments={
                    "base_resume_profile_id": "resume_profile_fake",
                    "target_jd_analysis_id": "jd_fake",
                    "artifact_id": "artifact_resume_version",
                    "evidence_refs": ["resume_profile_fake", "jd_fake", "artifact_resume_version"],
                },
            tool_call_id="call_resume_version",
        ),
        _context(),
    )

    assert decision.result is None
    assert decision.tool_call.arguments["base_resume_profile_id"] == "resume_profile_real"
    assert decision.tool_call.arguments["target_jd_analysis_id"] == "jd_real"
    assert "resume_profile_real" in decision.tool_call.arguments["evidence_refs"]
    assert "jd_real" in decision.tool_call.arguments["evidence_refs"]
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"


def test_resume_version_create_blocks_during_jd_fit_stage(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())
    context = _context()
    _append_user_message(
        repo,
        context,
        "请直接基于这个 JD artifact 分析我和岗位的匹配度，并保存岗位分析和匹配报告。",
    )

    decision = guard.inspect(
        ToolCall(
            name="career_resume_version_create",
            arguments={
                "base_resume_profile_id": "resume_profile_real",
                "target_jd_analysis_id": "jd_real",
                "title": "不该在 JD 阶段创建的简历",
                "evidence_refs": ["resume_profile_real", "jd_real", "fit_real"],
            },
            tool_call_id="call_jd_stage_version",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "jd_fit_stage_blocks_resume_version"


def test_resume_version_create_blocks_when_fit_report_is_missing(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())

    decision = guard.inspect(
        ToolCall(
            name="career_resume_version_create",
            arguments={
                "base_resume_profile_id": "resume_profile_real",
                "target_jd_analysis_id": "jd_real",
                "artifact_id": "artifact_resume_version_new",
                "evidence_refs": ["resume_profile_real", "jd_real", "artifact_resume_version_new"],
            },
            tool_call_id="call_missing_fit",
        ),
        _context(),
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["recoverable"] is True
    assert payload["reason"] == "resume_version_missing_job_fit_report"
    assert payload["missing_outputs"] == ["job_fit_report"]


def test_resume_version_create_blocks_compacted_content_without_full_body(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())

    decision = guard.inspect(
        ToolCall(
            name="career_resume_version_create",
            arguments={
                "base_resume_profile_id": "resume_profile_real",
                "target_jd_analysis_id": "jd_real",
                "title": "定制简历",
                "evidence_refs": ["resume_profile_real", "jd_real", "fit_real"],
                "content_omitted": {"chars": 486},
                "content_preview": "# 张明 ...",
            },
            tool_call_id="call_compacted_content",
        ),
        _context(),
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "resume_version_compacted_content_not_usable"
    assert payload["next_allowed_tools"] == ["career_resume_version_create"]
    assert payload["required_tools"] == ["career_resume_version_create"]
    assert payload["missing_outputs"] == ["resume_version"]
    assert "content_omitted" in payload["compacted_fields"]
    assert payload["required_tool_call_hint"]["tool_name"] == "career_resume_version_create"
    assert payload["retry_tool_call_skeleton"]["base_resume_profile_id"] == "resume_profile_real"
    assert payload["retry_tool_call_skeleton"]["target_jd_analysis_id"] == "jd_real"
    assert "content" in payload["retry_tool_call_skeleton"]
    assert "tool_search" in payload["blocked_retry_tools"]


def test_resume_version_create_allows_tool_fallback_after_validation_failure(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())
    context = _context()
    repo.append_event(
        context.session_id,
        EventRecord(
            event_id="evt_previous_version_failure",
            session_id=context.session_id,
            type="tool_result",
            payload={
                "tool_name": "career_resume_version_create",
                "success": False,
                "content": "ResumeVersion validation failed: previous invalid draft.",
                "tool_call_id": "call_previous_version_failure",
            },
            created_at=_now(),
            agent_id=context.agent_id,
            run_id=context.run_id,
        ),
    )

    decision = guard.inspect(
        ToolCall(
            name="career_resume_version_create",
            arguments={
                "base_resume_profile_id": "resume_profile_real",
                "target_jd_analysis_id": "jd_real",
                "title": "定制简历",
                "evidence_refs": ["resume_profile_real", "jd_real", "fit_real"],
                "content_omitted": {"chars": 486},
                "content_preview": "# 张明 ...",
            },
            tool_call_id="call_compacted_after_failure",
        ),
        context,
    )

    assert decision.result is None
    assert "content_omitted" not in decision.tool_call.arguments
    assert "content_preview" not in decision.tool_call.arguments
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"


def test_resume_version_create_allows_explicit_safe_fallback_without_content(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())

    decision = guard.inspect(
        ToolCall(
            name="career_resume_version_create",
            arguments={
                "base_resume_profile_id": "resume_profile_real",
                "target_jd_analysis_id": "jd_real",
                "title": "定制简历",
                "evidence_refs": ["resume_profile_real", "jd_real", "fit_real"],
                "use_safe_fallback": True,
            },
            tool_call_id="call_safe_fallback_without_content",
        ),
        _context(),
    )

    assert decision.result is None
    assert decision.tool_call.arguments["use_safe_fallback"] is True


def test_resume_version_create_reuses_existing_before_content_validation(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())
    store.save_resume_version(_resume_version())

    decision = guard.inspect(
        ToolCall(
            name="career_resume_version_create",
            arguments={
                "base_resume_profile_id": "resume_profile_real",
                "target_jd_analysis_id": "jd_real",
                "title": "定制简历",
                "evidence_refs": ["resume_profile_real", "jd_real", "fit_real"],
                "content_omitted": {"chars": 486},
                "content_preview": "# 张明 ...",
            },
            tool_call_id="call_duplicate_compacted_content",
        ),
        _context(),
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "reuse"
    assert payload["record_id"] == "resume_version_real"


def test_application_merge_blocks_resume_version_link_without_real_version(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())
    context = _context()
    _append_user_message(repo, context, "请基于刚才的岗位生成一版定制简历。")
    _append_tool_result(
        repo,
        context,
        tool_name="career_resume_version_create",
        content={
            "workflow_runtime_result": True,
            "policy": "block",
            "tool_executed": False,
            "reason": "resume_version_missing_career_application",
        },
    )

    decision = guard.inspect(
        ToolCall(
            name="career_application_merge",
            arguments={
                "application_id": "application_real",
                "updates": {
                    "resume_version_ids": ["rv_fake"],
                    "summary": "定制简历已完成。",
                },
                "evidence_refs": ["artifact_fake_resume_version"],
            },
            tool_call_id="call_fake_merge",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "resume_version_merge_without_record"
    assert payload["missing_outputs"] == ["resume_version"]
    assert payload["next_allowed_tools"] == ["career_resume_version_create"]
    assert payload["required_tools"] == ["career_resume_version_create"]
    assert "不要合并或编造" in payload["next_action"]


def test_application_merge_repairs_current_resume_version_link(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())
    store.save_resume_version(_resume_version())
    context = _context()
    _append_user_message(repo, context, "请基于刚才的岗位生成一版定制简历。")

    decision = guard.inspect(
        ToolCall(
            name="career_application_merge",
            arguments={"updates": {"stage": "ready_to_apply"}, "evidence_refs": ["fit_real"]},
            tool_call_id="call_merge_missing_refs",
        ),
        context,
    )

    assert decision.result is None
    assert decision.tool_call.arguments["application_id"] == "application_real"
    assert decision.tool_call.arguments["updates"]["resume_version_ids"] == ["resume_version_real"]
    assert "resume_version_real" in decision.tool_call.arguments["evidence_refs"]
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"


def test_application_merge_drops_non_current_resume_version_ids(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())
    store.save_resume_version(_resume_version())
    context = _context()
    _append_user_message(repo, context, "请基于刚才的岗位生成一版定制简历。")

    decision = guard.inspect(
        ToolCall(
            name="career_application_merge",
            arguments={
                "application_id": "application_real",
                "updates": {"resume_version_ids": ["resume_version_fake", "resume_version_real"]},
                "evidence_refs": ["resume_version_fake", "resume_version_real", "fit_real"],
            },
            tool_call_id="call_merge_fake_version",
        ),
        context,
    )

    assert decision.result is None
    assert decision.tool_call.arguments["updates"]["resume_version_ids"] == ["resume_version_real"]
    assert decision.tool_call.arguments["evidence_refs"] == ["resume_version_real", "fit_real"]
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"


def test_application_merge_for_interview_review_is_not_rewritten_as_resume_version_merge(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())
    store.save_resume_version(_resume_version())
    context = _context()
    _append_user_message(
        repo,
        context,
        (
            "请把这次面试复盘保存成一条 Note，并更新当前求职项目的阶段、风险、下一步行动和项目备注。"
            "不要创建学习计划或学习任务，不要重新生成匹配报告或简历版本。"
        ),
    )
    arguments = {
        "application_id": "application_real",
        "updates": {
            "stage": "interviewing",
            "next_actions": ["补强 RAG 评估回答"],
            "risks": ["召回评估指标回答不完整"],
            "notes": "面试复盘已保存为 Note note_review。",
        },
        "evidence_refs": ["application_real", "note_review", "fit_real"],
    }

    decision = guard.inspect(
        ToolCall(
            name="career_application_merge",
            arguments=arguments,
            tool_call_id="call_interview_review_merge",
        ),
        context,
    )

    assert decision.result is None
    assert decision.tool_call.arguments == arguments
    assert decision.event_payload is None


def test_career_profile_merge_removes_unsupported_update_fields(tmp_path: Path) -> None:
    guard, _, _ = _guard(tmp_path)

    decision = guard.inspect(
        ToolCall(
            name="career_profile_merge",
            arguments={
                "updates": {
                    "target_roles": ["测试工程师"],
                    "preferred_industries_note": "这是解释，不是受控字段",
                },
                "evidence_refs": ["artifact_resume"],
            },
            tool_call_id="call_profile_merge_extra_field",
        ),
        _context(),
    )

    assert decision.result is None
    assert decision.tool_call.arguments["updates"] == {"target_roles": ["测试工程师"]}
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"
    assert decision.event_payload["repair_actions"][0]["reason"] == "career_profile_merge_unsupported_fields_removed"


def test_resume_version_create_repairs_missing_target_jd_from_evidence_refs(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())
    context = _context()
    _append_user_message(repo, context, "请基于刚才的岗位生成一版定制简历。")

    decision = guard.inspect(
        ToolCall(
            name="career_resume_version_create",
                arguments={
                    "base_resume_profile_id": "resume_profile_real",
                    "title": "星河智能定制简历",
                    "artifact_id": "artifact_resume_version",
                    "evidence_refs": ["resume_profile_real", "jd_real", "fit_real"],
                },
            tool_call_id="call_repair_missing_jd",
        ),
        context,
    )

    assert decision.result is None
    assert decision.tool_call.arguments["target_jd_analysis_id"] == "jd_real"
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"


def test_resume_version_create_blocks_duplicate_stage_output(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())
    store.save_resume_version(_resume_version())

    decision = guard.inspect(
        ToolCall(
            name="career_resume_version_create",
            arguments={
                "base_resume_profile_id": "resume_profile_real",
                "target_jd_analysis_id": "jd_real",
                "artifact_id": "artifact_resume_version_new",
                "evidence_refs": ["resume_profile_real", "jd_real", "artifact_resume_version_new"],
            },
            tool_call_id="call_duplicate_version",
        ),
        _context(),
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["record_id"] == "resume_version_real"
    assert payload["policy"] == "reuse"


def test_main_jd_fit_complete_blocks_redundant_low_level_action(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())
    context = _context()
    _append_user_message(repo, context, "请分析 JD 并生成岗位匹配报告。")
    _append_tool_result(repo, context, tool_name="career_application_create", content={"record_id": "application_real"})

    decision = guard.inspect(
        ToolCall(
            name="career_jd_analysis_get",
            arguments={"jd_analysis_id": "jd_real"},
            tool_call_id="call_redundant_jd_get",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "main_jd_fit_stage_complete_final_answer"
    assert payload["terminal"] is True
    assert payload["missing_outputs"] == []
    assert payload["completed_refs"]["application_id"] == "application_real"
    assert "最终答复" in payload["next_action"]


def test_main_jd_fit_ready_blocks_redelegation_until_application_create(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    context = _context()
    _append_user_message(repo, context, "请分析 JD 并生成岗位匹配报告。")
    _append_tool_result(repo, context, tool_name="delegate_agents", content={"status": "completed"})

    decision = guard.inspect(
        ToolCall(
            name="delegate_agents",
            arguments={"tasks": [{"target_agent_id": "job_agent", "artifact_refs": ["artifact_jd"]}]},
            tool_call_id="call_redundant_delegate",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "main_jd_fit_records_ready_create_application"
    assert payload["missing_outputs"] == ["career_application"]
    assert payload["next_allowed_tools"] == ["career_application_create"]
    assert "career_application_create" in payload["next_action"]

    allowed = guard.inspect(
        ToolCall(
            name="career_application_create",
            arguments={"job_fit_report_id": "fit_real"},
            tool_call_id="call_application_create",
        ),
        context,
    )
    assert allowed.result is None


def test_main_resume_version_complete_blocks_redundant_merge(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    application = _application()
    application.resume_version_ids = ["resume_version_real"]
    store.save_career_application(application)
    store.save_resume_version(_resume_version())
    context = _context()
    _append_user_message(repo, context, "请基于刚才的岗位生成一版定制简历。")
    _append_tool_result(repo, context, tool_name="career_application_merge", content={"record_id": "application_real"})

    decision = guard.inspect(
        ToolCall(
            name="career_application_merge",
            arguments={"application_id": "application_real", "updates": {"stage": "ready_to_apply"}},
            tool_call_id="call_redundant_merge",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "main_resume_version_stage_complete_final_answer"
    assert payload["terminal"] is True
    assert payload["completed_refs"]["resume_version_id"] == "resume_version_real"
    assert payload["completed_refs"]["application_merged"] is True


def test_main_project_action_allows_application_read_after_resume_version_complete(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    application = _application()
    application.resume_version_ids = ["resume_version_real"]
    store.save_career_application(application)
    store.save_resume_version(_resume_version())
    context = _context()
    _append_user_message(
        repo,
        context,
        (
            "当前求职项目 application_id 是 application_real。请先调用 career_application_get 读取项目，"
            "再复用其中已有的 resume_profile_id、career_profile_id、jd_analysis_id、job_fit_report_id "
            "和 resume_version_ids。请执行投递前检查，检查定制简历状态。"
        ),
    )
    _append_tool_result(repo, context, tool_name="career_application_merge", content={"record_id": "application_real"})

    read_decision = guard.inspect(
        ToolCall(
            name="career_application_get",
            arguments={"application_id": "application_real"},
            tool_call_id="call_application_get",
        ),
        context,
    )
    search_decision = guard.inspect(
        ToolCall(
            name="tool_search",
            arguments={"query": "career_application_get"},
            tool_call_id="call_search_application_get",
        ),
        context,
    )

    assert read_decision.result is None
    assert search_decision.result is None


def _project_resume_version_message() -> str:
    return (
        "当前求职项目 application_id 是 application_real。请先调用 career_application_get 读取项目，"
        "再复用其中已有的 resume_profile_id、career_profile_id、jd_analysis_id、job_fit_report_id "
        "和 resume_version_ids。请生成或更新一版定制简历。必须调用 career_resume_version_create "
        "保存 ResumeVersion，再调用 career_application_merge 把新的 resume_version_id 合并进当前求职项目。"
    )


def _append_application_get_result(repo: JsonlSessionRepository, context: RunContext) -> None:
    _append_tool_result(
        repo,
        context,
        tool_name="career_application_get",
        content={
            "record_type": "career_application",
            "record_id": "application_real",
            "record": {
                "application_id": "application_real",
                "resume_profile_id": "resume_profile_real",
                "career_profile_id": "career_profile_default",
                "jd_analysis_id": "jd_real",
                "job_fit_report_id": "fit_real",
                "resume_version_ids": [],
            },
        },
    )


def test_main_project_resume_version_leaves_initial_order_to_runtime_plan(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())
    context = _context()
    _append_user_message(repo, context, _project_resume_version_message())

    search_decision = guard.inspect(
        ToolCall(
            name="tool_search",
            arguments={"query": "career_resume_version_create"},
            tool_call_id="call_project_search",
        ),
        context,
    )
    read_decision = guard.inspect(
        ToolCall(
            name="career_application_get",
            arguments={"application_id": "application_real"},
            tool_call_id="call_project_application_get",
        ),
        context,
    )

    assert read_decision.result is None
    assert search_decision.result is None


def test_main_project_resume_version_reuses_duplicate_application_get_after_read(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())
    context = _context()
    _append_user_message(repo, context, _project_resume_version_message())
    _append_application_get_result(repo, context)

    duplicate_get_decision = guard.inspect(
        ToolCall(
            name="career_application_get",
            arguments={"application_id": "application_real"},
            tool_call_id="call_duplicate_application_get",
        ),
        context,
    )
    search_decision = guard.inspect(
        ToolCall(
            name="tool_search",
            arguments={"query": "career_application_get"},
            tool_call_id="call_search_after_application_get",
        ),
        context,
    )

    assert duplicate_get_decision.result is not None
    payload = json.loads(duplicate_get_decision.result.content)
    assert payload["policy"] == "reuse"
    assert payload["reason"] == "product_record_already_read_in_run"
    assert search_decision.result is None


def test_main_resume_version_stage_blocks_duplicate_create_until_merge(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())
    store.save_resume_version(_resume_version())
    context = _context()
    _append_user_message(repo, context, _project_resume_version_message())
    _append_application_get_result(repo, context)
    _append_tool_result(
        repo,
        context,
        tool_name="career_resume_version_create",
        content={
            "record_type": "resume_version",
            "record_id": "resume_version_real",
            "record": {
                "resume_version_id": "resume_version_real",
                "artifact_id": "artifact_resume_version",
            },
        },
    )

    decision = guard.inspect(
        ToolCall(
            name="career_resume_version_create",
            arguments={
                "base_resume_profile_id": "resume_profile_real",
                "target_jd_analysis_id": "jd_real",
                "title": "重复定制简历",
                "content": "# 重复定制简历",
            },
            tool_call_id="call_duplicate_project_resume_version",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "main_resume_version_ready_merge_application"
    assert payload["next_allowed_tools"] == ["career_application_merge"]
    assert payload["missing_outputs"] == ["career_application_merge"]


def test_main_resume_version_stage_allows_explicit_new_version(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    application = _application()
    application.resume_version_ids = ["resume_version_real"]
    store.save_career_application(application)
    store.save_resume_version(_resume_version())
    context = _context()
    _append_user_message(repo, context, "请再生成一版定制简历。")
    _append_tool_result(repo, context, tool_name="career_application_merge", content={"record_id": "application_real"})

    decision = guard.inspect(
        ToolCall(
            name="career_resume_version_create",
            arguments={
                "base_resume_profile_id": "resume_profile_real",
                "target_jd_analysis_id": "jd_real",
                "title": "第二版",
                "content": "第二版内容",
                "evidence_refs": ["resume_profile_real", "jd_real", "fit_real"],
            },
            tool_call_id="call_new_version",
        ),
        context,
    )

    assert decision.result is None


def test_main_resume_diagnosis_partial_allows_profile_get(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    context = _context()
    _append_user_message(repo, context, "请诊断简历并生成简历画像。")
    _append_tool_result(repo, context, tool_name="delegate_agents", content={"resume_profile_id": "resume_profile_real"})

    decision = guard.inspect(
        ToolCall(
            name="career_resume_profile_get",
            arguments={"resume_profile_id": "resume_profile_real"},
            tool_call_id="call_profile_get",
        ),
        context,
    )

    assert decision.result is None


def test_main_resume_diagnosis_complete_blocks_redundant_read(tmp_path: Path) -> None:
    guard, store, repo = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    context = _context()
    _append_user_message(repo, context, "请诊断简历并生成简历画像。")
    _append_tool_result(repo, context, tool_name="career_profile_merge", content={"record_id": "career_profile_default"})

    decision = guard.inspect(
        ToolCall(
            name="session_read_artifact",
            arguments={"artifact_id": "artifact_resume"},
            tool_call_id="call_redundant_read",
        ),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["policy"] == "block"
    assert payload["reason"] == "main_resume_diagnosis_stage_complete_final_answer"
    assert payload["completed_refs"]["resume_profile_id"] == "resume_profile_real"


def test_application_create_reuses_existing_application_from_fit_report(tmp_path: Path) -> None:
    guard, store, _ = _guard(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_fit_report())
    store.save_career_application(_application())

    decision = guard.inspect(
        ToolCall(
            name="career_application_create",
            arguments={"job_fit_report_id": "fit_real", "evidence_refs": ["fit_real"]},
            tool_call_id="call_application",
        ),
        _context(),
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["record_id"] == "application_real"
    assert payload["idempotent_reused"] is True


def test_delegate_agents_reuses_same_run_signature(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = _context()
    arguments = {
        "tasks": [
            {
                "target_agent_id": "job_agent",
                "instruction": "分析 JD",
                "artifact_refs": ["artifact_jd"],
                "max_tool_rounds": 10,
            }
        ],
        "wait": True,
    }
    repo.append_event(
        context.session_id,
        EventRecord(
            event_id="evt_call",
            session_id=context.session_id,
            type="tool_call",
            payload={"name": "delegate_agents", "arguments": arguments, "tool_call_id": "call_delegate_1"},
            created_at=_now(),
            agent_id=context.agent_id,
            run_id=context.run_id,
        ),
    )
    repo.append_event(
        context.session_id,
        EventRecord(
            event_id="evt_result",
            session_id=context.session_id,
            type="tool_result",
            payload={
                "tool_name": "delegate_agents",
                "success": True,
                "tool_call_id": "call_delegate_1",
                "content": json.dumps(
                    {"task_group_id": "task_group_real", "status": "completed", "tasks": []},
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id=context.agent_id,
            run_id=context.run_id,
        ),
    )

    decision = guard.inspect(
        ToolCall(name="delegate_agents", arguments=arguments, tool_call_id="call_delegate_2"),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["task_group_id"] == "task_group_real"
    assert payload["idempotent_reused"] is True
    assert payload["policy"] == "reuse"


def test_delegate_agents_reuses_same_semantic_job_fit_task(tmp_path: Path) -> None:
    guard, _, repo = _guard(tmp_path)
    context = _context(run_id="run_delegate_semantic")
    first_arguments = {
        "tasks": [
            {
                "target_agent_id": "job_agent",
                "instruction": "请分析 artifact_jd 的岗位匹配报告，并保存 JobFitReport。",
                "artifact_refs": ["artifact_jd"],
                "max_tool_rounds": 8,
            }
        ],
        "wait": True,
    }
    repo.append_event(
        context.session_id,
        EventRecord(
            event_id="evt_semantic_call",
            session_id=context.session_id,
            type="tool_call",
            payload={"name": "delegate_agents", "arguments": first_arguments, "tool_call_id": "call_delegate_1"},
            created_at=_now(),
            agent_id=context.agent_id,
            run_id=context.run_id,
        ),
    )
    repo.append_event(
        context.session_id,
        EventRecord(
            event_id="evt_semantic_result",
            session_id=context.session_id,
            type="tool_result",
            payload={
                "tool_name": "delegate_agents",
                "success": True,
                "tool_call_id": "call_delegate_1",
                "content": json.dumps(
                    {"task_group_id": "task_group_semantic", "status": "completed", "tasks": []},
                    ensure_ascii=False,
                ),
            },
            created_at=_now(),
            agent_id=context.agent_id,
            run_id=context.run_id,
        ),
    )
    second_arguments = {
        "tasks": [
            {
                "target_agent_id": "job_agent",
                "instruction": "基于 artifact_jd 完成岗位匹配报告和 JobFitReport。",
                "max_tool_rounds": 16,
            }
        ],
        "wait": True,
    }

    decision = guard.inspect(
        ToolCall(name="delegate_agents", arguments=second_arguments, tool_call_id="call_delegate_2"),
        context,
    )

    assert decision.result is not None
    payload = json.loads(decision.result.content)
    assert payload["task_group_id"] == "task_group_semantic"
    assert payload["idempotent_reused"] is True
    assert payload["policy"] == "reuse"
    assert payload["lock_key"].startswith("delegate_agents_semantic:")
    assert decision.event_payload is not None
    assert decision.event_payload["semantic_signature"]
