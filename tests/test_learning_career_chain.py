"""Low-cost end-to-end verification from career project to learning plan."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.career.models import (
    CareerApplication,
    CareerProfile,
    CareerRecordStatus,
    JDAnalysis,
    JobFitReport,
    ResumeProfile,
)
from app.career.store import CareerProductStore
from app.core.time import APP_TIMEZONE
from app.domain.models import AgentRunInput, RunContext, ToolCall
from app.domain.protocols import ChatModelClient, ModelResponse, StreamChunk
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.learning.store import LearningStore
from app.memory.file_store import FileMemoryStore
from app.runtime.agent_capability import load_agent_capability_registry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.event_recorder import EventRecorder
from app.runtime.memory_manager import MemoryManager
from app.runtime.mid_term_flusher import MidTermFlusher
from app.runtime.session_manager import SessionManager
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.tools.builtins import (
    CareerApplicationGetTool,
    CareerJobFitReportGetTool,
    LearningCheckinCreateTool,
    LearningPlanCreateTool,
    LearningTaskCreateTool,
    LearningTaskUpdateStateTool,
    LearningWeaknessCreateTool,
    LearningWeaknessUpdateTool,
)
from app.tools.registry import ToolRegistry

__all__ = []


@dataclass(slots=True)
class LearningCareerChainBundle:
    runtime: AgentRuntime
    session_repository: JsonlSessionRepository
    career_store: CareerProductStore
    learning_store: LearningStore
    memory_manager: MemoryManager


class CareerToLearningPlanModel:
    """Drive the M10-4 chain with deterministic tool calls."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = system_prompt
        tool_names = _tool_names(tools)

        if not _assistant_called(messages, "career_application_get"):
            assert "career_application_get" in tool_names
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="career_application_get",
                        arguments={"application_id": "application_stargazer_backend"},
                    )
                ],
            )

        if not _assistant_called(messages, "career_job_fit_report_get"):
            assert "career_job_fit_report_get" in tool_names
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="career_job_fit_report_get",
                        arguments={"job_fit_report_id": "fit_stargazer_backend"},
                    ),
                ],
            )

        if not _assistant_called(messages, "learning_plan_create"):
            assert "learning_plan_create" in tool_names
            assert "learning_task_create" in tool_names
            assert "learning_weakness_create" in tool_names
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="learning_plan_create",
                        arguments={
                            "learning_plan_id": "stargazer_backend_prep",
                            "evidence_refs": [
                                "application_stargazer_backend",
                                "fit_stargazer_backend",
                                "resume_profile_stargazer",
                                "career_profile_default",
                                "jd_stargazer_backend",
                                "artifact_fit_report_stargazer",
                            ],
                            "title": "星河智能 AI Agent 后端面试准备计划",
                            "description": "基于求职项目和匹配报告，把 RAG、Agent 架构和异步任务短板拆成可执行任务。",
                            "plan_type": "interview_prep",
                            "target_application_id": "application_stargazer_backend",
                            "target_role": "AI Agent 后端工程师",
                            "target_company": "星河智能",
                            "priority": "high",
                            "goals": ["补齐 RAG 评估表达", "准备多 Agent 架构追问", "梳理异步任务队列经验"],
                            "focus_skill_tags": ["RAG", "Agent Runtime", "异步任务"],
                            "progress_summary": "已从匹配报告拆解出面试准备任务。",
                        },
                    ),
                    ToolCall(
                        name="learning_task_create",
                        arguments={
                            "learning_task_id": "rag_eval",
                            "evidence_refs": ["learning_plan_stargazer_backend_prep", "fit_stargazer_backend"],
                            "title": "准备 RAG 检索评估回答",
                            "learning_plan_id": "learning_plan_stargazer_backend_prep",
                            "task_type": "write_answer",
                            "priority": "high",
                            "skill_tags": ["RAG"],
                            "estimated_minutes": 45,
                            "resource_refs": ["resource_rag_eval", "skill_req_rag_engineering"],
                            "question_refs": ["question_rag_chunk_strategy"],
                            "success_criteria": ["覆盖 chunk 策略", "说明召回评估", "给出失败恢复例子"],
                        },
                    ),
                    ToolCall(
                        name="learning_task_create",
                        arguments={
                            "learning_task_id": "agent_architecture",
                            "evidence_refs": ["learning_plan_stargazer_backend_prep", "fit_stargazer_backend"],
                            "title": "梳理 multi-agent 编排架构",
                            "learning_plan_id": "learning_plan_stargazer_backend_prep",
                            "task_type": "write_answer",
                            "priority": "high",
                            "skill_tags": ["Agent Runtime"],
                            "estimated_minutes": 40,
                            "resource_refs": ["resource_agent_runtime_notes"],
                            "success_criteria": ["说明主 agent 和 child-agent 权限边界", "解释 artifact-first"],
                        },
                    ),
                    ToolCall(
                        name="learning_task_create",
                        arguments={
                            "learning_task_id": "async_queue",
                            "evidence_refs": ["learning_plan_stargazer_backend_prep", "fit_stargazer_backend"],
                            "title": "准备异步任务队列案例",
                            "learning_plan_id": "learning_plan_stargazer_backend_prep",
                            "task_type": "write_answer",
                            "priority": "medium",
                            "skill_tags": ["Celery", "Redis", "异步任务"],
                            "estimated_minutes": 35,
                            "resource_refs": ["resource_async_task_queue"],
                            "success_criteria": ["说明任务状态", "说明失败重试", "说明审计日志"],
                        },
                    ),
                    ToolCall(
                        name="learning_task_create",
                        arguments={
                            "learning_task_id": "mock_interview",
                            "evidence_refs": ["learning_plan_stargazer_backend_prep", "fit_stargazer_backend"],
                            "title": "做一次 30 分钟模拟面试",
                            "learning_plan_id": "learning_plan_stargazer_backend_prep",
                            "task_type": "mock_interview",
                            "priority": "medium",
                            "skill_tags": ["表达", "项目深挖"],
                            "estimated_minutes": 30,
                            "success_criteria": ["能在 3 分钟内讲清核心项目", "记录卡点到笔记"],
                        },
                    ),
                    ToolCall(
                        name="learning_weakness_create",
                        arguments={
                            "weakness_id": "rag_depth",
                            "evidence_refs": ["application_stargazer_backend", "fit_stargazer_backend"],
                            "title": "RAG 深度表达不足",
                            "description": "匹配报告显示 RAG 有关键词，但生产级评估和失败恢复证据不足。",
                            "weakness_type": "skill_gap",
                            "severity": "high",
                            "state": "open",
                            "skill_tags": ["RAG"],
                            "target_application_ids": ["application_stargazer_backend"],
                            "source_report_ids": ["fit_stargazer_backend", "artifact_fit_report_stargazer"],
                            "related_task_ids": ["learning_task_rag_eval"],
                        },
                    ),
                ],
            )

        if not _assistant_called(messages, "learning_checkin_create"):
            assert "learning_checkin_create" in tool_names
            assert "learning_task_update_state" in tool_names
            assert "learning_weakness_update" in tool_names
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="learning_checkin_create",
                        arguments={
                            "evidence_refs": ["learning_plan_stargazer_backend_prep", "learning_task_rag_eval"],
                            "learning_plan_id": "learning_plan_stargazer_backend_prep",
                            "learning_task_id": "learning_task_rag_eval",
                            "minutes_spent": 45,
                            "progress_state": "completed",
                            "summary": "已完成 RAG 检索评估回答提纲。",
                            "blockers": [],
                            "confidence": "medium",
                            "next_action": "用模拟面试验证表达是否顺畅。",
                        },
                    ),
                    ToolCall(
                        name="learning_task_update_state",
                        arguments={"learning_task_id": "learning_task_rag_eval", "state": "done"},
                    ),
                    ToolCall(
                        name="learning_weakness_update",
                        arguments={
                            "weakness_id": "weakness_rag_depth",
                            "updates": {
                                "state": "improving",
                                "resolution_summary": "已完成 RAG 评估提纲，下一步通过模拟面试验证表达。",
                                "related_task_ids": ["learning_task_rag_eval"],
                            },
                        },
                    ),
                ],
            )

        return ModelResponse(content="学习计划、任务、打卡和短板跟踪已经串起来。", tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        _ = (system_prompt, messages, tools)
        if False:
            yield StreamChunk()
        raise NotImplementedError("streaming is not used in this test")


def test_m10_low_cost_career_to_learning_chain(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path, CareerToLearningPlanModel())
    bundle.session_repository.create_session("sess_learning_chain")
    _seed_career_records(bundle.career_store)

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_learning_chain",
            user_message="基于 application_stargazer_backend 的匹配报告，生成学习计划并模拟一次完成 RAG 任务后的打卡。",
            skill_names=["base", "tools"],
            max_tool_rounds=4,
            context=_context("sess_learning_chain"),
        )
    )

    plan = bundle.learning_store.get_learning_plan("learning_plan_stargazer_backend_prep")
    tasks = bundle.learning_store.list_learning_tasks(
        include_archived=True,
        learning_plan_id="learning_plan_stargazer_backend_prep",
    )
    checkins = bundle.learning_store.list_progress_checkins(
        include_archived=True,
        learning_task_id="learning_task_rag_eval",
    )
    weakness = bundle.learning_store.get_weakness_tracker("weakness_rag_depth")
    events = bundle.session_repository.list_events("sess_learning_chain")
    tool_calls = _tool_call_names(events)

    assert output.answer == "学习计划、任务、打卡和短板跟踪已经串起来。"
    assert plan is not None
    assert plan.target_application_id == "application_stargazer_backend"
    assert {"application_stargazer_backend", "fit_stargazer_backend"}.issubset(set(plan.evidence_refs))
    assert plan.progress_summary == "已从匹配报告拆解出面试准备任务。"
    assert len(tasks) == 4
    assert {task.learning_task_id for task in tasks} == {
        "learning_task_rag_eval",
        "learning_task_agent_architecture",
        "learning_task_async_queue",
        "learning_task_mock_interview",
    }
    rag_task = bundle.learning_store.get_learning_task("learning_task_rag_eval")
    assert rag_task is not None
    assert rag_task.state == "done"
    assert rag_task.completed_at is not None
    assert len(checkins) == 1
    assert checkins[0].minutes_spent == 45
    assert checkins[0].progress_state == "completed"
    assert weakness is not None
    assert weakness.state == "improving"
    assert weakness.source_report_ids == ["fit_stargazer_backend", "artifact_fit_report_stargazer"]
    assert "learning_task_rag_eval" in weakness.related_task_ids
    assert "career_application_get" in tool_calls
    assert "career_job_fit_report_get" in tool_calls
    assert tool_calls.count("learning_task_create") == 4
    assert "learning_checkin_create" in tool_calls
    assert "learning_task_update_state" in tool_calls
    assert "learning_weakness_update" in tool_calls
    assert "memory_write" not in tool_calls
    assert bundle.memory_manager.search(query="RAG 检索评估", limit=5, context=_context("sess_learning_chain")) == []
    assert not list((tmp_path / "learning").rglob("*.md"))


