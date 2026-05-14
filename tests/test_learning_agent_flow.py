"""Deterministic runtime tests for LearningService agent boundaries."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.time import app_now
from app.domain.models import AgentRunInput, RunContext, ToolCall
from app.domain.protocols import ChatModelClient, ModelResponse, StreamChunk
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.learning.models import LearningRecordStatus, LearningTask
from app.learning.store import LearningStore
from app.memory.file_store import FileMemoryStore
from app.runtime.agent_capability import AgentCapabilityRegistry, load_agent_capability_registry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.event_recorder import EventRecorder
from app.runtime.memory_manager import MemoryManager
from app.runtime.mid_term_flusher import MidTermFlusher
from app.runtime.session_manager import SessionManager
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
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
    MemoryWriteTool,
)
from app.tools.registry import ToolRegistry

__all__ = []


@dataclass(slots=True)
class LearningFlowBundle:
    runtime: AgentRuntime
    session_repository: JsonlSessionRepository
    learning_store: LearningStore
    memory_manager: MemoryManager


class CreateLearningPlanModel:
    """Drive an explicit learning-plan request with deterministic tool calls."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = system_prompt
        tool_names = _tool_names(tools)
        assert "learning_plan_create" in tool_names
        assert "learning_task_create" in tool_names
        if not _assistant_called(messages, "learning_plan_create"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="learning_plan_create",
                        arguments={
                            "learning_plan_id": "stargazer_backend",
                            "evidence_refs": ["application_alpha", "fit_stargazer_backend"],
                            "title": "星河智能面试准备计划",
                            "plan_type": "interview_prep",
                            "target_application_id": "application_alpha",
                            "target_role": "AI Agent 后端工程师",
                            "target_company": "星河智能",
                            "priority": "high",
                            "goals": ["讲清楚 RAG 评估", "准备异步任务架构"],
                            "focus_skill_tags": ["RAG", "FastAPI"],
                        },
                    )
                ],
            )
        if not _assistant_called(messages, "learning_task_create"):
            plan_id = _latest_record_id(messages, "learning_plan")
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="learning_task_create",
                        arguments={
                            "learning_task_id": "rag_eval",
                            "evidence_refs": [plan_id, "resource_rag_eval"],
                            "title": "准备 RAG 评估回答",
                            "learning_plan_id": plan_id,
                            "task_type": "write_answer",
                            "priority": "high",
                            "skill_tags": ["RAG"],
                            "estimated_minutes": 45,
                            "resource_refs": ["resource_rag_eval", "skill_req_rag_engineering"],
                            "success_criteria": ["覆盖指标", "说明失败恢复"],
                        },
                    )
                ],
            )
        return ModelResponse(content="学习计划已经建立，下一步先完成 RAG 评估回答。", tool_calls=[])

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


class ManualLearningTaskModel:
    """Create a user-initiated task without requiring career evidence."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        assert "学习任务有两类入口：用户主动添加和系统推荐添加" in system_prompt
        assert "如果召回为空，也可以创建任务" in system_prompt
        assert "来源：用户主动添加" in system_prompt
        assert "learning_task_create" in _tool_names(tools)

        if not _assistant_called(messages, "learning_task_create"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="learning_task_create",
                        arguments={
                            "learning_task_id": "manual_rag_metrics",
                            "evidence_refs": ["sess_learning_manual"],
                            "title": "补 RAG 评估指标基础",
                            "description": "用户主动添加：整理 precision、recall、hit rate 的定义和适用场景。",
                            "task_type": "write_answer",
                            "priority": "medium",
                            "state": "todo",
                            "skill_tags": ["RAG", "评估指标"],
                            "estimated_minutes": 30,
                            "success_criteria": ["写清 3 个指标定义", "各给一个面试表达例子"],
                            "progress_notes": "来源：用户主动添加",
                        },
                    )
                ],
            )
        return ModelResponse(content="已创建学习任务：补 RAG 评估指标基础。", tool_calls=[])

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


class LearningTaskCheckinModel:
    """Record progress checkin and update task state after explicit user report."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        assert "先定位相关 LearningTask" in system_prompt
        assert "打卡和任务状态更新不自动写 Note 或 memory" in system_prompt
        tool_names = _tool_names(tools)
        assert {"learning_task_list", "learning_checkin_create", "learning_task_update_state"} <= tool_names

        if not _assistant_called(messages, "learning_task_list"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="learning_task_list",
                        arguments={"state": "doing"},
                    )
                ],
            )
        if not _assistant_called(messages, "learning_checkin_create"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="learning_checkin_create",
                        arguments={
                            "checkin_id": "manual_rag_metrics_done",
                            "evidence_refs": ["learning_task_manual_rag_metrics", "sess_learning_checkin"],
                            "learning_task_id": "learning_task_manual_rag_metrics",
                            "minutes_spent": 40,
                            "progress_state": "completed",
                            "summary": "完成 RAG 评估指标整理，补了 precision、recall 和 hit rate 示例。",
                            "confidence": "medium",
                            "next_action": "下次把这些指标放进项目回答里演练。",
                        },
                    )
                ],
            )
        if not _assistant_called(messages, "learning_task_update_state"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="learning_task_update_state",
                        arguments={
                            "learning_task_id": "learning_task_manual_rag_metrics",
                            "state": "done",
                        },
                    )
                ],
            )
        return ModelResponse(content="已记录今日进度，并把任务标记为完成。", tool_calls=[])

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


