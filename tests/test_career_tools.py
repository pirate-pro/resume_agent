"""Tests for career product tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from app.career.store import CareerProductStore
from app.core.errors import ToolExecutionError
from app.domain.models import RunContext, ToolCall
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
            "evidence_refs": [jd_artifact_id],
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
    assert fit_payload["record"]["source_artifact_id"] == jd_artifact_id
    assert fit_payload["record"]["report_artifact_id"] == report_artifact_id
    assert fit_payload["record"]["overall_score"] == 82
    assert fit_payload["record"]["score_breakdown"] == {"skills": 80, "projects": 85, "growth": 90}
    assert duplicate_fit_payload["record_id"] == "fit_alpha"
    assert duplicate_fit_payload["idempotent_reused"] is True

    with pytest.raises(ToolExecutionError):
        registry.execute(
            ToolCall(
                name="career_job_fit_report_save",
                arguments={
                    "job_fit_report_id": "fit_alpha",
                    "source_artifact_id": jd_artifact_id,
                    "evidence_refs": ["resume_profile_alpha", "career_profile_default", "jd_beta", jd_artifact_id],
                    "jd_analysis_id": "jd_beta",
                    "resume_profile_id": "resume_profile_alpha",
                    "career_profile_id": "career_profile_default",
                    "report_artifact_id": report_artifact_id,
                },
            ),
            context=_context(agent_id="job_agent"),
        )
    with pytest.raises(ToolExecutionError, match="not allowed"):
        registry.execute(
            ToolCall(
                name="career_profile_merge",
                arguments={"updates": {"career_goal": "AI"}, "evidence_refs": ["resume_profile_alpha"]},
            ),
            context=_context(agent_id="job_agent"),
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

    with pytest.raises(ToolExecutionError, match="forbidden placeholder"):
        registry.execute(
            ToolCall(
                name="career_resume_version_create",
                arguments={
                    "base_resume_profile_id": "resume_profile_alpha",
                    "target_jd_analysis_id": "jd_alpha",
                    "title": "含禁用词的简历版本",
                    "content": "# 定制简历\n\n突出 RAG 项目。",
                    "evidence_refs": ["resume_profile_alpha", "jd_alpha"],
                    "change_summary": ["省略缺失事实，避免占位表达"],
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