def _build_bundle(tmp_path: Path, model_client: ChatModelClient) -> LearningCareerChainBundle:
    session_repository = JsonlSessionRepository(data_dir=tmp_path / "sessions")
    career_store = CareerProductStore(root_dir=tmp_path / "career")
    learning_store = LearningStore(root_dir=tmp_path / "learning")
    capability_registry = load_agent_capability_registry(Path("app/config/agent_capabilities.json"))
    memory_store = FileMemoryStore(root_dir=tmp_path / "memory")
    memory_manager = MemoryManager(capability_registry=capability_registry, memory_store=memory_store)
    state_store = JsonlFileStateStore(root_dir=tmp_path / "state")
    state_manager = StateManager(store=state_store)
    tool_registry = ToolRegistry(capability_registry=capability_registry)
    tool_registry.register(CareerApplicationGetTool(career_store=career_store))
    tool_registry.register(CareerJobFitReportGetTool(career_store=career_store))
    tool_registry.register(LearningPlanCreateTool(learning_store=learning_store, session_repository=session_repository))
    tool_registry.register(LearningTaskCreateTool(learning_store=learning_store, session_repository=session_repository))
    tool_registry.register(LearningTaskUpdateStateTool(learning_store=learning_store))
    tool_registry.register(LearningCheckinCreateTool(learning_store=learning_store, session_repository=session_repository))
    tool_registry.register(LearningWeaknessCreateTool(learning_store=learning_store, session_repository=session_repository))
    tool_registry.register(LearningWeaknessUpdateTool(learning_store=learning_store, session_repository=session_repository))
    event_recorder = EventRecorder(session_repository=session_repository)
    context_assembler = ContextAssembler(
        session_repository=session_repository,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=MarkdownAgentDocumentRepository(agents_dir=Path("app/agents")),
        memory_manager=memory_manager,
        state_manager=state_manager,
        tool_executor=tool_registry,
    )
    runtime = AgentRuntime(
        session_manager=SessionManager(session_repository=session_repository),
        event_recorder=event_recorder,
        context_assembler=context_assembler,
        model_client=model_client,
        tool_executor=tool_registry,
        mid_term_flusher=MidTermFlusher(
            session_repository=session_repository,
            memory_store=memory_store,
            model_client=model_client,
        ),
    )
    return LearningCareerChainBundle(
        runtime=runtime,
        session_repository=session_repository,
        career_store=career_store,
        learning_store=learning_store,
        memory_manager=memory_manager,
    )