def test_explicit_learning_plan_flow_creates_plan_and_task_without_memory_write(tmp_path: Path) -> None:
    bundle = _build_learning_flow_bundle(tmp_path, CreateLearningPlanModel())
    bundle.session_repository.create_session("sess_learning_plan")

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_learning_plan",
            user_message="根据当前匹配报告给我制定一个面试准备学习计划。",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_learning_plan"),
        )
    )

    plan = bundle.learning_store.get_learning_plan("learning_plan_stargazer_backend")
    task = bundle.learning_store.get_learning_task("learning_task_rag_eval")
    events = bundle.session_repository.list_events("sess_learning_plan")

    assert output.answer == "学习计划已经建立，下一步先完成 RAG 评估回答。"
    assert plan is not None
    assert plan.source_session_id == "sess_learning_plan"
    assert plan.target_application_id == "application_alpha"
    assert task is not None
    assert task.learning_plan_id == "learning_plan_stargazer_backend"
    assert task.estimated_minutes == 45
    assert bundle.memory_manager.search(query="RAG 评估", limit=5, context=_context("sess_learning_plan")) == []
    assert "learning_plan_create" in _tool_call_names(events)
    assert "learning_task_create" in _tool_call_names(events)
    assert "memory_write" not in _tool_call_names(events)
    assert not any(event.type == "memory_write" for event in events)


def test_manual_learning_task_can_be_created_without_career_evidence(tmp_path: Path) -> None:
    bundle = _build_learning_flow_bundle(tmp_path, ManualLearningTaskModel())
    bundle.session_repository.create_session("sess_learning_manual")

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_learning_manual",
            user_message="我自己想补一下 RAG 评估指标，帮我建一个学习任务。",
            skill_names=["base", "tools"],
            max_tool_rounds=2,
            context=_context("sess_learning_manual"),
        )
    )

    task = bundle.learning_store.get_learning_task("learning_task_manual_rag_metrics")
    events = bundle.session_repository.list_events("sess_learning_manual")

    assert output.answer == "已创建学习任务：补 RAG 评估指标基础。"
    assert task is not None
    assert task.learning_plan_id is None
    assert task.evidence_refs == ["sess_learning_manual"]
    assert task.progress_notes == "来源：用户主动添加"
    assert getattr(task.state, "value", task.state) == "todo"
    assert _tool_call_names(events) == ["learning_task_create"]
    assert "memory_write" not in _tool_call_names(events)
    assert bundle.memory_manager.search(query="RAG 评估指标", limit=5, context=_context("sess_learning_manual")) == []


def test_learning_checkin_records_progress_and_updates_task_state_without_memory(tmp_path: Path) -> None:
    bundle = _build_learning_flow_bundle(tmp_path, LearningTaskCheckinModel())
    bundle.session_repository.create_session("sess_learning_checkin")
    _seed_learning_task(bundle.learning_store, session_id="sess_learning_checkin")

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_learning_checkin",
            user_message="我刚学了 40 分钟 RAG 评估指标，已经完成了，把任务也标记完成。",
            skill_names=["base", "tools"],
            max_tool_rounds=4,
            context=_context("sess_learning_checkin"),
        )
    )

    task = bundle.learning_store.get_learning_task("learning_task_manual_rag_metrics")
    checkin = bundle.learning_store.get_progress_checkin("checkin_manual_rag_metrics_done")
    events = bundle.session_repository.list_events("sess_learning_checkin")

    assert output.answer == "已记录今日进度，并把任务标记为完成。"
    assert checkin is not None
    assert checkin.learning_task_id == "learning_task_manual_rag_metrics"
    assert checkin.minutes_spent == 40
    assert getattr(checkin.progress_state, "value", checkin.progress_state) == "completed"
    assert "precision、recall" in checkin.summary
    assert task is not None
    assert getattr(task.state, "value", task.state) == "done"
    assert task.completed_at is not None
    assert _tool_call_names(events) == [
        "learning_task_list",
        "learning_checkin_create",
        "learning_task_update_state",
    ]
    assert "memory_write" not in _tool_call_names(events)
    assert bundle.memory_manager.search(query="今日进度", limit=5, context=_context("sess_learning_checkin")) == []


