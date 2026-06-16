"""Tests for note asset tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from app.core.errors import ToolExecutionError
from app.domain.models import RunContext, ToolCall
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.memory.models import MemoryScope
from app.notes.store import NoteStore
from app.runtime.agent_capability import AgentCapability, AgentCapabilityRegistry
from app.tools.builtins import (
    NoteAppendTool,
    NoteArchiveTool,
    NoteCollectionArchiveTool,
    NoteCollectionCreateTool,
    NoteCollectionGetTool,
    NoteCollectionListTool,
    NoteCollectionUpdateTool,
    NoteCreateTool,
    NoteGetTool,
    NoteListTool,
    NoteUpdateTool,
    SessionCreateTextArtifactTool,
)
from app.tools.registry import ToolRegistry

__all__ = []


def _context(session_id: str = "sess_notes", agent_id: str = "agent_main") -> RunContext:
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
                    "note_create",
                    "note_get",
                    "note_list",
                    "note_update",
                    "note_append",
                    "note_archive",
                    "note_collection_create",
                    "note_collection_get",
                    "note_collection_list",
                    "note_collection_update",
                    "note_collection_archive",
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
                allowed_tools=["session_create_text_artifact"],
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
    note_store = NoteStore(root_dir=tmp_path / "notes")
    registry = ToolRegistry(capability_registry=_capability_registry())
    registry.register(SessionCreateTextArtifactTool(session_repository=session_repository))
    registry.register(NoteCreateTool(note_store=note_store, session_repository=session_repository))
    registry.register(NoteGetTool(note_store=note_store))
    registry.register(NoteListTool(note_store=note_store))
    registry.register(NoteUpdateTool(note_store=note_store, session_repository=session_repository))
    registry.register(NoteAppendTool(note_store=note_store))
    registry.register(NoteArchiveTool(note_store=note_store))
    registry.register(NoteCollectionCreateTool(note_store=note_store))
    registry.register(NoteCollectionGetTool(note_store=note_store))
    registry.register(NoteCollectionListTool(note_store=note_store))
    registry.register(NoteCollectionUpdateTool(note_store=note_store))
    registry.register(NoteCollectionArchiveTool(note_store=note_store))
    return registry, session_repository


def _execute(registry: ToolRegistry, name: str, arguments: dict[str, Any], context: RunContext) -> dict[str, Any]:
    result = registry.execute(ToolCall(name=name, arguments=arguments), context=context)
    assert result.success is True
    return cast(dict[str, Any], json.loads(result.content))


def _create_text_artifact(
    registry: ToolRegistry,
    *,
    session_id: str = "sess_notes",
    agent_id: str = "agent_main",
    title: str = "资料.md",
    content: str = "# 投递前检查\n\n需要补 RAG 项目证据。",
) -> str:
    payload = _execute(
        registry,
        "session_create_text_artifact",
        {
            "title": title,
            "content": content,
            "kind": "generated_file",
            "media_type": "text/markdown",
        },
        _context(session_id, agent_id),
    )
    return str(payload["artifact_id"])


def test_main_agent_creates_gets_lists_updates_appends_and_archives_note(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_notes")
    report_artifact_id = _create_text_artifact(registry)

    collection_payload = _execute(
        registry,
        "note_collection_create",
        {
            "collection_id": "interview",
            "name": "面试复盘",
            "description": "目标岗位面试复盘",
            "kind": "interview",
            "tags": "RAG",
        },
        _context(),
    )
    note_payload = _execute(
        registry,
        "note_create",
        {
            "note_id": "star_agent_review",
            "source_artifact_id": report_artifact_id,
            "evidence_refs": ["application_alpha", "fit_alpha"],
            "title": "星河智能投递前检查复盘",
            "body_markdown": "## 结论\n先补 RAG 项目证据，再投递。",
            "note_type": "resource",
            "collection_id": collection_payload["record_id"],
            "tags": ["投递前检查", "RAG"],
            "related_application_id": "application_alpha",
            "summary": "投递前需要补齐 RAG 项目证据。",
        },
        _context(),
    )
    duplicate_payload = _execute(
        registry,
        "note_create",
        {
            "note_id": "note_star_agent_review",
            "title": "不应覆盖",
            "body_markdown": "不应覆盖",
        },
        _context(),
    )
    loaded_payload = _execute(registry, "note_get", {"note_id": note_payload["record_id"]}, _context())
    list_payload = _execute(
        registry,
        "note_list",
        {"collection_id": collection_payload["record_id"], "related_application_id": "application_alpha"},
        _context(),
    )
    updated_payload = _execute(
        registry,
        "note_update",
        {
            "note_id": note_payload["record_id"],
            "updates": json.dumps(
                {
                    "title": "更新后的投递复盘",
                    "summary": "准备 RAG 深挖问题。",
                    "note_type": "learning",
                    "tags": ["投递前检查", "面试准备"],
                },
                ensure_ascii=False,
            ),
        },
        _context(),
    )
    appended_payload = _execute(
        registry,
        "note_append",
        {
            "note_id": note_payload["record_id"],
            "body_markdown": "## 面试后补充\n面试官追问了向量检索评估。",
            "source_refs": [
                {
                    "source_type": "manual",
                    "source_session_id": "sess_notes",
                    "title": "面试后手动补充",
                }
            ],
            "evidence_refs": ["sess_notes"],
        },
        _context(),
    )
    archived_payload = _execute(registry, "note_archive", {"note_id": note_payload["record_id"]}, _context())
    archived_list_payload = _execute(registry, "note_list", {"include_archived": True}, _context())

    assert collection_payload["record_id"] == "collection_interview"
    assert note_payload["record_id"] == "note_star_agent_review"
    assert note_payload["source_session_id"] == "sess_notes"
    assert note_payload["origin"] == "agent"
    assert note_payload["record"]["origin"] == "agent"
    assert note_payload["record"]["source_artifact_id"] == report_artifact_id
    assert note_payload["record"]["note_type"] == "resource"
    assert report_artifact_id in note_payload["record"]["evidence_refs"]
    assert note_payload["record"]["source_refs"][0]["source_type"] == "artifact"
    assert duplicate_payload["record_id"] == "note_star_agent_review"
    assert duplicate_payload["idempotent_reused"] is True
    assert loaded_payload["record"]["title"] == "星河智能投递前检查复盘"
    assert [record["note_id"] for record in list_payload["records"]] == ["note_star_agent_review"]
    assert updated_payload["record"]["title"] == "更新后的投递复盘"
    assert updated_payload["record"]["note_type"] == "learning"
    assert "面试后补充" in appended_payload["record"]["body_markdown"]
    assert appended_payload["record"]["source_refs"][-1]["source_type"] == "manual"
    assert archived_payload["record"]["status"] == "archived"
    assert [record["note_id"] for record in archived_list_payload["records"]] == ["note_star_agent_review"]
    assert not list((tmp_path / "notes").rglob("*.md"))


def test_note_create_canonicalizes_object_evidence_refs(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_notes")

    note_payload = _execute(
        registry,
        "note_create",
        {
            "title": "面试准备",
            "body_markdown": "## 准备\n复习 RAG chunk 策略。",
            "evidence_refs": [
                {"source_type": "career_application", "source_id": "application_alpha"},
                {"source_type": "job_fit_report", "source_id": "fit_alpha"},
                "resume_profile_alpha",
                {"record_id": "artifact_alpha"},
                {"source_type": "job_fit_report", "source_id": "fit_alpha"},
            ],
            "source_refs": [
                {
                    "source_type": "career_application",
                    "source_id": "application_alpha",
                    "title": "AI 应用开发工程师",
                }
            ],
        },
        _context(),
    )

    assert note_payload["record"]["evidence_refs"] == [
        "application_alpha",
        "fit_alpha",
        "resume_profile_alpha",
        "artifact_alpha",
    ]
    assert note_payload["record"]["source_refs"][0]["source_id"] == "application_alpha"


def test_note_create_canonicalizes_career_reference_aliases(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_notes")

    note_payload = _execute(
        registry,
        "note_create",
        {
            "title": "面试准备",
            "body_markdown": "## 准备\n复习 RAG chunk 策略。",
            "evidence_refs": [
                "application:application_alpha",
                "resume_profile:resume_profile_alpha",
                "jd_analysis:jd_alpha",
                "job_fit_report:fit_alpha",
                "career_profile:career_profile_default",
                "resume_version:resume_version_alpha",
            ],
            "source_refs": [
                {"source_type": "application", "source_id": "application_alpha"},
                {"source_type": "jd", "source_id": "jd_alpha"},
                {"source_type": "fit", "source_id": "fit_alpha"},
                {"source_type": "career_resume_profile", "source_id": "resume_profile_alpha"},
                {"source_type": "resume_version", "source_id": "resume_version:resume_version_alpha"},
            ],
        },
        _context(),
    )

    assert note_payload["record"]["evidence_refs"] == [
        "application_alpha",
        "resume_profile_alpha",
        "jd_alpha",
        "fit_alpha",
        "career_profile_default",
        "resume_version_alpha",
    ]
    assert [item["source_type"] for item in note_payload["record"]["source_refs"]] == [
        "career_application",
        "jd_analysis",
        "job_fit_report",
        "resume_profile",
        "resume_version",
    ]
    assert note_payload["record"]["source_refs"][-1]["source_id"] == "resume_version_alpha"


def test_note_create_treats_note_source_ref_as_manual_context(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_notes")

    note_payload = _execute(
        registry,
        "note_create",
        {
            "title": "面试复盘",
            "body_markdown": "## 复盘\n补齐召回评估指标。",
            "source_refs": [
                {
                    "source_type": "note",
                    "source_id": "note_seed_alpha",
                    "title": "历史面试准备记录",
                }
            ],
        },
        _context(),
    )

    source_ref = note_payload["record"]["source_refs"][0]
    assert source_ref["source_type"] == "manual"
    assert source_ref["source_id"] is None
    assert source_ref["title"] == "历史面试准备记录"


def test_note_collection_tools_update_and_archive(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_notes")

    created_payload = _execute(
        registry,
        "note_collection_create",
        {"collection_id": "learning", "name": "学习记录", "kind": "learning"},
        _context(),
    )
    loaded_payload = _execute(
        registry,
        "note_collection_get",
        {"collection_id": created_payload["record_id"]},
        _context(),
    )
    updated_payload = _execute(
        registry,
        "note_collection_update",
        {
            "collection_id": created_payload["record_id"],
            "updates": {"name": "学习与面试记录", "kind": "career_project", "tags": ["学习", "面试"]},
        },
        _context(),
    )
    list_payload = _execute(registry, "note_collection_list", {}, _context())
    archived_payload = _execute(
        registry,
        "note_collection_archive",
        {"collection_id": created_payload["record_id"]},
        _context(),
    )

    assert loaded_payload["record"]["name"] == "学习记录"
    assert updated_payload["record"]["kind"] == "career_project"
    assert [record["collection_id"] for record in list_payload["records"]] == ["collection_learning"]
    assert archived_payload["record"]["status"] == "archived"


def test_note_tool_rejects_paths_store_owned_fields_and_unallowed_agents(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_notes")
    artifact_id = _create_text_artifact(registry)

    with pytest.raises(ToolExecutionError, match="Path arguments are not allowed"):
        registry.execute(
            ToolCall(
                name="note_create",
                arguments={
                    "title": "错误笔记",
                    "body_markdown": "正文",
                    "path": "note.md",
                },
            ),
            context=_context(),
        )
    with pytest.raises(ToolExecutionError, match="Store-owned fields are not accepted"):
        registry.execute(
            ToolCall(
                name="note_create",
                arguments={
                    "title": "错误笔记",
                    "body_markdown": "正文",
                    "source_session_id": "sess_other",
                },
            ),
            context=_context(),
        )
    with pytest.raises(ToolExecutionError, match="Unsupported updates field"):
        registry.execute(
            ToolCall(
                name="note_update",
                arguments={"note_id": "note_missing", "updates": {"created_at": "2026-01-01T00:00:00Z"}},
            ),
            context=_context(),
        )
    with pytest.raises(ToolExecutionError, match="not allowed"):
        registry.execute(
            ToolCall(
                name="note_create",
                arguments={"title": "子 agent 不允许写", "body_markdown": "正文"},
            ),
            context=_context(agent_id="resume_agent"),
        )

    valid_payload = _execute(
        registry,
        "note_create",
        {
            "source_artifact_id": artifact_id,
            "title": "合法笔记",
            "body_markdown": "正文",
        },
        _context(),
    )
    assert valid_payload["record"]["source_session_id"] == "sess_notes"


def test_note_tool_rejects_artifacts_outside_current_session(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_notes")
    session_repository.create_session("sess_other")
    other_artifact_id = _create_text_artifact(registry, session_id="sess_other", title="其他会话报告.md")

    with pytest.raises(ToolExecutionError, match="current session artifact"):
        registry.execute(
            ToolCall(
                name="note_create",
                arguments={
                    "source_artifact_id": other_artifact_id,
                    "title": "错误来源笔记",
                    "body_markdown": "正文",
                },
            ),
            context=_context(),
        )


def test_note_tool_returns_not_found_payloads(tmp_path: Path) -> None:
    registry, session_repository = _registry(tmp_path)
    session_repository.create_session("sess_notes")

    note_payload = _execute(registry, "note_get", {"note_id": "note_missing"}, _context())
    archive_payload = _execute(registry, "note_archive", {"note_id": "note_missing"}, _context())
    collection_payload = _execute(
        registry,
        "note_collection_get",
        {"collection_id": "collection_missing"},
        _context(),
    )

    assert note_payload["found"] is False
    assert archive_payload["found"] is False
    assert collection_payload["found"] is False
