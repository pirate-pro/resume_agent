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


def _resume_profile(record_id: str = "resume_profile_real") -> ResumeProfile:
    return ResumeProfile(
        resume_profile_id=record_id,
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_guard",
        source_artifact_id="artifact_resume",
        evidence_refs=["artifact_resume"],
        created_at=_now(),
        updated_at=_now(),
        basic_info={"name": "张明"},
        skills=["Python", "FastAPI"],
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
    assert "Python" in payload["supported_candidate_facts"]
    assert "FastAPI" in payload["supported_candidate_facts"]
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
                "artifact_refs": ["artifact_jd"],
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
                "artifact_refs": ["artifact_jd"],
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
                "artifact_refs": ["artifact_jd"],
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
    assert payload["missing_outputs"] == []
    assert "直接总结" in payload["next_action"]


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
    assert "resume_profile_id=" not in task["instruction"]
    assert decision.event_payload is not None
    assert decision.event_payload["policy"] == "repair"
    assert any(
        item["reason"] == "jd_fit_stage_uses_single_user_visible_report_artifact"
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
