"""Tests for learning plan tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from app.core.errors import ToolExecutionError
from app.domain.models import RunContext, ToolCall
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.learning.store import LearningStore
from app.memory.models import MemoryScope
from app.runtime.agent_capability import AgentCapability, AgentCapabilityRegistry
from app.tools.builtins import (
    LearningCheckinCreateTool,
    LearningPlanCreateTool,
    LearningPlanGetTool,
    LearningPlanListTool,
    LearningTaskCreateTool,
    LearningTaskGetTool,
    LearningTaskListTool,
    LearningTaskUpdateStateTool,
    LearningWeaknessCreateTool,
    LearningWeaknessUpdateTool,
    SessionCreateTextArtifactTool,
)
from app.tools.registry import ToolRegistry

__all__ = []


def _context(session_id: str = "sess_learning", agent_id: str = "agent_main") -> RunContext:
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
                    "learning_plan_create",
                    "learning_plan_get",
                    "learning_plan_list",
                    "learning_task_create",
                    "learning_task_get",
                    "learning_task_list",
                    "learning_task_update_state",
                    "learning_checkin_create",
                    "learning_weakness_create",
                    "learning_weakness_update",
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


def _registry(tmp_path: Path) -> tuple[ToolRegistry, JsonlSessionRepository, LearningStore]:
    session_repository = JsonlSessionRepository(data_dir=tmp_path / "sessions")
    learning_store = LearningStore(root_dir=tmp_path / "learning")
    registry = ToolRegistry(capability_registry=_capability_registry())
    registry.register(SessionCreateTextArtifactTool(session_repository=session_repository))
    registry.register(LearningPlanCreateTool(learning_store=learning_store, session_repository=session_repository))
    registry.register(LearningPlanGetTool(learning_store=learning_store))
    registry.register(LearningPlanListTool(learning_store=learning_store))
    registry.register(LearningTaskCreateTool(learning_store=learning_store, session_repository=session_repository))
    registry.register(LearningTaskGetTool(learning_store=learning_store))
    registry.register(LearningTaskListTool(learning_store=learning_store))
    registry.register(LearningTaskUpdateStateTool(learning_store=learning_store))
    registry.register(LearningCheckinCreateTool(learning_store=learning_store, session_repository=session_repository))
    registry.register(LearningWeaknessCreateTool(learning_store=learning_store, session_repository=session_repository))
    registry.register(LearningWeaknessUpdateTool(learning_store=learning_store, session_repository=session_repository))
    return registry, session_repository, learning_store


def _execute(registry: ToolRegistry, name: str, arguments: dict[str, Any], context: RunContext) -> dict[str, Any]:
    result = registry.execute(ToolCall(name=name, arguments=arguments), context=context)
    assert result.success is True
    return cast(dict[str, Any], json.loads(result.content))


def _create_text_artifact(registry: ToolRegistry, *, session_id: str = "sess_learning") -> str:
    payload = _execute(
        registry,
        "session_create_text_artifact",
        {
            "title": "匹配报告.md",
            "content": "# 匹配报告\n\nRAG 项目证据不足，需要学习计划跟进。",
            "kind": "generated_file",
            "media_type": "text/markdown",
        },
        _context(session_id=session_id),
    )
    return str(payload["artifact_id"])


def test_learning_task_create_normalizes_typed_evidence_refs(tmp_path: Path) -> None:
    registry, session_repository, _ = _registry(tmp_path)
    session_repository.create_session("sess_learning")

    payload = _execute(
        registry,
        "learning_task_create",
        {
            "title": "补强 RAG 评估",
            "description": "根据面试复盘创建学习任务。",
            "evidence_refs": [
                "career_application:application_alpha",
                "job_fit_report:fit_alpha",
                "note:note_review_alpha",
            ],
            "priority": "high",
        },
        _context(),
    )

    assert payload["record"]["evidence_refs"] == [
        "application_alpha",
        "fit_alpha",
        "note_review_alpha",
    ]


def test_main_agent_creates_reads_lists_checkins_and_updates_learning_records(tmp_path: Path) -> None:
    registry, session_repository, learning_store = _registry(tmp_path)
    session_repository.create_session("sess_learning")
    source_artifact_id = _create_text_artifact(registry)

    plan_payload = _execute(
        registry,
        "learning_plan_create",
        {
            "learning_plan_id": "stargazer_backend",
            "source_artifact_id": source_artifact_id,
            "evidence_refs": ["application_alpha", "fit_stargazer_backend", source_artifact_id],
            "title": "星河智能面试准备计划",
            "description": "围绕 RAG 和异步任务补短板。",
            "plan_type": "interview_prep",
            "target_application_id": "application_alpha",
            "target_role": "AI Agent 后端工程师",
            "target_company": "星河智能",
            "priority": "high",
            "goals": ["讲清楚 RAG 评估", "准备异步任务架构"],
            "focus_skill_tags": ["RAG", "FastAPI"],
            "progress_summary": "未开始",
        },
        _context(),
    )
    task_payload = _execute(
        registry,
        "learning_task_create",
        {
            "learning_task_id": "rag_eval",
            "source_artifact_id": source_artifact_id,
            "evidence_refs": [plan_payload["record_id"], "resource_rag_eval"],
            "title": "准备 RAG 评估回答",
            "learning_plan_id": plan_payload["record_id"],
            "task_type": "write_answer",
            "priority": "high",
            "skill_tags": ["RAG"],
            "estimated_minutes": 45,
            "resource_refs": ["resource_rag_eval", "skill_req_rag_engineering", "rag_chunking_strategy_resource_001"],
            "question_refs": ["question_rag_chunk_strategy"],
            "success_criteria": ["覆盖指标", "说明失败恢复"],
        },
        _context(),
    )
    weakness_payload = _execute(
        registry,
        "learning_weakness_create",
        {
            "weakness_id": "rag_depth",
            "source_artifact_id": source_artifact_id,
            "evidence_refs": ["fit_stargazer_backend", plan_payload["record_id"]],
            "title": "RAG 深度不足",
            "weakness_type": "skill_gap",
            "severity": "high",
            "skill_tags": ["RAG"],
            "target_application_ids": ["application_alpha"],
            "source_report_ids": ["fit_stargazer_backend", source_artifact_id],
            "related_task_ids": [task_payload["record_id"]],
        },
        _context(),
    )
    checkin_payload = _execute(
        registry,
        "learning_checkin_create",
        {
            "evidence_refs": [task_payload["record_id"]],
            "learning_plan_id": plan_payload["record_id"],
            "learning_task_id": task_payload["record_id"],
            "minutes_spent": 30,
            "progress_state": "in_progress",
            "summary": "完成了 RAG 指标提纲。",
            "blockers": ["缺少生产案例"],
            "confidence": "medium",
            "next_action": "补一个线上评估例子。",
        },
        _context(),
    )
    completed_payload = _execute(
        registry,
        "learning_task_update_state",
        {"learning_task_id": task_payload["record_id"], "state": "done"},
        _context(),
    )
    updated_weakness_payload = _execute(
        registry,
        "learning_weakness_update",
        {
            "weakness_id": weakness_payload["record_id"],
            "updates": json.dumps(
                {
                    "state": "improving",
                    "resolution_summary": "已完成第一版 RAG 评估回答。",
                    "related_task_ids": [task_payload["record_id"]],
                },
                ensure_ascii=False,
            ),
        },
        _context(),
    )
    plan_list_payload = _execute(
        registry,
        "learning_plan_list",
        {"target_application_id": "application_alpha"},
        _context(),
    )
    task_list_payload = _execute(
        registry,
        "learning_task_list",
        {"learning_plan_id": plan_payload["record_id"], "state": "done"},
        _context(),
    )
    loaded_plan_payload = _execute(
        registry,
        "learning_plan_get",
        {"learning_plan_id": plan_payload["record_id"]},
        _context(),
    )

    assert plan_payload["record_id"] == "learning_plan_stargazer_backend"
    assert plan_payload["source_session_id"] == "sess_learning"
    assert plan_payload["source_artifact_id"] == source_artifact_id
    assert task_payload["record_id"] == "learning_task_rag_eval"
    assert task_payload["record"]["learning_plan_id"] == plan_payload["record_id"]
    assert task_payload["record"]["resource_refs"] == ["resource_rag_eval", "skill_req_rag_engineering"]
    assert weakness_payload["record_id"] == "weakness_rag_depth"
    assert checkin_payload["record_type"] == "checkin"
    assert completed_payload["record"]["state"] == "done"
    assert completed_payload["record"]["completed_at"] is not None
    assert updated_weakness_payload["record"]["state"] == "improving"
    assert [record["learning_plan_id"] for record in plan_list_payload["records"]] == [plan_payload["record_id"]]
    assert [record["learning_task_id"] for record in task_list_payload["records"]] == [task_payload["record_id"]]
    assert loaded_plan_payload["record"]["title"] == "星河智能面试准备计划"
    assert learning_store.get_progress_checkin(checkin_payload["record_id"]) is not None
    assert not list((tmp_path / "learning").rglob("*.md"))


def test_learning_tools_reject_paths_store_owned_fields_and_unallowed_agents(tmp_path: Path) -> None:
    registry, session_repository, _learning_store = _registry(tmp_path)
    session_repository.create_session("sess_learning")

    with pytest.raises(ToolExecutionError, match="Path arguments are not allowed"):
        registry.execute(
            ToolCall(
                name="learning_plan_create",
                arguments={"title": "错误计划", "evidence_refs": ["application_alpha"], "path": "plan.json"},
            ),
            context=_context(),
        )
    with pytest.raises(ToolExecutionError, match="Store-owned fields are not accepted"):
        registry.execute(
            ToolCall(
                name="learning_plan_create",
                arguments={
                    "title": "错误计划",
                    "evidence_refs": ["application_alpha"],
                    "source_session_id": "sess_other",
                },
            ),
            context=_context(),
        )
    with pytest.raises(ToolExecutionError, match="not allowed"):
        registry.execute(
            ToolCall(
                name="learning_plan_create",
                arguments={"title": "子 agent 不允许写", "evidence_refs": ["application_alpha"]},
            ),
            context=_context(agent_id="resume_agent"),
        )
    with pytest.raises(ToolExecutionError, match="Unsupported updates field"):
        registry.execute(
            ToolCall(
                name="learning_weakness_update",
                arguments={"weakness_id": "weakness_missing", "updates": {"created_at": "2026-01-01T00:00:00Z"}},
            ),
            context=_context(),
        )


def test_learning_tools_reject_artifacts_outside_current_session(tmp_path: Path) -> None:
    registry, session_repository, _learning_store = _registry(tmp_path)
    session_repository.create_session("sess_learning")
    session_repository.create_session("sess_other")
    other_artifact_id = _create_text_artifact(registry, session_id="sess_other")

    with pytest.raises(ToolExecutionError, match="current session artifact"):
        registry.execute(
            ToolCall(
                name="learning_plan_create",
                arguments={
                    "source_artifact_id": other_artifact_id,
                    "evidence_refs": ["application_alpha", other_artifact_id],
                    "title": "错误来源计划",
                },
            ),
            context=_context(),
        )


def test_learning_tools_return_not_found_payloads(tmp_path: Path) -> None:
    registry, session_repository, _learning_store = _registry(tmp_path)
    session_repository.create_session("sess_learning")

    plan_payload = _execute(registry, "learning_plan_get", {"learning_plan_id": "learning_plan_missing"}, _context())
    task_payload = _execute(registry, "learning_task_get", {"learning_task_id": "learning_task_missing"}, _context())

    assert plan_payload["found"] is False
    assert task_payload["found"] is False