def test_learning_agent_contract_and_capabilities_keep_child_agents_read_only() -> None:
    main_doc = Path("app/agents/default/AGENT.md").read_text(encoding="utf-8")
    capability = load_agent_capability_registry(Path("app/config/agent_capabilities.json"))
    main_capability = capability.require("agent_main")
    resume_capability = capability.require("resume_agent")
    job_capability = capability.require("job_agent")

    assert "LearningService 用于用户可见、可追踪的学习计划、任务、打卡和能力短板" in main_doc
    assert "才调用 learning 工具" in main_doc
    assert "学习任务有两类入口：用户主动添加和系统推荐添加" in main_doc
    assert "如果召回为空，也可以创建任务" in main_doc
    assert "系统推荐添加学习任务时，必须先召回或复用本轮已经召回的上下文" in main_doc
    assert "先定位相关 LearningTask" in main_doc
    assert "打卡和任务状态更新不自动写 Note 或 memory" in main_doc
    assert "Learning 工具不会也不应该触发 memory 写入" in main_doc
    assert "resume_agent` 和 `job_agent` 默认不写 LearningService" in main_doc
    assert main_capability.allows_tool("learning_plan_create")
    assert main_capability.allows_tool("learning_task_create")
    assert main_capability.allows_tool("learning_checkin_create")
    assert main_capability.allows_tool("learning_weakness_update")
    assert not resume_capability.allows_tool("learning_plan_create")
    assert not resume_capability.allows_tool("learning_task_create")
    assert not job_capability.allows_tool("learning_plan_create")
    assert not job_capability.allows_tool("learning_task_create")


def _build_learning_flow_bundle(tmp_path: Path, model_client: ChatModelClient) -> LearningFlowBundle:
    session_repository = JsonlSessionRepository(data_dir=tmp_path / "sessions")
    learning_store = LearningStore(root_dir=tmp_path / "learning")
    memory_store = FileMemoryStore(root_dir=tmp_path / "memory")
    capability_registry = AgentCapabilityRegistry.for_tests()
    memory_manager = MemoryManager(capability_registry=capability_registry, memory_store=memory_store)
    state_store = JsonlFileStateStore(root_dir=tmp_path / "state")
    state_manager = StateManager(store=state_store)
    tool_registry = ToolRegistry(capability_registry=capability_registry)
    tool_registry.register(MemoryWriteTool(memory_manager=memory_manager))
    tool_registry.register(LearningPlanCreateTool(learning_store=learning_store, session_repository=session_repository))
    tool_registry.register(LearningPlanGetTool(learning_store=learning_store))
    tool_registry.register(LearningPlanListTool(learning_store=learning_store))
    tool_registry.register(LearningTaskCreateTool(learning_store=learning_store, session_repository=session_repository))
    tool_registry.register(LearningTaskGetTool(learning_store=learning_store))
    tool_registry.register(LearningTaskListTool(learning_store=learning_store))
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
    return LearningFlowBundle(
        runtime=runtime,
        session_repository=session_repository,
        learning_store=learning_store,
        memory_manager=memory_manager,
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


def _seed_learning_task(store: LearningStore, *, session_id: str) -> None:
    now = app_now()
    store.save_learning_task(
        LearningTask(
            learning_task_id="learning_task_manual_rag_metrics",
            status=LearningRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=None,
            evidence_refs=[session_id],
            created_at=now,
            updated_at=now,
            title="补 RAG 评估指标基础",
            description="用户主动添加：整理 precision、recall、hit rate。",
            task_type="write_answer",
            priority="medium",
            state="doing",
            skill_tags=["RAG", "评估指标"],
            estimated_minutes=30,
            success_criteria=["写清 3 个指标定义", "各给一个面试表达例子"],
            progress_notes="来源：用户主动添加",
        )
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


def _latest_record_id(messages: list[dict[str, Any]], record_type: str) -> str:
    record_ids: list[str] = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("record_type") == record_type:
            record_id = payload.get("record_id")
            if isinstance(record_id, str):
                record_ids.append(record_id)
    if not record_ids:
        raise AssertionError(f"expected {record_type} record id")
    return record_ids[-1]


def _tool_call_names(events: list[Any]) -> list[str]:
    names: list[str] = []
    for event in events:
        if event.type != "tool_call":
            continue
        name = event.payload.get("name") if isinstance(event.payload, dict) else None
        if isinstance(name, str):
            names.append(name)
    return names
