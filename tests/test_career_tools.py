"""Tests for career product tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from app.career.store import CareerProductStore
from app.core.errors import ToolExecutionError
from app.core.time import app_now
from app.domain.models import EventRecord, RunContext, ToolCall
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.memory.models import MemoryScope
from app.runtime.agent_capability import AgentCapability, AgentCapabilityRegistry
from app.tools.builtins import (
    CareerApplicationCreateTool,
    CareerApplicationGetTool,
    CareerApplicationListTool,
    CareerApplicationMergeTool,
    CareerJobFitReportGetTool,
    CareerJobFitReportListTool,
    CareerJobFitReportSaveTool,
    CareerJDAnalysisGetTool,
    CareerJDAnalysisListTool,
    CareerJDAnalysisSaveTool,
    CareerProfileGetTool,
    CareerProfileMergeTool,
    CareerResumeProfileGetTool,
    CareerResumeProfileListTool,
    CareerResumeProfileSaveTool,
    CareerResumeVersionCreateTool,
    CareerResumeVersionGetTool,
    CareerResumeVersionListTool,
    SessionCreateTextArtifactTool,
    SessionReadArtifactTool,
)
from app.tools.registry import ToolRegistry

__all__ = []


def _context(session_id: str = "sess_career", agent_id: str = "agent_main") -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}_{agent_id}",
        agent_id=agent_id,
        turn_id=f"turn_{session_id}_{agent_id}",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={},
    )


def _capability_registry() -> AgentCapabilityRegistry:
    return AgentCapabilityRegistry(
        {
            "agent_main": AgentCapability(
                agent_id="agent_main",
                allowed_tools=[
                    "session_create_text_artifact",
                    "session_read_artifact",
                    "career_resume_profile_get",
                    "career_resume_profile_list",
                    "career_profile_get",
                    "career_profile_merge",
                    "career_jd_analysis_get",
                    "career_jd_analysis_list",
                    "career_job_fit_report_get",
                    "career_job_fit_report_list",
                    "career_resume_version_create",
                    "career_resume_version_get",
                    "career_resume_version_list",
                    "career_application_create",
                    "career_application_get",
                    "career_application_list",
                    "career_application_merge",
                ],
                allowed_skills=["*"],
                default_skills=["base"],
                memory_read_scopes=[MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                memory_write_scopes=[MemoryScope.AGENT_LONG],
                allow_cross_session_short_read=False,
                allow_cross_agent_memory_read=False,
                allow_cross_agent_memory_write=False,
            ),
            "resume_agent": AgentCapability(
                agent_id="resume_agent",
                allowed_tools=[
                    "session_create_text_artifact",
                    "session_read_artifact",
                    "career_resume_profile_save",
                    "career_resume_profile_get",
                ],
                allowed_skills=["*"],
                default_skills=["base"],
                memory_read_scopes=[MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                memory_write_scopes=[MemoryScope.AGENT_LONG],
                allow_cross_session_short_read=False,
                allow_cross_agent_memory_read=False,
                allow_cross_agent_memory_write=False,
            ),
            "job_agent": AgentCapability(
                agent_id="job_agent",
                allowed_tools=[
                    "session_create_text_artifact",
                    "session_read_artifact",
                    "career_resume_profile_get",
                    "career_profile_get",
                    "career_jd_analysis_save",
                    "career_jd_analysis_get",
                    "career_job_fit_report_save",
                    "career_job_fit_report_get",
                ],
                allowed_skills=["*"],
                default_skills=["base"],
                memory_read_scopes=[MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                memory_write_scopes=[MemoryScope.AGENT_LONG],
                allow_cross_session_short_read=False,
                allow_cross_agent_memory_read=False,
                allow_cross_agent_memory_write=False,
            ),
        }
    )


def _registry(tmp_path: Path) -> tuple[ToolRegistry, JsonlSessionRepository]:
    session_repository = JsonlSessionRepository(data_dir=tmp_path / "sessions")
    career_store = CareerProductStore(root_dir=tmp_path / "career")
    registry = ToolRegistry(capability_registry=_capability_registry())
    registry.register(SessionCreateTextArtifactTool(session_repository=session_repository))
    registry.register(SessionReadArtifactTool(session_repository=session_repository))
    registry.register(
        CareerResumeProfileSaveTool(career_store=career_store, session_repository=session_repository)
    )
    registry.register(CareerResumeProfileGetTool(career_store=career_store))
    registry.register(CareerResumeProfileListTool(career_store=career_store))
    registry.register(CareerProfileGetTool(career_store=career_store))
    registry.register(CareerProfileMergeTool(career_store=career_store, session_repository=session_repository))
    registry.register(CareerJDAnalysisSaveTool(career_store=career_store, session_repository=session_repository))
    registry.register(CareerJDAnalysisGetTool(career_store=career_store))
    registry.register(CareerJDAnalysisListTool(career_store=career_store))
    registry.register(CareerJobFitReportSaveTool(career_store=career_store, session_repository=session_repository))
    registry.register(CareerJobFitReportGetTool(career_store=career_store))
    registry.register(CareerJobFitReportListTool(career_store=career_store))
    registry.register(CareerResumeVersionCreateTool(career_store=career_store, session_repository=session_repository))
    registry.register(CareerResumeVersionGetTool(career_store=career_store))
    registry.register(CareerResumeVersionListTool(career_store=career_store))
    registry.register(CareerApplicationCreateTool(career_store=career_store, session_repository=session_repository))
    registry.register(CareerApplicationGetTool(career_store=career_store))
    registry.register(CareerApplicationListTool(career_store=career_store))
    registry.register(CareerApplicationMergeTool(career_store=career_store, session_repository=session_repository))
    return registry, session_repository


def _execute(registry: ToolRegistry, name: str, arguments: dict[str, Any], context: RunContext) -> dict[str, Any]:
    result = registry.execute(ToolCall(name=name, arguments=arguments), context=context)
    assert result.success is True
    return cast(dict[str, Any], json.loads(result.content))


def _create_text_artifact(
    registry: ToolRegistry,
    *,
    session_id: str = "sess_career",
    agent_id: str = "agent_main",
    title: str = "资料.txt",
    content: str = "Python 后端经验",
    kind: str = "pasted_text",
    media_type: str = "text/plain",
) -> str:
    payload = _execute(
        registry,
        "session_create_text_artifact",
        {
            "title": title,
            "content": content,
            "kind": kind,
            "media_type": media_type,
        },
        _context(session_id, agent_id),
    )
    return str(payload["artifact_id"])


def _append_tool_result_event(
    session_repository: JsonlSessionRepository,
    *,
    context: RunContext,
    tool_name: str,
    payload: dict[str, Any],
    event_id: str = "evt_tool_result",
) -> None:
    session_repository.append_agent_event(
        context.session_id,
        context.agent_id,
        EventRecord(
            event_id=event_id,
            session_id=context.session_id,
            type="tool_result",
            payload={
                "tool_name": tool_name,
                "success": True,
                "content": json.dumps(payload, ensure_ascii=False),
                "tool_call_id": f"call_{event_id}",
            },
            created_at=app_now(),
            agent_id=context.agent_id,
            run_id=context.run_id,
            parent_run_id=context.parent_run_id,
        ),
    )


def _save_resume_profile(registry: ToolRegistry, resume_artifact_id: str, diagnosis_artifact_id: str) -> dict[str, Any]:
    return _execute(
        registry,
        "career_resume_profile_save",
        {
            "resume_profile_id": "resume_profile_alpha",
            "source_artifact_id": resume_artifact_id,
            "evidence_refs": [resume_artifact_id],
            "basic_info": {"name": "候选人"},
            "skills": ["Python", "FastAPI"],
            "raw_text_artifact_id": resume_artifact_id,
            "diagnosis_artifact_id": diagnosis_artifact_id,
            "diagnosis": {"strengths": ["后端经验"]},
        },
        _context(agent_id="resume_agent"),
    )


def test_session_create_text_artifact_is_pathless_and_readable(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")

    artifact_id = _create_text_artifact(
        registry,
        title="岗位 JD.txt",
        content="需要 Python 和 RAG 经验",
        kind="pasted_text",
        media_type="text/plain",
    )
    read_payload = _execute(
        registry,
        "session_read_artifact",
        {"artifact_id": artifact_id, "max_chars": 500},
        _context(),
    )
    definition = next(item for item in registry.list_definitions() if item.name == "session_create_text_artifact")

    assert read_payload["content"] == "需要 Python 和 RAG 经验"
    assert "path" not in definition.parameters_schema["properties"]

    with pytest.raises(ToolExecutionError):
        registry.execute(
            ToolCall(
                name="session_create_text_artifact",
                arguments={"title": "空.txt", "content": ""},
            ),
            context=_context(),
        )
    with pytest.raises(ToolExecutionError):
        registry.execute(
            ToolCall(
                name="session_create_text_artifact",
                arguments={"title": "错误.txt", "content": "x", "kind": "uploaded_file"},
            ),
            context=_context(),
        )
    with pytest.raises(ToolExecutionError):
        registry.execute(
            ToolCall(
                name="session_create_text_artifact",
                arguments={"title": "错误.txt", "content": "x", "media_type": "application/json"},
            ),
            context=_context(),
        )


def test_session_create_text_artifact_updates_same_run_generated_report(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    context = _context(agent_id="resume_agent")

    first_payload = _execute(
        registry,
        "session_create_text_artifact",
        {
            "title": "简历诊断报告_张三",
            "content": "第一版诊断",
            "kind": "generated_file",
            "media_type": "text/markdown",
        },
        context,
    )
    _append_tool_result_event(
        session_repository,
        context=context,
        tool_name="session_create_text_artifact",
        payload=first_payload,
    )

    second_payload = _execute(
        registry,
        "session_create_text_artifact",
        {
            "title": "张三简历诊断报告.md",
            "content": "第二版诊断，更完整",
            "kind": "generated_file",
            "media_type": "text/markdown",
        },
        context,
    )
    artifacts = session_repository.list_session_artifacts("sess_career")

    assert second_payload["artifact_id"] == first_payload["artifact_id"]
    assert second_payload["idempotent_update"] is True
    assert second_payload["title"] == "张三简历诊断报告.md"
    assert session_repository.read_session_artifact_text("sess_career", str(first_payload["artifact_id"])) == "第二版诊断，更完整"
    assert [item.kind for item in artifacts if item.owner_agent_id == "resume_agent"] == ["generated_file"]


def test_session_create_text_artifact_treats_job_fit_analysis_report_as_fit_report(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    context = _context(agent_id="job_agent")

    first_payload = _execute(
        registry,
        "session_create_text_artifact",
        {
            "title": "岗位匹配分析报告.md",
            "content": "第一版匹配分析",
            "kind": "generated_file",
            "media_type": "text/markdown",
        },
        context,
    )
    _append_tool_result_event(
        session_repository,
        context=context,
        tool_name="session_create_text_artifact",
        payload=first_payload,
    )

    second_payload = _execute(
        registry,
        "session_create_text_artifact",
        {
            "title": "AI应用开发工程师-候选人匹配分析报告",
            "content": "第二版匹配分析",
            "kind": "generated_file",
            "media_type": "text/markdown",
        },
        context,
    )

    assert second_payload["artifact_id"] == first_payload["artifact_id"]
    assert second_payload["idempotent_update"] is True
    assert len(session_repository.list_session_artifacts("sess_career")) == 1


def test_session_create_text_artifact_does_not_dedupe_pasted_text(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    context = _context(agent_id="agent_main")

    first_payload = _execute(
        registry,
        "session_create_text_artifact",
        {
            "title": "岗位 JD.txt",
            "content": "第一份 JD",
            "kind": "pasted_text",
            "media_type": "text/plain",
        },
        context,
    )
    _append_tool_result_event(
        session_repository,
        context=context,
        tool_name="session_create_text_artifact",
        payload=first_payload,
    )
    second_payload = _execute(
        registry,
        "session_create_text_artifact",
        {
            "title": "岗位 JD.txt",
            "content": "第二份 JD",
            "kind": "pasted_text",
            "media_type": "text/plain",
        },
        context,
    )

    assert second_payload["artifact_id"] != first_payload["artifact_id"]
    assert "idempotent_update" not in second_payload
    assert len(session_repository.list_session_artifacts("sess_career")) == 2


def test_resume_profile_tool_uses_context_source_and_rejects_store_owned_fields(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历.txt")
    diagnosis_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="简历诊断.md",
        content="# 简历诊断",
        kind="generated_file",
        media_type="text/markdown",
    )

    payload = _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)
    loaded = _execute(
        registry,
        "career_resume_profile_get",
        {"resume_profile_id": "resume_profile_alpha"},
        _context(agent_id="agent_main"),
    )
    fallback_loaded = _execute(
        registry,
        "career_resume_profile_get",
        {"resume_profile_id": "resume_profile_guessed"},
        _context(agent_id="agent_main"),
    )
    missing_career_profile = _execute(
        registry,
        "career_profile_get",
        {"career_profile_id": "career_profile_default"},
        _context(agent_id="agent_main"),
    )
    duplicate_payload = _execute(
        registry,
        "career_resume_profile_save",
        {
            "resume_profile_id": "resume_profile_duplicate",
            "source_artifact_id": resume_artifact_id,
            "evidence_refs": [resume_artifact_id],
            "basic_info": {"name": "重复候选人"},
        },
        _context(agent_id="resume_agent"),
    )

    assert payload["source_session_id"] == "sess_career"
    assert payload["record"]["diagnosis_artifact_id"] == diagnosis_artifact_id
    assert loaded["record"]["basic_info"]["name"] == "候选人"
    assert fallback_loaded["found"] is True
    assert fallback_loaded["record_id"] == "resume_profile_alpha"
    assert fallback_loaded["requested_record_id"] == "resume_profile_guessed"
    assert fallback_loaded["resolved_from_missing_id"] is True
    assert missing_career_profile["found"] is False
    assert duplicate_payload["record_id"] == "resume_profile_alpha"
    assert duplicate_payload["idempotent_reused"] is True

    with pytest.raises(ToolExecutionError):
        registry.execute(
            ToolCall(
                name="career_resume_profile_save",
                arguments={
                    "source_artifact_id": resume_artifact_id,
                    "evidence_refs": [resume_artifact_id],
                    "created_at": "1999-01-01T00:00:00Z",
                },
            ),
            context=_context(agent_id="resume_agent"),
        )
    with pytest.raises(ToolExecutionError):
        registry.execute(
            ToolCall(
                name="career_resume_profile_save",
                arguments={
                    "source_artifact_id": resume_artifact_id,
                    "evidence_refs": [resume_artifact_id],
                    "path": "resume.json",
                },
            ),
            context=_context(agent_id="resume_agent"),
        )
    with pytest.raises(ToolExecutionError, match="not allowed"):
        registry.execute(
            ToolCall(
                name="career_resume_profile_save",
                arguments={"source_artifact_id": resume_artifact_id, "evidence_refs": [resume_artifact_id]},
            ),
            context=_context(agent_id="agent_main"),
        )


def test_career_tool_rejects_artifacts_outside_current_session(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    session_repository.create_session("sess_other")
    other_artifact_id = _create_text_artifact(registry, session_id="sess_other", title="其他会话简历.txt")

    with pytest.raises(ToolExecutionError):
        registry.execute(
            ToolCall(
                name="career_resume_profile_save",
                arguments={"source_artifact_id": other_artifact_id, "evidence_refs": [other_artifact_id]},
            ),
            context=_context(agent_id="resume_agent"),
        )


def test_job_agent_saves_jd_and_fit_report_but_cannot_merge_profile(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历.txt")
    diagnosis_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历诊断.md")
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)
    jd_artifact_id = _create_text_artifact(registry, agent_id="job_agent", title="JD.txt", content="需要 RAG")
    report_artifact_id = _create_text_artifact(
        registry,
        agent_id="job_agent",
        title="匹配报告.md",
        content="# 匹配报告",
        kind="generated_file",
        media_type="text/markdown",
    )

    jd_payload = _execute(
        registry,
        "career_jd_analysis_save",
        {
            "jd_analysis_id": "jd_alpha",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [jd_artifact_id, "jd_analysis", "career_profile_merge"],
            "company": "Example Co",
            "position": "AI 应用开发工程师",
            "required_skills": ["Python", "RAG"],
        },
        _context(agent_id="job_agent"),
    )
    duplicate_jd_payload = _execute(
        registry,
        "career_jd_analysis_save",
        {
            "jd_analysis_id": "jd_beta",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [jd_artifact_id],
            "company": "Other Co",
            "position": "重复岗位",
        },
        _context(agent_id="job_agent"),
    )
    fit_payload = _execute(
        registry,
        "career_job_fit_report_save",
        {
            "job_fit_report_id": "fit_alpha",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [
                "resume_profile_alpha",
                "career_profile_default",
                "career_profile_merge",
                "jd_analysis",
                "jd_alpha",
                jd_artifact_id,
                report_artifact_id,
            ],
            "jd_analysis_id": "jd_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "overall_score": "82",
            "score_breakdown": {"skills": "80", "projects": "85/100", "growth": 0.9},
            "recommendation": "recommended",
            "report_artifact_id": report_artifact_id,
        },
        _context(agent_id="job_agent"),
    )
    duplicate_fit_payload = _execute(
        registry,
        "career_job_fit_report_save",
        {
            "job_fit_report_id": "fit_beta",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [
                "resume_profile_alpha",
                "career_profile_default",
                "jd_alpha",
                jd_artifact_id,
                report_artifact_id,
            ],
            "jd_analysis_id": "jd_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "report_artifact_id": report_artifact_id,
        },
        _context(agent_id="job_agent"),
    )

    assert jd_payload["record"]["source_artifact_id"] == jd_artifact_id
    assert duplicate_jd_payload["record_id"] == "jd_alpha"
    assert duplicate_jd_payload["idempotent_reused"] is True
    assert "career_profile_merge" not in jd_payload["record"]["evidence_refs"]
    assert "jd_analysis" not in jd_payload["record"]["evidence_refs"]
    assert fit_payload["record"]["source_artifact_id"] == jd_artifact_id
    assert fit_payload["record"]["report_artifact_id"] == report_artifact_id
    assert "career_profile_merge" not in fit_payload["record"]["evidence_refs"]
    assert "jd_analysis" not in fit_payload["record"]["evidence_refs"]
    assert fit_payload["record"]["overall_score"] == 82
    assert fit_payload["record"]["score_breakdown"] == {"skills": 80, "projects": 85, "growth": 90}
    created_default_profile = _execute(
        registry,
        "career_profile_get",
        {"career_profile_id": "career_profile_default"},
        _context(agent_id="agent_main"),
    )
    assert created_default_profile["found"] is True
    assert created_default_profile["record"]["source_artifact_id"] == jd_artifact_id
    assert duplicate_fit_payload["record_id"] == "fit_alpha"
    assert duplicate_fit_payload["idempotent_reused"] is True

    repaired_missing_profile_payload = _execute(
        registry,
        "career_job_fit_report_save",
        {
            "job_fit_report_id": "fit_missing_profile",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [
                "resume_profile_alpha",
                "career_profile_missing",
                "jd_alpha",
                jd_artifact_id,
                report_artifact_id,
            ],
            "jd_analysis_id": "jd_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_missing",
            "report_artifact_id": report_artifact_id,
        },
        _context(agent_id="job_agent"),
    )
    assert repaired_missing_profile_payload["record_id"] == "fit_alpha"
    assert repaired_missing_profile_payload["idempotent_reused"] is True
    assert repaired_missing_profile_payload["record"]["career_profile_id"] == "career_profile_default"

    repaired_missing_jd_payload = _execute(
        registry,
        "career_job_fit_report_save",
        {
            "job_fit_report_id": "fit_alpha",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": ["resume_profile_alpha", "career_profile_default", "jd_beta", jd_artifact_id],
            "jd_analysis_id": "jd_beta",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "report_artifact_id": report_artifact_id,
        },
        _context(agent_id="job_agent"),
    )
    assert repaired_missing_jd_payload["record_id"] == "fit_alpha"
    assert repaired_missing_jd_payload["record"]["jd_analysis_id"] == "jd_alpha"
    assert "jd_beta" not in repaired_missing_jd_payload["record"]["evidence_refs"]
    with pytest.raises(ToolExecutionError, match="not allowed"):
        registry.execute(
            ToolCall(
                name="career_profile_merge",
                arguments={"updates": {"career_goal": "AI"}, "evidence_refs": ["resume_profile_alpha"]},
            ),
            context=_context(agent_id="job_agent"),
        )


def test_job_fit_report_save_derives_and_normalizes_evidence_refs(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历.txt")
    diagnosis_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历诊断.md")
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)
    jd_artifact_id = _create_text_artifact(registry, agent_id="job_agent", title="JD.txt", content="需要 Python 和 RAG")
    report_artifact_id = _create_text_artifact(
        registry,
        agent_id="job_agent",
        title="匹配报告.md",
        content="# 匹配报告",
        kind="generated_file",
        media_type="text/markdown",
    )

    payload_without_refs = _execute(
        registry,
        "career_job_fit_report_save",
        {
            "job_fit_report_id": "fit_derived_refs",
            "source_artifact_id": jd_artifact_id,
            "jd_analysis_id": "jd_derived_refs",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "report_artifact_id": report_artifact_id,
            "overall_score": 80,
        },
        _context(agent_id="job_agent"),
    )
    assert set(payload_without_refs["record"]["evidence_refs"]) >= {
        "resume_profile_alpha",
        "career_profile_default",
        "jd_derived_refs",
        jd_artifact_id,
        report_artifact_id,
    }

    another_report_artifact_id = _create_text_artifact(
        registry,
        agent_id="job_agent",
        title="匹配报告-2.md",
        content="# 匹配报告",
        kind="generated_file",
        media_type="text/markdown",
    )
    another_jd_artifact_id = _create_text_artifact(
        registry,
        agent_id="job_agent",
        title="JD-2.txt",
        content="需要 FastAPI 和 Agent 经验",
    )
    payload_with_key_value_refs = _execute(
        registry,
        "career_job_fit_report_save",
        {
            "job_fit_report_id": "fit_key_value_refs",
            "source_artifact_id": another_jd_artifact_id,
            "jd_analysis_id": "jd_key_value_refs",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "report_artifact_id": another_report_artifact_id,
            "evidence_refs": [
                "resume_profile_id=resume_profile_alpha",
                "career_profile_id=career_profile_default",
                "jd_analysis_id=jd_key_value_refs",
                f"source_artifact_id={another_jd_artifact_id}",
                f"report_artifact_id={another_report_artifact_id}",
            ],
        },
        _context(agent_id="job_agent"),
    )
    assert set(payload_with_key_value_refs["record"]["evidence_refs"]) >= {
        "resume_profile_alpha",
        "career_profile_default",
        "jd_key_value_refs",
        another_jd_artifact_id,
        another_report_artifact_id,
    }


def test_resume_version_create_repairs_missing_jd_id_when_single_current_jd_exists(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历.txt")
    diagnosis_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历诊断.md")
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)
    jd_artifact_id = _create_text_artifact(registry, agent_id="job_agent", title="JD.txt", content="需要 RAG")

    _execute(
        registry,
        "career_jd_analysis_save",
        {
            "jd_analysis_id": "jd_real",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [jd_artifact_id],
            "position": "AI 应用开发工程师",
        },
        _context(agent_id="job_agent"),
    )
    payload = _execute(
        registry,
        "career_resume_version_create",
            {
                "base_resume_profile_id": "resume_profile_alpha",
                "target_jd_analysis_id": "jd_fake",
                "title": "定制简历",
                "content": "# 张三\n\n技能：Python、FastAPI。",
                "evidence_refs": ["resume_profile_alpha", "jd_fake"],
            },
            _context(agent_id="agent_main"),
        )

    assert payload["record"]["target_jd_analysis_id"] == "jd_real"
    assert "jd_real" in payload["record"]["evidence_refs"]
    assert "jd_fake" not in payload["record"]["evidence_refs"]


def test_application_create_repairs_ids_from_current_fit_report(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历.txt")
    diagnosis_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历诊断.md")
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)
    jd_artifact_id = _create_text_artifact(registry, agent_id="job_agent", title="JD.txt", content="需要 RAG")
    report_artifact_id = _create_text_artifact(
        registry,
        agent_id="job_agent",
        title="匹配报告.md",
        content="# 匹配报告",
        kind="generated_file",
        media_type="text/markdown",
    )

    _execute(
        registry,
        "career_jd_analysis_save",
        {
            "jd_analysis_id": "jd_real",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [jd_artifact_id],
            "position": "AI 应用开发工程师",
        },
        _context(agent_id="job_agent"),
    )
    _execute(
        registry,
        "career_job_fit_report_save",
        {
            "job_fit_report_id": "fit_real",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": ["resume_profile_alpha", "career_profile_default", "jd_real", report_artifact_id],
            "jd_analysis_id": "jd_real",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "report_artifact_id": report_artifact_id,
        },
        _context(agent_id="job_agent"),
    )
    payload = _execute(
        registry,
        "career_application_create",
        {
            "job_fit_report_id": "fit_real",
            "jd_analysis_id": "jd_fake",
            "resume_profile_id": "resume_profile_fake",
            "evidence_refs": ["fit_real", "jd_fake", "resume_profile_fake"],
        },
        _context(agent_id="agent_main"),
    )

    assert payload["record"]["jd_analysis_id"] == "jd_real"
    assert payload["record"]["resume_profile_id"] == "resume_profile_alpha"
    assert "jd_real" in payload["record"]["evidence_refs"]
    assert "jd_fake" not in payload["record"]["evidence_refs"]
    assert "resume_profile_fake" not in payload["record"]["evidence_refs"]


def test_application_create_infers_single_current_fit_report_when_ids_are_missing(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历.txt")
    diagnosis_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历诊断.md")
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)
    jd_artifact_id = _create_text_artifact(registry, agent_id="job_agent", title="JD.txt", content="需要 RAG")
    report_artifact_id = _create_text_artifact(
        registry,
        agent_id="job_agent",
        title="匹配报告.md",
        content="# 匹配报告",
        kind="generated_file",
        media_type="text/markdown",
    )

    _execute(
        registry,
        "career_jd_analysis_save",
        {
            "jd_analysis_id": "jd_real",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [jd_artifact_id],
            "position": "AI 应用开发工程师",
        },
        _context(agent_id="job_agent"),
    )
    _execute(
        registry,
        "career_job_fit_report_save",
        {
            "job_fit_report_id": "fit_real",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": ["resume_profile_alpha", "career_profile_default", "jd_real", report_artifact_id],
            "jd_analysis_id": "jd_real",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "report_artifact_id": report_artifact_id,
        },
        _context(agent_id="job_agent"),
    )
    payload = _execute(
        registry,
        "career_application_create",
        {
            "source_artifact_id": jd_artifact_id,
            "status": "ready_to_apply",
            "created_at": "1999-01-01T00:00:00Z",
            "summary": "已完成岗位匹配，创建求职项目。",
        },
        _context(agent_id="agent_main"),
    )

    assert payload["record"]["jd_analysis_id"] == "jd_real"
    assert payload["record"]["job_fit_report_id"] == "fit_real"
    assert payload["record"]["resume_profile_id"] == "resume_profile_alpha"
    assert payload["record"]["career_profile_id"] == "career_profile_default"
    assert payload["record"]["stage"] == "ready_to_apply"
    assert {"fit_real", "jd_real", "resume_profile_alpha", report_artifact_id}.issubset(
        set(payload["record"]["evidence_refs"])
    )


def test_job_fit_report_save_creates_missing_jd_analysis_ref_from_source_artifact(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="简历.txt",
        content="候选人具备 Python、FastAPI 后端开发经验。",
    )
    diagnosis_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历诊断.md")
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)
    jd_artifact_id = _create_text_artifact(
        registry,
        agent_id="job_agent",
        title="JD.txt",
        content="公司招聘 AI 应用开发工程师，要求 Python、FastAPI、RAG、Agent 工程经验和向量检索。",
    )
    report_artifact_id = _create_text_artifact(
        registry,
        agent_id="job_agent",
        title="匹配报告.md",
        content="# 匹配报告",
        kind="generated_file",
        media_type="text/markdown",
    )

    payload = _execute(
        registry,
        "career_job_fit_report_save",
        {
            "job_fit_report_id": "fit_missing_jd",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": ["resume_profile_alpha", "career_profile_default", "jd_missing", report_artifact_id],
            "jd_analysis_id": "jd_missing",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "report_artifact_id": report_artifact_id,
            "matched_evidence": ["Python 与 FastAPI 匹配"],
            "gaps": ["向量检索未体现"],
        },
        _context(agent_id="job_agent"),
    )
    jd_payload = _execute(
        registry,
        "career_jd_analysis_get",
        {"jd_analysis_id": "jd_missing"},
        _context(agent_id="agent_main"),
    )

    assert payload["record"]["jd_analysis_id"] == "jd_missing"
    assert "jd_missing" in payload["record"]["evidence_refs"]
    assert jd_payload["found"] is True
    assert jd_payload["record"]["source_artifact_id"] == jd_artifact_id
    assert jd_payload["record"]["position"] == "AI 应用开发工程师"
    assert {"Python", "FastAPI", "RAG", "Agent", "向量检索"}.issubset(
        set(jd_payload["record"]["required_skills"])
    )


def test_get_tools_recover_from_invalid_id_format_when_session_record_is_unambiguous(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历.txt")
    diagnosis_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历诊断.md")
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)
    jd_artifact_id = _create_text_artifact(registry, agent_id="job_agent", title="JD.txt", content="需要 RAG")
    report_artifact_id = _create_text_artifact(
        registry,
        agent_id="job_agent",
        title="匹配报告.md",
        content="# 匹配报告",
        kind="generated_file",
        media_type="text/markdown",
    )
    _execute(
        registry,
        "career_jd_analysis_save",
        {
            "jd_analysis_id": "jd_alpha",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [jd_artifact_id],
        },
        _context(agent_id="job_agent"),
    )
    _execute(
        registry,
        "career_job_fit_report_save",
        {
            "job_fit_report_id": "fit_alpha",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [
                "resume_profile_alpha",
                "career_profile_default",
                "jd_alpha",
                jd_artifact_id,
                report_artifact_id,
            ],
            "jd_analysis_id": "jd_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "report_artifact_id": report_artifact_id,
        },
        _context(agent_id="job_agent"),
    )

    recovered = _execute(
        registry,
        "career_job_fit_report_get",
        {"job_fit_report_id": "job_fit_report_alpha"},
        _context(agent_id="agent_main"),
    )
    missing = _execute(
        registry,
        "career_resume_version_get",
        {"resume_version_id": "version_alpha"},
        _context(agent_id="agent_main"),
    )

    assert recovered["record_id"] == "fit_alpha"
    assert recovered["requested_record_id"] == "job_fit_report_alpha"
    assert recovered["invalid_id_format"] is True
    assert recovered["resolved_from_invalid_id"] is True
    assert missing["found"] is False
    assert missing["invalid_id_format"] is True
    assert "list tool" in missing["hint"]


def test_job_fit_report_save_moves_unsupported_candidate_claims_to_gaps(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="简历.txt",
        content="候选人：张三\n技能：Python、FastAPI。",
    )
    diagnosis_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="诊断.md",
        content="# 诊断",
        kind="generated_file",
        media_type="text/markdown",
    )
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)
    jd_artifact_id = _create_text_artifact(
        registry,
        agent_id="job_agent",
        title="JD.txt",
        content="需要 Python、FastAPI、向量检索经验。",
    )
    report_artifact_id = _create_text_artifact(
        registry,
        agent_id="job_agent",
        title="匹配报告.md",
        content="# 匹配报告",
        kind="generated_file",
        media_type="text/markdown",
    )
    _execute(
        registry,
        "career_jd_analysis_save",
        {
            "jd_analysis_id": "jd_alpha",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [jd_artifact_id],
            "required_skills": ["Python", "FastAPI", "向量检索"],
        },
        _context(agent_id="job_agent"),
    )

    payload = _execute(
        registry,
        "career_job_fit_report_save",
        {
            "job_fit_report_id": "fit_alpha",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": ["resume_profile_alpha", "career_profile_default", "jd_alpha", report_artifact_id],
            "jd_analysis_id": "jd_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "report_artifact_id": report_artifact_id,
            "matched_evidence": [
                "Python：简历明确列出",
                "向量检索：简历 RAG 项目隐含具备向量检索能力",
            ],
            "gaps": [],
        },
        _context(agent_id="job_agent"),
    )

    record = payload["record"]
    assert record["matched_evidence"] == ["Python：简历明确列出"]
    assert any("向量检索" in item and "未证实匹配项已转为差距" in item for item in record["gaps"])


def test_resume_profile_save_accepts_single_string_for_list_fields(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历.txt")

    payload = _execute(
        registry,
        "career_resume_profile_save",
        {
            "resume_profile_id": "resume_profile_string_list",
            "source_artifact_id": resume_artifact_id,
            "evidence_refs": [resume_artifact_id],
            "skills": "Python / FastAPI",
            "project_experience": "简历诊断 Agent",
        },
        _context(agent_id="resume_agent"),
    )

    assert payload["record"]["skills"] == ["Python / FastAPI"]
    assert payload["record"]["project_experience"] == ["简历诊断 Agent"]


def test_resume_profile_save_preserves_unparseable_diagnosis_text(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="简历.txt")

    payload = _execute(
        registry,
        "career_resume_profile_save",
        {
            "resume_profile_id": "resume_profile_diagnosis_text",
            "source_artifact_id": resume_artifact_id,
            "evidence_refs": [resume_artifact_id],
            "diagnosis": '{"summary": "补充量化成果，如"响应降低 30%""}',
        },
        _context(agent_id="resume_agent"),
    )

    assert payload["record"]["diagnosis"] == {
        "raw_text": '{"summary": "补充量化成果，如"响应降低 30%""}'
    }


def test_resume_profile_save_rejects_profile_that_drops_source_tech_evidence(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="简历.txt",
        content="技能：Python、FastAPI、PostgreSQL、Redis、RAG、Agent 工具调用。",
    )

    with pytest.raises(ToolExecutionError, match="明确技术证据不一致"):
        registry.execute(
            ToolCall(
                name="career_resume_profile_save",
                arguments={
                    "resume_profile_id": "resume_profile_bad_alignment",
                    "source_artifact_id": resume_artifact_id,
                    "evidence_refs": [resume_artifact_id],
                    "skills": [{"category": "编程语言", "items": ["Java"]}],
                    "work_experience": [{"position": "Java 后端开发"}],
                    "diagnosis": {"missing": ["Python/FastAPI/RAG/Agent 均未提及"]},
                },
            ),
            context=_context(agent_id="resume_agent"),
        )


def test_resume_version_create_rejects_unverified_quantified_metrics(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="简历.txt",
        content="候选人：张三\n项目：优化接口性能，响应速度提升 30%。\n技能：Python、FastAPI。",
    )
    diagnosis_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="诊断.md",
        content="# 诊断",
        kind="generated_file",
        media_type="text/markdown",
    )
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)

    allowed_payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "base_resume_profile_id": "resume_profile_alpha",
            "target_jd_analysis_id": "jd_alpha",
            "title": "证实量化指标版本",
            "content": "# 张三\n\n优化接口性能，响应速度提升 30%。",
            "evidence_refs": ["resume_profile_alpha", "jd_alpha"],
        },
        _context(agent_id="agent_main"),
    )

    assert allowed_payload["record"]["artifact_id"].startswith("artifact_")

    with pytest.raises(ToolExecutionError, match="Retry career_resume_version_create immediately"):
        registry.execute(
            ToolCall(
                name="career_resume_version_create",
                arguments={
                    "base_resume_profile_id": "resume_profile_alpha",
                    "target_jd_analysis_id": "jd_alpha",
                    "title": "未证实量化指标版本",
                    "content": "# 张三\n\n上线后客服效率提升 60%，问题解决率达 85%，服务可用性达 99.99%。",
                    "evidence_refs": ["resume_profile_alpha", "jd_alpha"],
                },
            ),
            context=_context(agent_id="agent_main"),
        )


def test_resume_version_create_rejects_unverified_counts_and_years(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="简历.txt",
        content="候选人：张三\n经历：3 年后端开发经验。\n技能：Python、FastAPI。",
    )
    diagnosis_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="诊断.md",
        content="# 诊断",
        kind="generated_file",
        media_type="text/markdown",
    )
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)

    with pytest.raises(ToolExecutionError, match="unverified quantitative metrics"):
        registry.execute(
            ToolCall(
                name="career_resume_version_create",
                arguments={
                    "base_resume_profile_id": "resume_profile_alpha",
                    "target_jd_analysis_id": "jd_alpha",
                    "title": "伪造数量指标版本",
                    "content": "# 张三\n\n具备 1 年经验，设计 12 个维度评估模型和 50+ 诊断算法。",
                    "evidence_refs": ["resume_profile_alpha", "jd_alpha"],
                },
            ),
            context=_context(agent_id="agent_main"),
        )


def test_resume_version_create_uses_safe_fallback_for_unsupported_candidate_facts(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="简历.txt",
        content="候选人：张三\n技能：Python、FastAPI。",
    )
    diagnosis_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="诊断.md",
        content="# 诊断",
        kind="generated_file",
        media_type="text/markdown",
    )
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)

    payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "base_resume_profile_id": "resume_profile_alpha",
            "target_jd_analysis_id": "jd_alpha",
            "title": "保守技术栈版本",
            "content": "# 张三\n\n技能：Python、FastAPI、Docker、React、LLM API、向量检索。",
            "change_summary": ["将技能列表扩展为 Docker/React/LLM API"],
            "keyword_strategy": ["Python", "FastAPI", "向量检索"],
            "risk_notes": ["向量检索经验缺失，应后续补充。"],
            "evidence_refs": ["resume_profile_alpha", "jd_alpha"],
        },
        _context(agent_id="agent_main"),
    )

    artifact_text = session_repository.read_session_artifact_text(
        "sess_career",
        payload["record"]["artifact_id"],
    )
    assert payload["safe_fallback_from_invalid_draft"] is True
    assert "Docker" not in artifact_text
    assert "React" not in artifact_text
    assert "LLM API" not in artifact_text
    assert "向量检索" not in artifact_text
    assert payload["record"]["keyword_strategy"] == ["FastAPI", "Python"]
    assert any("保守事实版本" in item for item in payload["record"]["risk_notes"])


def test_resume_version_create_sanitizes_unverified_contact_values(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="简历.txt",
        content="候选人：张三\n技能：Python、FastAPI。",
    )
    diagnosis_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="诊断.md",
        content="# 诊断",
        kind="generated_file",
        media_type="text/markdown",
    )
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)

    payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "base_resume_profile_id": "resume_profile_alpha",
            "target_jd_analysis_id": "jd_alpha",
            "title": "净化联系方式版本",
            "content": "# 张三\n\nphone: 13800138000\nemail: zhangsan@email.com\n\n技能：Python、FastAPI。",
            "evidence_refs": ["resume_profile_alpha", "jd_alpha"],
        },
        _context(agent_id="agent_main"),
    )

    artifact_text = session_repository.read_session_artifact_text(
        "sess_career",
        payload["record"]["artifact_id"],
    )
    assert payload["sanitized_unverified_contacts"] == ["zhangsan@email.com", "13800138000"]
    assert "zhangsan@email.com" not in artifact_text
    assert "13800138000" not in artifact_text
    assert "技能：Python、FastAPI" in artifact_text
    assert any("未证实的联系方式" in item for item in payload["record"]["risk_notes"])


def test_resume_version_create_uses_safe_fallback_after_previous_validation_failure(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="简历.txt",
        content="候选人：张三\n目标方向：AI 应用开发 / 后端工程师\n技能：Python、FastAPI。",
    )
    diagnosis_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="诊断.md",
        content="# 诊断",
        kind="generated_file",
        media_type="text/markdown",
    )
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)
    context = _context(agent_id="agent_main")
    session_repository.append_agent_event(
        context.session_id,
        context.agent_id,
        EventRecord(
            event_id="evt_previous_resume_version_failure",
            session_id=context.session_id,
            type="tool_result",
            payload={
                "tool_name": "career_resume_version_create",
                "success": False,
                "content": "ResumeVersion validation failed: previous invalid draft.",
                "tool_call_id": "call_previous_resume_version_failure",
            },
            created_at=app_now(),
            agent_id=context.agent_id,
            run_id=context.run_id,
            parent_run_id=context.parent_run_id,
        ),
    )

    payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "base_resume_profile_id": "resume_profile_alpha",
            "target_jd_analysis_id": "jd_alpha",
            "title": "保守定制简历",
            "content": "# 张三\n\nphone: 13800138000\nemail: zhangsan@email.com\n\n技能：Python、FastAPI、LangChain、向量检索。",
            "change_summary": ["加入 LangChain 和向量检索关键词"],
            "keyword_strategy": ["Python", "FastAPI", "LangChain", "向量检索"],
            "evidence_refs": ["resume_profile_alpha", "jd_alpha"],
        },
        context,
    )

    artifact_text = session_repository.read_session_artifact_text(
        context.session_id,
        payload["record"]["artifact_id"],
    )
    assert payload["safe_fallback_from_invalid_draft"] is True
    assert "zhangsan@email.com" not in artifact_text
    assert "13800138000" not in artifact_text
    assert "LangChain" not in artifact_text
    assert "向量检索" not in artifact_text
    assert "Python" in artifact_text
    assert payload["record"]["keyword_strategy"] == ["FastAPI", "Python"]


def test_resume_version_create_uses_safe_fallback_when_retry_has_no_full_content(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="简历.txt",
        content="候选人：张三\n目标方向：AI 应用开发 / 后端工程师\n技能：Python、FastAPI。",
    )
    diagnosis_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="诊断.md",
        content="# 诊断",
        kind="generated_file",
        media_type="text/markdown",
    )
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)
    context = _context(agent_id="agent_main")
    session_repository.append_agent_event(
        context.session_id,
        context.agent_id,
        EventRecord(
            event_id="evt_previous_resume_version_failure_no_content",
            session_id=context.session_id,
            type="tool_result",
            payload={
                "tool_name": "career_resume_version_create",
                "success": False,
                "content": "ResumeVersion validation failed: previous invalid draft.",
                "tool_call_id": "call_previous_resume_version_failure_no_content",
            },
            created_at=app_now(),
            agent_id=context.agent_id,
            run_id=context.run_id,
            parent_run_id=context.parent_run_id,
        ),
    )

    payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "base_resume_profile_id": "resume_profile_alpha",
            "target_jd_analysis_id": "jd_alpha",
            "title": "保守定制简历",
            "evidence_refs": ["resume_profile_alpha", "jd_alpha"],
            "content_omitted": {"chars": 983},
            "content_preview": "# 张三 ...",
        },
        context,
    )

    artifact_text = session_repository.read_session_artifact_text(
        context.session_id,
        payload["record"]["artifact_id"],
    )
    assert payload["safe_fallback_from_invalid_draft"] is True
    assert payload["record_type"] == "resume_version"
    assert "Python" in artifact_text
    assert "FastAPI" in artifact_text


def test_resume_version_create_allows_missing_jd_keywords_in_risk_notes(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="简历.txt",
        content="候选人：张三\n技能：Python、FastAPI。",
    )
    diagnosis_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="诊断.md",
        content="# 诊断",
        kind="generated_file",
        media_type="text/markdown",
    )
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)

    payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "base_resume_profile_id": "resume_profile_alpha",
            "target_jd_analysis_id": "jd_alpha",
            "title": "风险说明版本",
            "content": "# 张三\n\n技能：Python、FastAPI。",
            "keyword_strategy": ["Python", "FastAPI"],
            "risk_notes": ["向量检索经验缺失，应后续补充。"],
            "evidence_refs": ["resume_profile_alpha", "jd_alpha"],
        },
        _context(agent_id="agent_main"),
    )

    assert payload["record_type"] == "resume_version"


def test_resume_version_create_uses_content_as_output_artifact_when_source_artifact_is_supplied(
    tmp_path: Path,
) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="原始简历.txt",
        content="候选人：张三\n技能：Python、FastAPI。",
    )
    diagnosis_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="简历诊断.md",
        content="# 简历诊断",
        kind="generated_file",
        media_type="text/markdown",
    )
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)

    resume_content = "# 张三\n\n技能：Python、FastAPI。\n"
    payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "base_resume_profile_id": "resume_profile_alpha",
            "title": "定制简历",
            "artifact_id": resume_artifact_id,
            "content": resume_content,
            "evidence_refs": ["resume_profile_alpha", resume_artifact_id],
        },
        _context(agent_id="agent_main"),
    )

    version_artifact_id = payload["record"]["artifact_id"]
    assert version_artifact_id != resume_artifact_id
    assert payload["record"]["source_artifact_id"] == version_artifact_id
    assert resume_artifact_id in payload["record"]["evidence_refs"]
    artifact = session_repository.get_session_artifact("sess_career", version_artifact_id)
    assert artifact is not None
    assert artifact.kind == "generated_file"
    assert session_repository.read_session_artifact_text("sess_career", version_artifact_id) == resume_content.strip()


def test_resume_version_create_rejects_input_artifact_as_version_output(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="原始简历.txt",
        content="候选人：张三\n技能：Python、FastAPI。",
    )
    diagnosis_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="简历诊断.md",
        content="# 简历诊断",
        kind="generated_file",
        media_type="text/markdown",
    )
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)

    with pytest.raises(ToolExecutionError, match="generated_file artifact"):
        registry.execute(
            ToolCall(
                name="career_resume_version_create",
                arguments={
                    "base_resume_profile_id": "resume_profile_alpha",
                    "title": "错误复用原始简历",
                    "artifact_id": resume_artifact_id,
                    "evidence_refs": ["resume_profile_alpha", resume_artifact_id],
                },
            ),
            context=_context(agent_id="agent_main"),
        )


def test_main_agent_merges_profile_and_creates_markdown_resume_version(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    evidence_artifact_id = _create_text_artifact(registry, title="简历.txt")
    resume_version_artifact_id = _create_text_artifact(
        registry,
        title="定制简历.md",
        content="# 定制简历",
        kind="generated_file",
        media_type="text/markdown",
    )

    profile_payload = _execute(
        registry,
        "career_profile_merge",
        {
            "updates": {
                "career_goal": "AI 应用开发",
                "target_roles": ["后端开发"],
            },
            "evidence_refs": [evidence_artifact_id],
            "source_artifact_id": evidence_artifact_id,
        },
        _context(agent_id="agent_main"),
    )
    alias_payload = _execute(
        registry,
        "career_profile_merge",
        {
            "updates": {
                "name": "张三",
                "target_direction": "AI 应用开发",
                "target_position": "AI 应用开发工程师",
                "core_skills": ["RAG", "Agent"],
                "job_market_fit": "匹配度高",
            },
            "evidence_refs": [evidence_artifact_id],
            "source_artifact_id": evidence_artifact_id,
        },
        _context(agent_id="agent_main"),
    )
    merged_payload = _execute(
        registry,
        "career_profile_merge",
        {
            "updates": {
                "career_goal": "",
                "target_roles": ["后端开发", "AI 应用开发"],
            },
            "evidence_refs": ["resume_profile_alpha"],
        },
        _context(agent_id="agent_main"),
    )
    string_payload = _execute(
        registry,
        "career_profile_merge",
        {
            "updates": json.dumps({"weaknesses": ["缺少量化成果"]}, ensure_ascii=False),
            "evidence_refs": [evidence_artifact_id],
        },
        _context(agent_id="agent_main"),
    )
    nested_string_payload = _execute(
        registry,
        "career_profile_merge",
        {
            "updates": (
                '{"target_roles": ["AI Agent 后端工程师"], '
                '"skills": ["工具入参归一化"]}, '
                f'"evidence_refs": ["{evidence_artifact_id}", "resume_profile_alpha"]'
            ),
        },
        _context(agent_id="agent_main"),
    )
    typed_evidence_payload = _execute(
        registry,
        "career_profile_merge",
        {
            "updates": {"skills": ["证据归一化"]},
            "evidence_refs": [
                f"artifact:{evidence_artifact_id}",
                "jd_analysis:jd_alpha",
                "job_fit_report:fit_alpha",
            ],
        },
        _context(agent_id="agent_main"),
    )
    version_payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "resume_version_id": "zhangsan_ai_app_dev",
            "base_resume_profile_id": "resume_profile_alpha",
            "target_jd_analysis_id": "jd_alpha",
            "title": "AI 应用开发简历版本",
            "artifact_id": resume_version_artifact_id,
            "evidence_refs": ["resume_profile_alpha", "jd_alpha", resume_version_artifact_id],
            "change_summary": ["强化 RAG 项目"],
        },
        _context(agent_id="agent_main"),
    )
    duplicate_version_payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "resume_version_id": "zhangsan_ai_app_dev_duplicate",
            "base_resume_profile_id": "resume_profile_alpha",
            "target_jd_analysis_id": "jd_alpha",
            "title": "AI 应用开发简历版本重复",
            "artifact_id": resume_version_artifact_id,
            "evidence_refs": ["resume_profile_alpha", "jd_alpha", resume_version_artifact_id],
            "change_summary": ["重复调用应复用原版本"],
        },
        _context(agent_id="agent_main"),
    )
    version_fallback_payload = _execute(
        registry,
        "career_resume_version_get",
        {"resume_version_id": "resume_version_001"},
        _context(agent_id="agent_main"),
    )
    alias_version_artifact_id = _create_text_artifact(
        registry,
        title="AI 应用开发简历版本 alias.md",
        kind="generated_file",
        media_type="text/markdown",
    )
    alias_version_payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "resume_profile_id": "resume_profile_alpha",
            "target_jd_analysis_id": "jd_alpha",
            "title": "AI 应用开发简历版本 alias",
            "artifact_id": alias_version_artifact_id,
            "evidence_refs": ["resume_profile_alpha", "jd_alpha", alias_version_artifact_id],
            "change_summary": ["验证 resume_profile_id alias"],
        },
        _context(agent_id="agent_main"),
    )
    inferred_version_artifact_id = _create_text_artifact(
        registry,
        title="AI 应用开发简历版本 inferred.md",
        kind="generated_file",
        media_type="text/markdown",
    )
    inferred_version_payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "title": "AI 应用开发简历版本 inferred",
            "artifact_id": inferred_version_artifact_id,
            "evidence_refs": ["resume_profile_alpha", "jd_alpha", inferred_version_artifact_id],
            "change_summary": ["验证 evidence_refs 推断 base_resume_profile_id 和 target_jd_analysis_id"],
        },
        _context(agent_id="agent_main"),
    )
    atomic_version_payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "target_jd_analysis_id": "jd_alpha",
            "title": "AI 应用开发简历版本 atomic",
            "content": "# 原子定制简历\n\n突出 RAG 和 Agent 工程。",
            "evidence_refs": ["resume_profile:resume_profile_alpha", "jd_analysis:jd_alpha"],
            "change_summary": ["验证原子创建 artifact 和 ResumeVersion"],
        },
        _context(agent_id="agent_main"),
    )
    atomic_duplicate_payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "target_jd_analysis_id": "jd_alpha",
            "title": "AI 应用开发简历版本 atomic",
            "content": "# 原子定制简历\n\n重复调用。",
            "evidence_refs": ["resume_profile:resume_profile_alpha", "jd_analysis:jd_alpha"],
        },
        _context(agent_id="agent_main"),
    )
    atomic_artifact_payload = _execute(
        registry,
        "session_read_artifact",
        {"artifact_id": atomic_version_payload["record"]["artifact_id"]},
        _context(agent_id="agent_main"),
    )

    assert profile_payload["record"]["career_goal"] == "AI 应用开发"
    assert alias_payload["record"]["career_goal"] == "AI 应用开发"
    assert "AI 应用开发工程师" in alias_payload["record"]["target_roles"]
    assert "RAG" in alias_payload["record"]["skills"]
    assert "Agent" in alias_payload["record"]["skills"]
    assert merged_payload["record"]["career_goal"] == "AI 应用开发"
    assert merged_payload["record"]["target_roles"] == ["后端开发", "AI 应用开发工程师", "AI 应用开发"]
    assert "缺少量化成果" in string_payload["record"]["weaknesses"]
    assert "工具入参归一化" in nested_string_payload["record"]["skills"]
    assert "resume_profile_alpha" in nested_string_payload["record"]["evidence_refs"]
    assert "jd_alpha" in typed_evidence_payload["record"]["evidence_refs"]
    assert "fit_alpha" in typed_evidence_payload["record"]["evidence_refs"]
    assert version_payload["record"]["format"] == "markdown"
    assert version_payload["record"]["resume_version_id"] == "resume_version_zhangsan_ai_app_dev"
    assert version_payload["record"]["source_artifact_id"] == resume_version_artifact_id
    assert duplicate_version_payload["record_id"] == "resume_version_zhangsan_ai_app_dev"
    assert duplicate_version_payload["idempotent_reused"] is True
    assert alias_version_payload["record"]["base_resume_profile_id"] == "resume_profile_alpha"
    assert inferred_version_payload["record"]["base_resume_profile_id"] == "resume_profile_alpha"
    assert inferred_version_payload["record"]["target_jd_analysis_id"] == "jd_alpha"
    assert atomic_version_payload["record"]["base_resume_profile_id"] == "resume_profile_alpha"
    assert atomic_version_payload["record"]["source_artifact_id"].startswith("artifact_")
    assert atomic_version_payload["record"]["source_artifact_id"] in atomic_version_payload["record"]["evidence_refs"]
    assert atomic_duplicate_payload["record_id"] == atomic_version_payload["record_id"]
    assert atomic_duplicate_payload["idempotent_reused"] is True
    assert atomic_artifact_payload["content"].startswith("# 原子定制简历")
    assert version_fallback_payload["record_id"] == "resume_version_zhangsan_ai_app_dev"
    assert version_fallback_payload["requested_record_id"] == "resume_version_001"

    metadata_sanitized_payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "base_resume_profile_id": "resume_profile_alpha",
            "target_jd_analysis_id": "jd_alpha",
            "title": "含禁用词元数据的简历版本",
            "content": "# 定制简历\n\n突出 RAG 项目。",
            "evidence_refs": ["resume_profile_alpha", "jd_alpha"],
            "change_summary": ["省略缺失事实，避免占位表达"],
            "risk_notes": ["TODO：请用户确认缺失事实"],
            "keyword_strategy": ["Python", "占位关键词"],
        },
        _context(agent_id="agent_main"),
    )
    metadata_record = metadata_sanitized_payload["record"]
    metadata_text = "\n".join(
        [
            *metadata_record["change_summary"],
            *metadata_record["risk_notes"],
            *metadata_record["keyword_strategy"],
        ]
    )
    assert "占位" not in metadata_text
    assert "TODO" not in metadata_text
    assert "占位关键词" not in metadata_record["keyword_strategy"]
    assert "Python" in metadata_record["keyword_strategy"]

    with pytest.raises(ToolExecutionError, match="forbidden placeholder"):
        registry.execute(
            ToolCall(
                name="career_resume_version_create",
                arguments={
                    "base_resume_profile_id": "resume_profile_alpha",
                    "target_jd_analysis_id": "jd_alpha",
                    "title": "正文含禁用词的简历版本",
                    "content": "# 定制简历\n\n这里是占位正文。",
                    "evidence_refs": ["resume_profile_alpha", "jd_alpha"],
                    "change_summary": ["调整简历结构"],
                },
            ),
            context=_context(agent_id="agent_main"),
        )

    with pytest.raises(ToolExecutionError, match="Unsupported CareerProfile merge field"):
        registry.execute(
            ToolCall(
                name="career_profile_merge",
                arguments={"updates": {"unknown_field": "value"}, "evidence_refs": ["resume_profile_alpha"]},
            ),
            context=_context(agent_id="agent_main"),
        )
    with pytest.raises(ToolExecutionError, match="not allowed"):
        registry.execute(
            ToolCall(
                name="career_resume_version_create",
                arguments={
                    "base_resume_profile_id": "resume_profile_alpha",
                    "title": "错误权限",
                    "artifact_id": resume_version_artifact_id,
                    "evidence_refs": ["resume_profile_alpha", resume_version_artifact_id],
                },
            ),
            context=_context(agent_id="job_agent"),
        )


def test_main_agent_creates_gets_lists_and_merges_career_application(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_career")
    resume_artifact_id = _create_text_artifact(registry, agent_id="resume_agent", title="张三简历.txt")
    diagnosis_artifact_id = _create_text_artifact(
        registry,
        agent_id="resume_agent",
        title="张三简历诊断.md",
        content="# 简历诊断",
        kind="generated_file",
        media_type="text/markdown",
    )
    _save_resume_profile(registry, resume_artifact_id, diagnosis_artifact_id)
    jd_artifact_id = _create_text_artifact(
        registry,
        agent_id="job_agent",
        title="星河智能 JD.txt",
        content="星河智能招聘 AI Agent 后端工程师，需要 Python、FastAPI、RAG。",
    )
    report_artifact_id = _create_text_artifact(
        registry,
        agent_id="job_agent",
        title="星河智能匹配报告.md",
        content="# 匹配报告",
        kind="generated_file",
        media_type="text/markdown",
    )
    version_artifact_id = _create_text_artifact(
        registry,
        title="星河智能定制简历.md",
        content="# 定制简历",
        kind="generated_file",
        media_type="text/markdown",
    )

    _execute(
        registry,
        "career_jd_analysis_save",
        {
            "jd_analysis_id": "jd_star_agent",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [jd_artifact_id],
            "company": "星河智能",
            "position": "AI Agent 后端工程师",
            "required_skills": ["Python", "FastAPI", "RAG"],
        },
        _context(agent_id="job_agent"),
    )
    _execute(
        registry,
        "career_job_fit_report_save",
        {
            "job_fit_report_id": "fit_star_agent",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [
                "resume_profile_alpha",
                "career_profile_default",
                "jd_star_agent",
                jd_artifact_id,
                report_artifact_id,
            ],
            "jd_analysis_id": "jd_star_agent",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "overall_score": 77,
            "recommendation": "cautious",
            "report_artifact_id": report_artifact_id,
        },
        _context(agent_id="job_agent"),
    )
    version_payload = _execute(
        registry,
        "career_resume_version_create",
        {
            "resume_version_id": "star_agent_resume",
            "base_resume_profile_id": "resume_profile_alpha",
            "target_jd_analysis_id": "jd_star_agent",
            "title": "星河智能定制简历",
            "artifact_id": version_artifact_id,
            "evidence_refs": ["resume_profile_alpha", "jd_star_agent", version_artifact_id],
        },
        _context(agent_id="agent_main"),
    )

    application_payload = _execute(
        registry,
        "career_application_create",
        {
            "job_fit_report_id": "fit_star_agent",
            "resume_version_ids": [version_payload["record_id"]],
            "stage": "ready_to_apply",
            "priority": "high",
            "summary": "候选人与岗位整体匹配，但需要补强 RAG 证据。",
            "next_actions": ["完善 RAG 项目说明"],
            "evidence_refs": ["job_fit_report:fit_star_agent"],
        },
        _context(agent_id="agent_main"),
    )
    duplicate_payload = _execute(
        registry,
        "career_application_create",
        {
            "job_fit_report_id": "fit_star_agent",
            "evidence_refs": ["fit_star_agent"],
        },
        _context(agent_id="agent_main"),
    )
    alias_evidence_payload = _execute(
        registry,
        "career_application_create",
        {
            "job_fit_report_id": "fit_star_agent",
            "evidence_refs": ["job_fit_report_star_agent", "job_fit_report:job_fit_report_star_agent"],
        },
        _context(agent_id="agent_main"),
    )
    loaded_payload = _execute(
        registry,
        "career_application_get",
        {"application_id": application_payload["record_id"]},
        _context(agent_id="agent_main"),
    )
    list_payload = _execute(
        registry,
        "career_application_list",
        {},
        _context(agent_id="agent_main"),
    )
    merged_payload = _execute(
        registry,
        "career_application_merge",
        {
            "application_id": application_payload["record_id"],
            "updates": json.dumps(
                {
                    "stage": "applied",
                    "next_actions": ["等待 HR 反馈"],
                    "risks": ["RAG 项目证据不足"],
                    "notes": "已投递第一版定制简历。",
                },
                ensure_ascii=False,
            ),
            "evidence_refs": [version_payload["record_id"], report_artifact_id],
        },
        _context(agent_id="agent_main"),
    )
    fallback_payload = _execute(
        registry,
        "career_application_get",
        {"application_id": "application_missing"},
        _context(agent_id="agent_main"),
    )

    assert application_payload["record"]["company"] == "星河智能"
    assert application_payload["record"]["position"] == "AI Agent 后端工程师"
    assert application_payload["record"]["source_artifact_id"] == jd_artifact_id
    assert application_payload["record"]["resume_profile_id"] == "resume_profile_alpha"
    assert application_payload["record"]["career_profile_id"] == "career_profile_default"
    assert application_payload["record"]["jd_analysis_id"] == "jd_star_agent"
    assert application_payload["record"]["job_fit_report_id"] == "fit_star_agent"
    assert application_payload["record"]["resume_version_ids"] == [version_payload["record_id"]]
    assert {"fit_star_agent", "jd_star_agent", jd_artifact_id, report_artifact_id}.issubset(
        set(application_payload["record"]["evidence_refs"])
    )
    assert duplicate_payload["record_id"] == application_payload["record_id"]
    assert duplicate_payload["idempotent_reused"] is True
    assert alias_evidence_payload["record_id"] == application_payload["record_id"]
    assert alias_evidence_payload["idempotent_reused"] is True
    assert loaded_payload["record"]["company"] == "星河智能"
    assert [record["application_id"] for record in list_payload["records"]] == [application_payload["record_id"]]
    assert merged_payload["record"]["stage"] == "applied"
    assert "等待 HR 反馈" in merged_payload["record"]["next_actions"]
    assert "RAG 项目证据不足" in merged_payload["record"]["risks"]
    assert fallback_payload["record_id"] == application_payload["record_id"]
    assert fallback_payload["resolved_from_missing_id"] is True

    ignored_readonly_payload = _execute(
        registry,
        "career_application_merge",
        {
            "application_id": application_payload["record_id"],
            "updates": {"company": "不允许覆盖公司"},
            "evidence_refs": ["fit_star_agent"],
        },
        _context(agent_id="agent_main"),
    )
    assert ignored_readonly_payload["record"]["company"] == "星河智能"

    with pytest.raises(ToolExecutionError, match="Unsupported CareerApplication merge field"):
        registry.execute(
            ToolCall(
                name="career_application_merge",
                arguments={
                    "application_id": application_payload["record_id"],
                    "updates": {"unexpected_field": "不支持"},
                    "evidence_refs": ["fit_star_agent"],
                },
            ),
            context=_context(agent_id="agent_main"),
        )
    with pytest.raises(ToolExecutionError, match="not allowed"):
        registry.execute(
            ToolCall(
                name="career_application_create",
                arguments={"job_fit_report_id": "fit_star_agent", "evidence_refs": ["fit_star_agent"]},
            ),
            context=_context(agent_id="job_agent"),
        )


def test_career_application_merge_repairs_unclosed_json_string_updates(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_app_repair")
    jd_artifact_id = _create_text_artifact(
        registry,
        session_id="sess_app_repair",
        title="JD.txt",
        content="AI 应用工程师 JD",
    )
    application = _execute(
        registry,
        "career_application_create",
        {
            "company": "星河智能",
            "position": "AI 应用工程师",
            "source_artifact_id": jd_artifact_id,
            "evidence_refs": [jd_artifact_id],
        },
        _context(session_id="sess_app_repair", agent_id="agent_main"),
    )

    repaired = _execute(
        registry,
        "career_application_merge",
        {
            "application_id": application["record_id"],
            "updates": (
                '{"summary": "已生成定制简历", '
                '"next_actions": ["补充教育背景", "补充项目量化成果"}'
            ),
            "evidence_refs": [jd_artifact_id],
        },
        _context(session_id="sess_app_repair", agent_id="agent_main"),
    )

    assert repaired["record"]["summary"] == "已生成定制简历"
    assert repaired["record"]["next_actions"] == ["补充教育背景", "补充项目量化成果"]

    nested_repaired = _execute(
        registry,
        "career_application_merge",
        {
            "updates": (
                f'"application_id": "{application["record_id"]}", '
                '"updates": {"stage": "interviewing", "notes": "已进入面试准备"}, '
                f'"evidence_refs": ["{jd_artifact_id}"]'
            ),
        },
        _context(session_id="sess_app_repair", agent_id="agent_main"),
    )

    assert nested_repaired["record"]["stage"] == "interviewing"
    assert nested_repaired["record"]["notes"] == "已进入面试准备"


def test_career_application_merge_accepts_resume_stage_aliases(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_app_stage_alias")
    jd_artifact_id = _create_text_artifact(
        registry,
        session_id="sess_app_stage_alias",
        title="JD.txt",
        content="AI 应用工程师 JD",
    )
    application = _execute(
        registry,
        "career_application_create",
        {
            "company": "星河智能",
            "position": "AI 应用工程师",
            "source_artifact_id": jd_artifact_id,
            "stage": "analysis_complete",
            "evidence_refs": [jd_artifact_id],
        },
        _context(session_id="sess_app_stage_alias", agent_id="agent_main"),
    )
    assert application["record"]["stage"] == "draft"

    merged = _execute(
        registry,
        "career_application_merge",
        {
            "application_id": application["record_id"],
            "updates": {"stage": "tailoring", "summary": "定制简历已生成，可进入投递准备。"},
            "evidence_refs": [jd_artifact_id],
        },
        _context(session_id="sess_app_stage_alias", agent_id="agent_main"),
    )

    assert merged["record"]["stage"] == "ready_to_apply"
    assert merged["record"]["summary"] == "定制简历已生成，可进入投递准备。"

    merged_from_resume_version_stage = _execute(
        registry,
        "career_application_merge",
        {
            "application_id": application["record_id"],
            "updates": {"stage": "resume_version_created", "notes": "ResumeVersion 已创建。"},
            "evidence_refs": [jd_artifact_id],
        },
        _context(session_id="sess_app_stage_alias", agent_id="agent_main"),
    )

    assert merged_from_resume_version_stage["record"]["stage"] == "ready_to_apply"

    merged_from_customized_stage = _execute(
        registry,
        "career_application_merge",
        {
            "application_id": application["record_id"],
            "updates": {"stage": "resume_customized", "notes": "定制简历已关联。"},
            "evidence_refs": [jd_artifact_id],
        },
        _context(session_id="sess_app_stage_alias", agent_id="agent_main"),
    )

    assert merged_from_customized_stage["record"]["stage"] == "ready_to_apply"

    merged_from_chinese_stage = _execute(
        registry,
        "career_application_merge",
        {
            "application_id": application["record_id"],
            "updates": {"stage": "定制简历完成", "notes": "自然语言阶段已归一化。"},
            "evidence_refs": [jd_artifact_id],
        },
        _context(session_id="sess_app_stage_alias", agent_id="agent_main"),
    )

    assert merged_from_chinese_stage["record"]["stage"] == "ready_to_apply"
    assert merged_from_chinese_stage["record"]["notes"] == "自然语言阶段已归一化。"

    merged_from_ready_to_apply_phrase = _execute(
        registry,
        "career_application_merge",
        {
            "application_id": application["record_id"],
            "updates": {"stage": "待投递", "notes": "定制简历已就绪，等待投递。"},
            "evidence_refs": [jd_artifact_id],
        },
        _context(session_id="sess_app_stage_alias", agent_id="agent_main"),
    )

    assert merged_from_ready_to_apply_phrase["record"]["stage"] == "ready_to_apply"

    merged_from_applied_phrase = _execute(
        registry,
        "career_application_merge",
        {
            "application_id": application["record_id"],
            "updates": {"stage": "已投递", "notes": "已提交官网申请。"},
            "evidence_refs": [jd_artifact_id],
        },
        _context(session_id="sess_app_stage_alias", agent_id="agent_main"),
    )

    assert merged_from_applied_phrase["record"]["stage"] == "applied"

    merged_from_resume_tailored_stage = _execute(
        registry,
        "career_application_merge",
        {
            "application_id": application["record_id"],
            "updates": {"stage": "resume_tailored", "notes": "英文阶段别名已归一化。"},
            "evidence_refs": [jd_artifact_id],
        },
        _context(session_id="sess_app_stage_alias", agent_id="agent_main"),
    )

    assert merged_from_resume_tailored_stage["record"]["stage"] == "ready_to_apply"

    merged_from_resume_version_stage_alias = _execute(
        registry,
        "career_application_merge",
        {
            "application_id": application["record_id"],
            "updates": {"stage": "resume_version", "notes": "简历版本阶段已归一化。"},
            "evidence_refs": [jd_artifact_id],
        },
        _context(session_id="sess_app_stage_alias", agent_id="agent_main"),
    )

    assert merged_from_resume_version_stage_alias["record"]["stage"] == "ready_to_apply"


def test_career_application_tools_sanitize_placeholder_wording(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_app_placeholder_sanitize")
    jd_artifact_id = _create_text_artifact(
        registry,
        session_id="sess_app_placeholder_sanitize",
        title="JD.txt",
        content="AI 应用工程师 JD",
    )

    application = _execute(
        registry,
        "career_application_create",
        {
            "company": "未知公司",
            "position": "未知职位",
            "source_artifact_id": jd_artifact_id,
            "summary": "基于 JD 创建的求职项目，待补充公司和职位信息。",
            "next_actions": ["待补充公司信息", "TODO 准备面试话术"],
            "risks": ["TBD 风险"],
            "notes": "占位说明",
            "evidence_refs": [jd_artifact_id, "artifact_missing_fake"],
        },
        _context(session_id="sess_app_placeholder_sanitize", agent_id="agent_main"),
    )

    record = application["record"]
    joined = "\n".join([record["summary"], record["notes"], *record["next_actions"], *record["risks"]])
    assert "待补" not in joined
    assert "TODO" not in joined
    assert "TBD" not in joined
    assert "占位" not in joined
    assert "artifact_missing_fake" not in record["evidence_refs"]

    merged = _execute(
        registry,
        "career_application_merge",
        {
            "application_id": application["record_id"],
            "updates": {"notes": "补充一次备注"},
            "evidence_refs": [jd_artifact_id, "artifact_missing_fake"],
        },
        _context(session_id="sess_app_placeholder_sanitize", agent_id="agent_main"),
    )

    assert "artifact_missing_fake" not in merged["record"]["evidence_refs"]