def _seed_career_records(career_store: CareerProductStore) -> None:
    now = datetime(2026, 5, 12, 0, 0, tzinfo=APP_TIMEZONE)
    career_store.save_resume_profile(
        ResumeProfile(
            resume_profile_id="resume_profile_stargazer",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_learning_chain",
            source_artifact_id="artifact_resume_stargazer",
            evidence_refs=["artifact_resume_stargazer"],
            created_at=now,
            updated_at=now,
            basic_info={"name": "张明"},
            skills=["Python", "FastAPI", "Redis"],
        )
    )
    career_store.save_career_profile(
        CareerProfile(
            career_profile_id="career_profile_default",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_learning_chain",
            source_artifact_id=None,
            evidence_refs=["resume_profile_stargazer"],
            created_at=now,
            updated_at=now,
            career_goal="AI Agent 后端工程师",
            target_roles=["AI Agent 后端工程师"],
            skills=["Python", "FastAPI", "Redis"],
            interview_weaknesses=["RAG 深度追问准备不足"],
        )
    )
    career_store.save_jd_analysis(
        JDAnalysis(
            jd_analysis_id="jd_stargazer_backend",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_learning_chain",
            source_artifact_id="artifact_jd_stargazer",
            evidence_refs=["artifact_jd_stargazer"],
            created_at=now,
            updated_at=now,
            company="星河智能",
            position="AI Agent 后端工程师",
            required_skills=["Python", "FastAPI", "RAG", "异步任务"],
            preferred_skills=["多 Agent 编排", "向量检索评估"],
            interview_focus=["RAG 检索评估", "Agent Runtime 架构", "异步任务可靠性"],
        )
    )
    career_store.save_job_fit_report(
        JobFitReport(
            job_fit_report_id="fit_stargazer_backend",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_learning_chain",
            source_artifact_id="artifact_jd_stargazer",
            evidence_refs=[
                "artifact_jd_stargazer",
                "resume_profile_stargazer",
                "career_profile_default",
                "jd_stargazer_backend",
            ],
            created_at=now,
            updated_at=now,
            jd_analysis_id="jd_stargazer_backend",
            resume_profile_id="resume_profile_stargazer",
            career_profile_id="career_profile_default",
            overall_score=76,
            score_breakdown={"backend": 85, "rag": 62, "agent": 72},
            matched_evidence=["Python/FastAPI 后端经验", "Redis 异步任务相关经验"],
            gaps=["RAG 检索评估证据不足", "多 Agent 编排表达需要准备"],
            interview_preparation_focus=["RAG chunk 策略与评估", "Agent Runtime 权限边界", "异步任务失败恢复"],
            recommendation="cautious",
            report_artifact_id="artifact_fit_report_stargazer",
        )
    )
    career_store.save_career_application(
        CareerApplication(
            application_id="application_stargazer_backend",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_learning_chain",
            source_artifact_id="artifact_jd_stargazer",
            evidence_refs=[
                "artifact_jd_stargazer",
                "resume_profile_stargazer",
                "career_profile_default",
                "jd_stargazer_backend",
                "fit_stargazer_backend",
                "artifact_fit_report_stargazer",
            ],
            created_at=now,
            updated_at=now,
            company="星河智能",
            position="AI Agent 后端工程师",
            location="上海",
            stage="ready_to_apply",
            priority="high",
            resume_profile_id="resume_profile_stargazer",
            career_profile_id="career_profile_default",
            jd_analysis_id="jd_stargazer_backend",
            job_fit_report_id="fit_stargazer_backend",
            summary="匹配度较高，但面试前需要补齐 RAG 与 Agent 架构表达。",
            next_actions=["准备 RAG 检索评估回答", "梳理 Agent Runtime 架构"],
            risks=["RAG 深度追问准备不足"],
        )
    )


def _context(session_id: str) -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}",
        agent_id="agent_main",
        turn_id=f"turn_{session_id}",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={},
    )


def _tool_names(tools: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        function = tool.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str):
                names.add(name)
    return names


def _assistant_called(messages: list[dict[str, Any]], tool_name: str) -> bool:
    for message in messages:
        if message.get("role") != "assistant":
            continue
        raw_tool_calls = message.get("tool_calls")
        if not isinstance(raw_tool_calls, list):
            continue
        for call in raw_tool_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if isinstance(function, dict) and function.get("name") == tool_name:
                return True
    return False


def _tool_call_names(events: list[Any]) -> list[str]:
    names: list[str] = []
    for event in events:
        if event.type != "tool_call":
            continue
        name = event.payload.get("name") if isinstance(event.payload, dict) else None
        if isinstance(name, str):
            names.append(name)
    return names
