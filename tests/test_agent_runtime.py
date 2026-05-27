"""Tests for agent runtime execution loop."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.models import (
    AgentRunInput,
    AgentRunOutput,
    EventRecord,
    RunContext,
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
)
from app.domain.protocols import ChatModelClient, ModelResponse, StreamChunk
from app.infra.storage.jsonl_tool_call_ledger import JsonlToolCallLedger
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.file_store import FileMemoryStore
from app.runtime.agent_events import AGENT_TASK_ASSIGNED_EVENT, AgentTaskAssignedPayload
from app.runtime.agent_capability import AgentCapabilityRegistry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.event_channel import EventChannel
from app.runtime.event_recorder import EventRecorder
from app.runtime.mid_term_flusher import MidTermFlusher, MidTermFlushResult
from app.runtime.memory_manager import MemoryManager
from app.runtime.workflow import WorkflowGuardDecision
from app.runtime.session_manager import SessionManager
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.tools.builtins import MemoryWriteTool
from app.tools.base import Tool
from app.tools.builtin_tools import ToolSearchTool
from app.tools.registry import ToolRegistry
from tests.helpers import SequenceModelClient, StaticModelClient

__all__ = []


def _capability_registry() -> AgentCapabilityRegistry:
    return AgentCapabilityRegistry.for_tests()


def _context(session_id: str, agent_id: str = "agent_main") -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}",
        agent_id=agent_id,
        turn_id=f"turn_{session_id}",
        entry_agent_id=agent_id,
        parent_run_id=None,
        trace_flags={},
    )



def _build_runtime(
    tmp_path: Path,
    model_client: ChatModelClient,
    *,
    extra_tools: list[Tool] | None = None,
    register_tool_search: bool = False,
    tool_schema_disclosure_mode: str = "full",
    tool_schema_always_visible: str | list[str] | None = None,
    tool_context_window_mode: str = "off",
    workflow_guard: Any | None = None,
    tool_call_ledger: JsonlToolCallLedger | None = None,
) -> tuple[AgentRuntime, JsonlSessionRepository, MemoryManager]:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    state_store = JsonlFileStateStore(root_dir=tmp_path / "state")
    state_manager = StateManager(store=state_store)
    skill_repo = MarkdownSkillRepository(skills_dir=Path("app/skills"))
    agent_document_repository = MarkdownAgentDocumentRepository(agents_dir=Path("app/agents"))
    capability_registry = _capability_registry()
    memory_store = FileMemoryStore(root_dir=tmp_path / "memory")

    memory_manager = MemoryManager(
        capability_registry=capability_registry,
        memory_store=memory_store,
    )
    tool_registry = ToolRegistry(capability_registry=capability_registry)
    tool_registry.register(MemoryWriteTool(memory_manager=memory_manager))
    for tool in extra_tools or []:
        tool_registry.register(tool)
    if register_tool_search:
        tool_registry.register(ToolSearchTool(tool_definitions_provider=tool_registry.list_definitions_for_agent))

    session_manager = SessionManager(session_repository=session_repo)
    event_recorder = EventRecorder(session_repository=session_repo)
    context_assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=skill_repo,
        agent_document_repository=agent_document_repository,
        memory_manager=memory_manager,
        state_manager=state_manager,
        tool_executor=tool_registry,
        tool_schema_disclosure_mode=tool_schema_disclosure_mode,
        tool_schema_always_visible=tool_schema_always_visible,
    )
    runtime = AgentRuntime(
        session_manager=session_manager,
        event_recorder=event_recorder,
        context_assembler=context_assembler,
        model_client=model_client,
        tool_executor=tool_registry,
        mid_term_flusher=MidTermFlusher(
            session_repository=session_repo,
            memory_store=memory_store,
            model_client=model_client,
        ),
        tool_schema_disclosure_mode=tool_schema_disclosure_mode,
        tool_schema_always_visible=tool_schema_always_visible,
        tool_context_window_mode=tool_context_window_mode,
        workflow_guard=workflow_guard,
        tool_call_ledger=tool_call_ledger,
    )
    return runtime, session_repo, memory_manager



def test_runtime_without_tool_calls_finishes(tmp_path: Path) -> None:
    runtime, session_repo, _ = _build_runtime(tmp_path, StaticModelClient(content="hello"))

    output = runtime.run(
        AgentRunInput(
            session_id="sess_1",
            user_message="hi",
            skill_names=["base"],
            max_tool_rounds=3,
            context=_context("sess_1"),
        )
    )

    events = session_repo.list_events("sess_1")

    assert output.answer == "hello"
    assert len(output.tool_calls) == 0
    assert any(event.type == "run_finished" for event in events)
    usage_events = [event for event in events if event.type == "llm_usage"]
    assert len(usage_events) == 1
    assert usage_events[0].payload["estimated"] is True
    assert usage_events[0].payload["total_tokens"] > 0
    assert usage_events[0].payload["prompt_estimate_total_tokens"] > 0
    assert usage_events[0].payload["system_prompt_estimate_tokens"] > 0
    assert usage_events[0].payload["system_prompt_section_count"] > 0
    assert usage_events[0].payload["system_prompt_sections"]
    assert usage_events[0].payload["messages_estimate_tokens"] > 0
    assert usage_events[0].payload["tools_estimate_tokens"] >= 0
    assert usage_events[0].payload["message_user_estimate_tokens"] > 0
    assert usage_events[0].payload["message_assistant_estimate_tokens"] == 0
    assert usage_events[0].payload["message_tool_estimate_tokens"] == 0



def test_runtime_with_tool_calls_loops_and_finishes(tmp_path: Path) -> None:
    model = SequenceModelClient(
        responses=[
            ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="memory_write",
                        arguments={"content": "User prefers JSONL", "tags": ["preference"]},
                    )
                ],
            ),
            ModelResponse(content="saved", tool_calls=[]),
        ]
    )
    runtime, session_repo, memory_manager = _build_runtime(tmp_path, model)

    output = runtime.run(
        AgentRunInput(
            session_id="sess_2",
            user_message="remember this",
            skill_names=["base", "memory"],
            max_tool_rounds=3,
            context=_context("sess_2"),
        )
    )

    events = session_repo.list_events("sess_2")
    memories = memory_manager.search(query="jsonl", limit=10, context=_context("sess_2"))

    assert output.answer == "saved"
    assert len(output.tool_calls) == 1
    assert any(event.type == "tool_call" for event in events)
    assert any(event.type == "tool_result" for event in events)
    assert any(event.type == "memory_write" for event in events)
    assert any(item.content == "User prefers JSONL" for item in memories)


def test_child_resume_diagnosis_executor_runs_closed_tool_chain(tmp_path: Path) -> None:
    class JsonTool:
        def __init__(self, name: str) -> None:
            self._name = name
            self.calls: list[dict[str, Any]] = []

        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name=self._name,
                description=f"{self._name} test tool.",
                parameters_schema={"type": "object", "properties": {}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = context
            self.calls.append(dict(arguments))
            if self._name == "session_create_text_artifact":
                return ToolExecutionResult(
                    tool_name=self._name,
                    success=True,
                    content=json.dumps(
                        {
                            "artifact_id": "artifact_resume_diagnosis",
                            "title": arguments.get("title"),
                            "kind": "generated_file",
                        },
                        ensure_ascii=False,
                    ),
                )
            return ToolExecutionResult(
                tool_name=self._name,
                success=True,
                content=json.dumps(
                    {
                        "record_type": "resume_profile",
                        "record_id": "resume_profile_alpha",
                        "record": {
                            "resume_profile_id": "resume_profile_alpha",
                            "diagnosis_artifact_id": arguments.get("diagnosis_artifact_id"),
                        },
                    },
                    ensure_ascii=False,
                ),
            )

    payload = {
        "diagnosis_title": "简历质量诊断报告 - 张三",
        "diagnosis_markdown": "# 简历质量诊断报告\n\n候选人具备 Python 和 FastAPI 后端经验，建议补充量化成果。",
        "resume_profile": {
            "resume_profile_id": "resume_profile_alpha",
            "basic_info": {"name": "张三", "target_direction": "AI 应用开发 / 后端工程师"},
            "education": [{"school": "计算机相关专业本科", "degree": "本科"}],
            "work_experience": [{"position": "后端工程师", "duration": "3年"}],
            "project_experience": [{"project_name": "简历诊断 Agent"}],
            "skills": ["Python", "FastAPI", "RAG"],
            "certificates": [],
            "awards": [],
            "self_evaluation": "具备后端和 AI 应用开发经验。",
            "diagnosis": {"issues": ["缺少量化成果"]},
        },
    }
    model = SequenceModelClient([ModelResponse(content=json.dumps(payload, ensure_ascii=False), tool_calls=[])])
    artifact_tool = JsonTool("session_create_text_artifact")
    profile_tool = JsonTool("career_resume_profile_save")
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[artifact_tool, profile_tool],
        tool_schema_disclosure_mode="search",
    )
    session_repo.create_session("sess_resume_executor")
    session_repo.append_event(
        "sess_resume_executor",
        EventRecord(
            event_id="evt_task_resume",
            session_id="sess_resume_executor",
            type=AGENT_TASK_ASSIGNED_EVENT,
            payload=AgentTaskAssignedPayload(
                task_id="task_resume",
                source_agent_id="agent_main",
                target_agent_id="resume_agent",
                instruction="请解析简历并保存诊断报告和 ResumeProfile。",
                artifact_refs=["artifact_resume_alpha"],
                task_context={
                    "schema_version": 1,
                    "phase": "resume_diagnosis",
                    "provided_inputs_complete": True,
                    "known_refs": {"resume_source_artifact_id": "artifact_resume_alpha"},
                    "provided_artifacts": [{"artifact_id": "artifact_resume_alpha", "text_preview": "张三 Python"}],
                    "required_outputs": ["diagnosis_artifact", "resume_profile"],
                    "allowed_initial_tools": ["session_create_text_artifact"],
                },
                parent_run_id="run_parent",
                child_run_id="run_child",
            ).to_payload(),
            created_at=datetime.now(UTC),
            agent_id="agent_main",
            run_id="run_parent",
        ),
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_resume_executor",
            user_message="开始执行子任务",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=RunContext(
                session_id="sess_resume_executor",
                run_id="run_child",
                agent_id="resume_agent",
                turn_id="turn_resume_executor",
                entry_agent_id="agent_main",
                parent_run_id="run_parent",
                task_id="task_resume",
                trace_flags={},
            ),
        )
    )

    assert [call.name for call in output.tool_calls] == [
        "session_create_text_artifact",
        "career_resume_profile_save",
    ]
    assert profile_tool.calls[0]["source_artifact_id"] == "artifact_resume_alpha"
    assert profile_tool.calls[0]["diagnosis_artifact_id"] == "artifact_resume_diagnosis"
    assert "`resume_profile_alpha`" in output.answer
    decisions = [
        event.payload
        for event in session_repo.list_agent_events("sess_resume_executor", "resume_agent")
        if event.type == "workflow_runtime_decision"
    ]
    assert any(item.get("contract_id") == "career.resume_diagnosis.child.v1" for item in decisions)
    assert any(item.get("reason") == "workflow_executor_completed" for item in decisions)


def test_runtime_uses_workflow_guard_result_without_executing_tool(tmp_path: Path) -> None:
    class GuardedTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="guarded_tool",
                description="tool protected by workflow guard",
                parameters_schema={"type": "object", "properties": {"value": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            raise AssertionError("guarded_tool should not execute when guard returns a result")

    class SyntheticGuard:
        def inspect(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
            _ = context
            return WorkflowGuardDecision(
                tool_call=tool_call,
                result=ToolExecutionResult(
                    tool_name=tool_call.name,
                    success=True,
                    content=json.dumps({"workflow_runtime_result": True, "policy": "reuse"}, ensure_ascii=False),
                ),
                event_payload={"workflow_runtime_result": True, "policy": "reuse", "tool_name": tool_call.name},
            )

    model = SequenceModelClient(
        responses=[
            ModelResponse(
                content="",
                tool_calls=[ToolCall(name="guarded_tool", arguments={"value": "x"}, tool_call_id="call_guarded")],
            ),
            ModelResponse(content="guarded done", tool_calls=[]),
        ]
    )
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[GuardedTool()],
        workflow_guard=SyntheticGuard(),
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_runtime_guard",
            user_message="run guarded tool",
            skill_names=["base", "tools"],
            max_tool_rounds=2,
            context=_context("sess_runtime_guard"),
        )
    )

    events = session_repo.list_events("sess_runtime_guard")

    assert output.answer == "guarded done"
    assert any(event.type == "workflow_runtime_decision" for event in events)
    tool_result = next(event for event in events if event.type == "tool_result")
    assert json.loads(tool_result.payload["content"])["workflow_runtime_result"] is True


def test_runtime_terminal_workflow_block_goes_directly_to_final_answer(tmp_path: Path) -> None:
    class GuardedTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="guarded_tool",
                description="tool protected by terminal workflow guard",
                parameters_schema={"type": "object", "properties": {}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            raise AssertionError("guarded_tool should not execute when terminal guard returns a result")

    class TerminalGuard:
        def inspect(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
            _ = context
            return WorkflowGuardDecision(
                tool_call=tool_call,
                result=ToolExecutionResult(
                    tool_name=tool_call.name,
                    success=True,
                    content=json.dumps(
                        {
                            "workflow_runtime_result": True,
                            "policy": "block",
                            "terminal": True,
                            "reason": "main_jd_fit_stage_complete_final_answer",
                            "next_action": "直接最终答复。",
                        },
                        ensure_ascii=False,
                    ),
                ),
                event_payload={
                    "workflow_runtime_result": True,
                    "policy": "block",
                    "terminal": True,
                    "tool_name": tool_call.name,
                },
            )

    class TerminalModelClient:
        def __init__(self) -> None:
            self.calls = 0
            self.tool_names_by_call: list[set[str]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            self.tool_names_by_call.append({item["function"]["name"] for item in tools})
            if self.calls == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="guarded_tool", arguments={}, tool_call_id="call_terminal")],
                )
            assert tools == []
            return ModelResponse(content="阶段已完成，这是最终答复。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = TerminalModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[GuardedTool()],
        workflow_guard=TerminalGuard(),
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_terminal_workflow_block",
            user_message="继续读取已经完成的报告",
            skill_names=["base", "tools"],
            max_tool_rounds=4,
            context=_context("sess_terminal_workflow_block"),
        )
    )
    usage_phases = [
        event.payload["phase"]
        for event in session_repo.list_events("sess_terminal_workflow_block")
        if event.type == "llm_usage"
    ]

    assert output.answer == "阶段已完成，这是最终答复。"
    assert model.calls == 2
    assert model.tool_names_by_call[1] == set()
    assert usage_phases == ["tool_loop", "final_answer_recovery"]


def test_runtime_recovers_when_final_round_returns_empty_answer(tmp_path: Path) -> None:
    model = SequenceModelClient(
        responses=[
            ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="memory_write",
                        arguments={"content": "User prefers JSONL", "tags": ["preference"]},
                    )
                ],
            ),
            ModelResponse(content="", tool_calls=[]),
            ModelResponse(content="已经为你整理好了最终答复。", tool_calls=[]),
        ]
    )
    runtime, _, _ = _build_runtime(tmp_path, model)

    output = runtime.run(
        AgentRunInput(
            session_id="sess_recover_sync",
            user_message="remember this",
            skill_names=["base", "memory"],
            max_tool_rounds=3,
            context=_context("sess_recover_sync"),
        )
    )

    assert output.answer == "已经为你整理好了最终答复。"



def test_runtime_finalizes_instead_of_returning_tool_round_limit(tmp_path: Path) -> None:
    model = SequenceModelClient(
        responses=[
            ModelResponse(
                content="",
                tool_calls=[ToolCall(name="memory_write", arguments={"content": "x", "tags": []})],
            )
        ]
    )
    runtime, session_repo, _ = _build_runtime(tmp_path, model)

    output = runtime.run(
        AgentRunInput(
            session_id="sess_3",
            user_message="loop",
            skill_names=["base"],
            max_tool_rounds=0,
            context=_context("sess_3"),
        )
    )

    assert "Tool call limit reached" not in output.answer
    assert "停止继续执行重复步骤" in output.answer
    decisions = [
        event.payload
        for event in session_repo.list_events("sess_3")
        if event.type == "workflow_runtime_decision"
    ]
    assert any(item.get("reason") == "tool_call_soft_budget_exceeded" for item in decisions)
    assert any(item.get("reason") == "tool_loop_stagnation" for item in decisions)


def test_runtime_rejects_internal_limit_text_from_model_answer(tmp_path: Path) -> None:
    model = SequenceModelClient(
        responses=[
            ModelResponse(
                content='运行时工具状态摘要（完整工具结果见事件日志）： {"runtime_tool_state":"compact"}',
                tool_calls=[],
            ),
            ModelResponse(content="这是可用的最终答复。", tool_calls=[]),
        ]
    )
    runtime, session_repo, _ = _build_runtime(tmp_path, model)

    output = runtime.run(
        AgentRunInput(
            session_id="sess_internal_answer_recovery",
            user_message="给我最终结果",
            skill_names=["base"],
            max_tool_rounds=1,
            context=_context("sess_internal_answer_recovery"),
        )
    )

    assert output.answer == "这是可用的最终答复。"
    events = session_repo.list_events("sess_internal_answer_recovery")
    assert any(event.type == "assistant_answer_rejected" for event in events)
    assistant_messages = [event.payload["content"] for event in events if event.type == "assistant_message"]
    assert assistant_messages == ["这是可用的最终答复。"]


def test_runtime_repeated_tool_search_without_new_reveal_finalizes(tmp_path: Path) -> None:
    class EmptyToolSearch:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="tool_search",
                description="Search tools.",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="tool_search",
                success=True,
                content=json.dumps({"revealed_tool_names": [], "revealed_tool_count": 0}, ensure_ascii=False),
            )

    model = SequenceModelClient(
        responses=[
            ModelResponse(content="", tool_calls=[ToolCall(name="tool_search", arguments={"query": "unknown"})]),
            ModelResponse(content="", tool_calls=[ToolCall(name="tool_search", arguments={"query": "unknown"})]),
            ModelResponse(content="已基于当前上下文给出阶段性结果。", tool_calls=[]),
        ]
    )
    runtime, session_repo, _ = _build_runtime(tmp_path, model, extra_tools=[EmptyToolSearch()])

    output = runtime.run(
        AgentRunInput(
            session_id="sess_repeated_empty_search",
            user_message="找一个不存在的工具",
            skill_names=["base", "tools"],
            max_tool_rounds=5,
            context=_context("sess_repeated_empty_search"),
        )
    )

    assert output.answer == "已基于当前上下文给出阶段性结果。"
    assert [call.name for call in output.tool_calls] == ["tool_search", "tool_search"]
    decisions = [
        event.payload
        for event in session_repo.list_events("sess_repeated_empty_search")
        if event.type == "workflow_runtime_decision"
    ]
    assert any(
        item.get("reason") == "tool_loop_stagnation"
        and item.get("stop_reason") == "schema_search_without_new_reveal"
        for item in decisions
    )


def test_runtime_builds_valid_tool_message_flow(tmp_path: Path) -> None:
    class CapturingModelClient:
        def __init__(self) -> None:
            self.calls: list[list[dict[str, Any]]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, tools)
            self.calls.append(messages)
            if len(self.calls) == 1:
                return ModelResponse(
                    content="",
                    reasoning_content="provider thinking state",
                    tool_calls=[
                        ToolCall(
                            name="memory_write",
                            arguments={"content": "remember", "tags": ["t"]},
                            tool_call_id="call_test_1",
                        )
                    ],
                )
            return ModelResponse(content="done", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = CapturingModelClient()
    runtime, _, _ = _build_runtime(tmp_path, model)
    output = runtime.run(
        AgentRunInput(
            session_id="sess_4",
            user_message="run tools",
            skill_names=["base", "tools"],
            max_tool_rounds=2,
            context=_context("sess_4"),
        )
    )

    second_call_messages = model.calls[1]
    assistant_tool_call_message = next(
        msg for msg in second_call_messages if msg.get("role") == "assistant" and "tool_calls" in msg
    )
    tool_result_message = next(msg for msg in second_call_messages if msg.get("role") == "tool")

    assert output.answer == "done"
    assert assistant_tool_call_message["reasoning_content"] == "provider thinking state"
    assert assistant_tool_call_message["tool_calls"][0]["id"] == "call_test_1"
    assert tool_result_message["tool_call_id"] == "call_test_1"


def test_runtime_replays_compact_tool_result_to_model_but_records_full_event(tmp_path: Path) -> None:
    class LargeRetrievalTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="retrieval_context_pack",
                description="test retrieval tool",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            payload = {
                "query": "星河智能 RAG 二面准备",
                "session_id": "sess_compact_tool_view",
                "count": 1,
                "context_char_count": 30000,
                "context_pack": {
                    "hits": [
                        {
                            "source": {
                                "source_type": "job_fit_report",
                                "source_id": "fit_alpha_001",
                                "artifact_id": "artifact_fit_report",
                            },
                            "title": "星河智能匹配报告",
                            "summary": "后端能力匹配，RAG 实践偏弱。",
                            "snippet": "候选人需要补齐 RAG 深度实践。",
                            "match_reason": "命中岗位和 RAG 短板。",
                            "score": 0.9,
                        }
                    ],
                    "grouped_context": {"career": [{"snippet": "FULL_GROUPED_CONTEXT_MARKER" * 1000}]},
                    "citations": [
                        {
                            "source_type": "job_fit_report",
                            "source_id": "fit_alpha_001",
                            "artifact_id": "artifact_fit_report",
                        }
                    ],
                    "omitted": [],
                    "omitted_count": 0,
                    "context_char_count": 30000,
                },
            }
            return ToolExecutionResult(
                tool_name="retrieval_context_pack",
                success=True,
                content=json.dumps(payload, ensure_ascii=False),
            )

    class CapturingModelClient:
        def __init__(self) -> None:
            self.calls: list[list[dict[str, Any]]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, tools)
            self.calls.append(messages)
            if len(self.calls) == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="retrieval_context_pack",
                            arguments={"query": "星河智能 RAG"},
                            tool_call_id="call_retrieval_1",
                        )
                    ],
                )
            return ModelResponse(content="done", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = CapturingModelClient()
    runtime, session_repo, _ = _build_runtime(tmp_path, model, extra_tools=[LargeRetrievalTool()])

    output = runtime.run(
        AgentRunInput(
            session_id="sess_compact_tool_view",
            user_message="帮我看之前的星河智能 RAG 准备",
            skill_names=["base", "tools"],
            max_tool_rounds=2,
            context=_context("sess_compact_tool_view"),
        )
    )

    events = session_repo.list_events("sess_compact_tool_view")
    full_tool_events = [event for event in events if event.type == "tool_result"]
    model_tool_message = next(message for message in model.calls[1] if message.get("role") == "tool")
    compact_payload = json.loads(str(model_tool_message["content"]))

    assert output.answer == "done"
    assert "FULL_GROUPED_CONTEXT_MARKER" in full_tool_events[0].payload["content"]
    assert "FULL_GROUPED_CONTEXT_MARKER" not in str(model_tool_message["content"])
    assert compact_payload["model_view"] == "compact"
    assert compact_payload["top_hits"][0]["source"]["source_id"] == "fit_alpha_001"


def test_runtime_compacts_consumed_tool_exchange_in_model_messages(tmp_path: Path) -> None:
    class CapturingModelClient:
        def __init__(self) -> None:
            self.calls: list[list[dict[str, Any]]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, tools)
            self.calls.append(messages)
            if len(self.calls) == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="memory_write",
                            arguments={"content": "first compact memory", "tags": ["t"]},
                            tool_call_id="call_first",
                        )
                    ],
                )
            if len(self.calls) == 2:
                tool_messages = [message for message in messages if message.get("role") == "tool"]
                assert [message.get("tool_call_id") for message in tool_messages] == ["call_first"]
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="memory_write",
                            arguments={"content": "second compact memory", "tags": ["t"]},
                            tool_call_id="call_second",
                        )
                    ],
                )
            tool_messages = [message for message in messages if message.get("role") == "tool"]
            state_messages = [
                message
                for message in messages
                if message.get("role") == "assistant" and "runtime_tool_state" in str(message.get("content"))
            ]
            assert [message.get("tool_call_id") for message in tool_messages] == ["call_second"]
            assert state_messages
            assert "call_first" in str(state_messages[0]["content"])
            assert "call_first" not in json.dumps(tool_messages, ensure_ascii=False)
            return ModelResponse(content="done", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = CapturingModelClient()
    runtime, session_repo, _ = _build_runtime(tmp_path, model, tool_context_window_mode="compact")

    output = runtime.run(
        AgentRunInput(
            session_id="sess_tool_context_window",
            user_message="run compact tool window",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_tool_context_window"),
        )
    )
    usage_events = [event for event in session_repo.list_events("sess_tool_context_window") if event.type == "llm_usage"]

    assert output.answer == "done"
    assert usage_events[0].payload["tool_context_window_mode"] == "compact"
    assert usage_events[2].payload["compacted_tool_observation_count"] == 1
    assert usage_events[2].payload["tool_state_message_estimate_tokens"] > 0
    assert usage_events[2].payload["pending_tool_exchange_count"] == 1


def test_runtime_search_disclosure_reveals_tool_schema_after_tool_search(tmp_path: Path) -> None:
    class RetrievalTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="retrieval_context_pack",
                description="Build context from saved records.",
                parameters_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="retrieval_context_pack",
                success=True,
                content=json.dumps({"context_pack": {"hits": []}}, ensure_ascii=False),
            )

    class RevealModelClient:
        def __init__(self) -> None:
            self.tool_names_by_call: list[set[str]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            tool_names = {item["function"]["name"] for item in tools}
            self.tool_names_by_call.append(tool_names)
            if len(self.tool_names_by_call) == 1:
                assert tool_names == {"tool_search", "memory_write"}
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="tool_search",
                            arguments={"query": "召回之前保存过的求职项目和匹配报告"},
                            tool_call_id="call_tool_search_1",
                        )
                    ],
                )
            if len(self.tool_names_by_call) == 2:
                assert "retrieval_context_pack" in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="retrieval_context_pack",
                            arguments={"query": "星河智能二面准备"},
                            tool_call_id="call_retrieval_1",
                        )
                    ],
                )
            return ModelResponse(content="done", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = RevealModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[RetrievalTool()],
        register_tool_search=True,
        tool_schema_disclosure_mode="search",
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_tool_reveal",
            user_message="根据之前保存过的内容帮我准备面试。",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_tool_reveal"),
        )
    )
    usage_events = [event for event in session_repo.list_events("sess_tool_reveal") if event.type == "llm_usage"]

    assert output.answer == "done"
    assert model.tool_names_by_call[0] == {"tool_search", "memory_write"}
    assert "retrieval_context_pack" in model.tool_names_by_call[1]
    assert usage_events[0].payload["tool_disclosure_mode"] == "search"
    assert usage_events[0].payload["visible_tool_names"] == ["memory_write", "tool_search"]
    assert "retrieval_context_pack" in usage_events[1].payload["revealed_tool_names"]


def test_runtime_search_disclosure_uses_runtime_plan_initial_visible_tools(tmp_path: Path) -> None:
    class StaticTool:
        def __init__(self, name: str) -> None:
            self._name = name

        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name=self._name,
                description=f"{self._name} description",
                parameters_schema={"type": "object", "properties": {}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(tool_name=self._name, success=True, content="{}")

    class InitialVisibleModelClient:
        def __init__(self) -> None:
            self.tool_names: set[str] = set()
            self.tool_names_by_call: list[set[str]] = []
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            self.tool_names = {item["function"]["name"] for item in tools}
            self.tool_names_by_call.append(self.tool_names)
            if self.calls == 1:
                return ModelResponse(content="done", tool_calls=[])
            if self.calls == 2:
                assert any("运行时守卫" in str(message.get("content", "")) for message in messages)
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_resume_version_create",
                            arguments={"base_resume_profile_id": "resume_profile_alpha", "title": "定制简历"},
                        )
                    ],
                )
            return ModelResponse(content="done", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = InitialVisibleModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[
            StaticTool("career_application_get"),
            StaticTool("career_resume_profile_get"),
            StaticTool("career_jd_analysis_get"),
            StaticTool("career_job_fit_report_get"),
            StaticTool("career_resume_version_create"),
        ],
        register_tool_search=True,
        tool_schema_disclosure_mode="search",
    )
    session_id = "sess_runtime_plan_initial_visible"
    session_repo.create_session(session_id)
    now = datetime.now(UTC)
    for event_id, tool_name, content in [
        (
            "evt_resume_profile",
            "career_resume_profile_save",
            {
                "record_type": "resume_profile",
                "record_id": "resume_profile_alpha",
                "status": "active",
                "record": {
                    "resume_profile_id": "resume_profile_alpha",
                    "source_artifact_id": "artifact_resume_source",
                },
            },
        ),
        (
            "evt_fit_report",
            "career_job_fit_report_save",
            {
                "record_type": "job_fit_report",
                "record_id": "fit_ai_backend_001",
                "status": "active",
                "record": {
                    "job_fit_report_id": "fit_ai_backend_001",
                    "jd_analysis_id": "jd_ai_backend_001",
                    "resume_profile_id": "resume_profile_alpha",
                    "source_artifact_id": "artifact_jd_source",
                    "report_artifact_id": "artifact_fit_report",
                },
            },
        ),
        (
            "evt_application",
            "career_application_create",
            {
                "record_type": "career_application",
                "record_id": "application_ai_backend",
                "status": "active",
                "record": {
                    "application_id": "application_ai_backend",
                    "resume_profile_id": "resume_profile_alpha",
                    "jd_analysis_id": "jd_ai_backend_001",
                    "job_fit_report_id": "fit_ai_backend_001",
                },
            },
        ),
    ]:
        session_repo.append_event(
            session_id,
            EventRecord(
                event_id=event_id,
                session_id=session_id,
                type="tool_result",
                payload={
                    "tool_name": tool_name,
                    "success": True,
                    "content": json.dumps(content, ensure_ascii=False),
                    "tool_call_id": f"call_{event_id}",
                },
                created_at=now,
                agent_id="agent_main",
                run_id=f"run_{session_id}",
            ),
        )

    output = runtime.run(
        AgentRunInput(
            session_id=session_id,
            user_message="继续生成定制简历",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context(session_id),
        )
    )
    usage_event = next(event for event in session_repo.list_events(session_id) if event.type == "llm_usage")

    assert output.answer == "done"
    assert model.calls == 3
    assert model.tool_names_by_call[0] == {"career_resume_version_create"}
    assert "career_application_get" not in model.tool_names_by_call[0]
    assert "tool_search" not in model.tool_names_by_call[0]
    assert usage_event.payload["tool_disclosure_mode"] == "search"
    assert usage_event.payload["visible_tool_count"] == 1
    assert usage_event.payload["visible_tool_names"] == ["career_resume_version_create"]
    assert "tool_search" not in usage_event.payload["visible_tool_names"]


def test_runtime_tool_search_without_runtime_plan_keeps_pending_required_tool(tmp_path: Path) -> None:
    class StaticTool:
        def __init__(self, name: str, content: str = "{}") -> None:
            self._name = name
            self._content = content

        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name=self._name,
                description=f"{self._name} description",
                parameters_schema={"type": "object", "properties": {}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(tool_name=self._name, success=True, content=self._content)

    class RuntimePlanPreservationModelClient:
        def __init__(self) -> None:
            self.calls = 0
            self.tool_names_by_call: list[set[str]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = system_prompt
            self.calls += 1
            self.tool_names_by_call.append({item["function"]["name"] for item in tools})
            if self.calls == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="tool_search",
                            arguments={"query": "读取 artifact 辅助生成简历"},
                        )
                    ],
                )
            if self.calls == 2:
                return ModelResponse(content="我已经可以直接回答了。", tool_calls=[])
            if self.calls == 3:
                assert any("运行时守卫" in str(message.get("content", "")) for message in messages)
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_resume_version_create",
                            arguments={"base_resume_profile_id": "resume_profile_alpha", "title": "定制简历"},
                        )
                    ],
                )
            return ModelResponse(content="done", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = RuntimePlanPreservationModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[
            StaticTool("tool_search"),
            StaticTool("career_application_get"),
            StaticTool("career_resume_profile_get"),
            StaticTool("career_jd_analysis_get"),
            StaticTool("career_job_fit_report_get"),
            StaticTool(
                "career_resume_version_create",
                content='{"record_type":"resume_version","record_id":"resume_version_alpha"}',
            ),
        ],
        tool_schema_disclosure_mode="search",
    )
    session_id = "sess_runtime_plan_preserve"
    session_repo.create_session(session_id)
    now = datetime.now(UTC)
    for event_id, tool_name, content in [
        (
            "evt_resume_profile",
            "career_resume_profile_save",
            {
                "record_type": "resume_profile",
                "record_id": "resume_profile_alpha",
                "status": "active",
                "record": {
                    "resume_profile_id": "resume_profile_alpha",
                    "source_artifact_id": "artifact_resume_source",
                },
            },
        ),
        (
            "evt_fit_report",
            "career_job_fit_report_save",
            {
                "record_type": "job_fit_report",
                "record_id": "fit_ai_backend_001",
                "status": "active",
                "record": {
                    "job_fit_report_id": "fit_ai_backend_001",
                    "jd_analysis_id": "jd_ai_backend_001",
                    "resume_profile_id": "resume_profile_alpha",
                    "source_artifact_id": "artifact_jd_source",
                    "report_artifact_id": "artifact_fit_report",
                },
            },
        ),
        (
            "evt_application",
            "career_application_create",
            {
                "record_type": "career_application",
                "record_id": "application_ai_backend",
                "status": "active",
                "record": {
                    "application_id": "application_ai_backend",
                    "resume_profile_id": "resume_profile_alpha",
                    "jd_analysis_id": "jd_ai_backend_001",
                    "job_fit_report_id": "fit_ai_backend_001",
                },
            },
        ),
    ]:
        session_repo.append_event(
            session_id,
            EventRecord(
                event_id=event_id,
                session_id=session_id,
                type="tool_result",
                payload={
                    "tool_name": tool_name,
                    "success": True,
                    "content": json.dumps(content, ensure_ascii=False),
                    "tool_call_id": f"call_{event_id}",
                },
                created_at=now,
                agent_id="agent_main",
                run_id=f"run_{session_id}",
            ),
        )

    output = runtime.run(
        AgentRunInput(
            session_id=session_id,
            user_message="继续生成定制简历",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context(session_id),
        )
    )

    assert output.answer == "done"
    assert model.calls == 4
    assert "career_resume_version_create" in model.tool_names_by_call[0]
    decisions = [
        event
        for event in session_repo.list_events(session_id)
        if event.type == "workflow_runtime_decision"
    ]
    assert any(
        event.payload.get("reason") == "premature_final_answer_with_pending_runtime_tools"
        for event in decisions
    )


def test_runtime_keeps_prerequisite_next_allowed_tool_visible_with_required_tool(tmp_path: Path) -> None:
    class StaticTool:
        def __init__(self, name: str, content: str = "{}") -> None:
            self._name = name
            self._content = content

        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name=self._name,
                description=f"{self._name} description",
                parameters_schema={"type": "object", "properties": {}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(tool_name=self._name, success=True, content=self._content)

    runtime_plan_search_result = {
        "runtime_plan_applied": True,
        "runtime_plan_phase": "resume_diagnosis",
        "runtime_next_action": "ResumeProfile 已存在；只读取画像并 merge 职业画像。",
        "runtime_next_allowed_tools": ["career_resume_profile_get", "career_profile_merge"],
        "runtime_missing_outputs": ["career_profile"],
        "runtime_known_refs": {
            "resume_profile_id": "resume_profile_alpha",
            "diagnosis_artifact_id": "artifact_diagnosis",
        },
        "runtime_final_answer_ready": False,
        "runtime_discouraged_tools": ["delegate_agents", "session_read_artifact", "session_list_artifacts"],
        "revealed_tool_names": ["career_resume_profile_get", "career_profile_merge"],
    }

    class RuntimePlanPrerequisiteModelClient:
        def __init__(self) -> None:
            self.calls = 0
            self.tool_names_by_call: list[set[str]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            self.tool_names_by_call.append(tool_names)
            if self.calls == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="tool_search", arguments={"query": "更新职业画像"})],
                )
            if self.calls == 2:
                assert {"career_resume_profile_get", "career_profile_merge"}.issubset(tool_names)
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_resume_profile_get",
                            arguments={"resume_profile_id": "resume_profile_alpha"},
                        )
                    ],
                )
            if self.calls == 3:
                assert {"career_resume_profile_get", "career_profile_merge"}.issubset(tool_names)
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_profile_merge",
                            arguments={
                                "career_profile_id": "career_profile_default",
                                "updates": {"skills": ["Python"]},
                            },
                        )
                    ],
                )
            return ModelResponse(content="职业画像已更新。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = RuntimePlanPrerequisiteModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[
            StaticTool("tool_search", content=json.dumps(runtime_plan_search_result, ensure_ascii=False)),
            StaticTool(
                "career_resume_profile_get",
                content='{"record_type":"resume_profile","record_id":"resume_profile_alpha"}',
            ),
            StaticTool(
                "career_profile_merge",
                content='{"record_type":"career_profile","record_id":"career_profile_default"}',
            ),
        ],
        tool_schema_disclosure_mode="search",
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_runtime_plan_prerequisite_visible",
            user_message="更新职业画像。",
            skill_names=["base", "tools"],
            max_tool_rounds=4,
            context=_context("sess_runtime_plan_prerequisite_visible"),
        )
    )

    assert output.answer == "职业画像已更新。"
    assert [call.name for call in output.tool_calls] == [
        "tool_search",
        "career_resume_profile_get",
        "career_profile_merge",
    ]
    decisions = [
        event.payload
        for event in session_repo.list_events("sess_runtime_plan_prerequisite_visible")
        if event.type == "workflow_runtime_decision"
    ]
    assert not any(item.get("reason") == "hidden_tools_suppressed_required_tool_visible" for item in decisions)


def test_runtime_search_disclosure_does_not_charge_schema_search_against_tool_round_limit(tmp_path: Path) -> None:
    class RetrievalTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="retrieval_context_pack",
                description="Build context from saved records.",
                parameters_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="retrieval_context_pack",
                success=True,
                content=json.dumps({"context_pack": {"hits": []}}, ensure_ascii=False),
            )

    class SearchBudgetModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            if self.calls == 1:
                assert tool_names == {"tool_search", "memory_write"}
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="tool_search",
                            arguments={"query": "召回之前保存过的求职项目"},
                            tool_call_id="call_tool_search_budget",
                        )
                    ],
                )
            if self.calls == 2:
                assert "retrieval_context_pack" in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="retrieval_context_pack",
                            arguments={"query": "星河智能"},
                            tool_call_id="call_retrieval_budget",
                        )
                    ],
                )
            return ModelResponse(content="done", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = SearchBudgetModelClient()
    runtime, _, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[RetrievalTool()],
        register_tool_search=True,
        tool_schema_disclosure_mode="search",
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_tool_search_budget",
            user_message="根据之前保存过的内容帮我准备面试。",
            skill_names=["base", "tools"],
            max_tool_rounds=1,
            context=_context("sess_tool_search_budget"),
        )
    )

    assert output.answer == "done"
    assert model.calls == 3


def test_runtime_search_disclosure_resets_schema_budget_after_business_tool(tmp_path: Path) -> None:
    class RetrievalTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="retrieval_context_pack",
                description="Build context from saved records.",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="retrieval_context_pack",
                success=True,
                content=json.dumps({"context_pack": {"hits": []}}, ensure_ascii=False),
            )

    class InterleavedSearchModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            if self.calls in {1, 3, 5, 7}:
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="tool_search",
                            arguments={"query": f"检索能力 {self.calls}"},
                            tool_call_id=f"call_search_{self.calls}",
                        )
                    ],
                )
            if self.calls in {2, 4, 6, 8}:
                assert "retrieval_context_pack" in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="retrieval_context_pack",
                            arguments={"query": f"查询 {self.calls}"},
                            tool_call_id=f"call_retrieval_{self.calls}",
                        )
                    ],
                )
            return ModelResponse(content="done", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = InterleavedSearchModelClient()
    runtime, _, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[RetrievalTool()],
        register_tool_search=True,
        tool_schema_disclosure_mode="search",
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_interleaved_tool_search",
            user_message="分阶段检索并读取上下文。",
            skill_names=["base", "tools"],
            max_tool_rounds=4,
            context=_context("sess_interleaved_tool_search"),
        )
    )

    assert output.answer == "done"
    assert model.calls == 9


def test_runtime_search_disclosure_rejects_unrevealed_tool_call(tmp_path: Path) -> None:
    class RetrievalTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="retrieval_context_pack",
                description="Build context from saved records.",
                parameters_schema={"type": "object", "properties": {}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(tool_name="retrieval_context_pack", success=True, content='{"ok": true}')

    class HiddenCallModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, tools)
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="retrieval_context_pack",
                            arguments={},
                            tool_call_id="call_hidden_1",
                        )
                    ],
                )
            tool_message = next(message for message in messages if message.get("role") == "tool")
            assert "tool_schema_not_revealed" in str(tool_message["content"])
            return ModelResponse(content="需要先搜索可用工具。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = HiddenCallModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[RetrievalTool()],
        register_tool_search=True,
        tool_schema_disclosure_mode="search",
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_hidden_tool_call",
            user_message="直接调用隐藏工具。",
            skill_names=["base", "tools"],
            max_tool_rounds=2,
            context=_context("sess_hidden_tool_call"),
        )
    )
    tool_results = [event for event in session_repo.list_events("sess_hidden_tool_call") if event.type == "tool_result"]

    assert output.answer == "需要先搜索可用工具。"
    assert tool_results[0].payload["success"] is True
    assert "tool_schema_not_revealed" in tool_results[0].payload["content"]


def test_runtime_recovers_when_final_answer_is_text_tool_invocation(tmp_path: Path) -> None:
    class TextToolInvocationModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    content='<tool_invocation name="career_resume_profile_get" arguments={"resume_profile_id":"x"} />',
                    tool_calls=[],
                )
            assert tools == []
            return ModelResponse(content="已完成并汇总结果。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = TextToolInvocationModelClient()
    runtime, session_repo, _ = _build_runtime(tmp_path, model)

    output = runtime.run(
        AgentRunInput(
            session_id="sess_text_tool_invocation",
            user_message="诊断简历。",
            skill_names=["base"],
            max_tool_rounds=1,
            context=_context("sess_text_tool_invocation"),
        )
    )

    assert output.answer == "已完成并汇总结果。"
    assert model.calls == 2
    usage_events = [event for event in session_repo.list_events("sess_text_tool_invocation") if event.type == "llm_usage"]
    assert usage_events[-1].payload["phase"] == "final_answer_recovery"


def test_runtime_recovers_when_final_answer_is_xml_tool_call_markup(tmp_path: Path) -> None:
    model = SequenceModelClient(
        responses=[
            ModelResponse(
                content=(
                    "<tool_call>\n"
                    "<function=career_application_get>\n"
                    "<parameter=application_id>application_alpha</parameter>\n"
                    "</function>\n"
                    "</tool_call>"
                ),
                tool_calls=[],
            ),
            ModelResponse(content="已完成并汇总结果。", tool_calls=[]),
        ]
    )
    runtime, session_repo, _ = _build_runtime(tmp_path, model)

    output = runtime.run(
        AgentRunInput(
            session_id="sess_xml_tool_call_answer",
            user_message="给我最终结果。",
            skill_names=["base"],
            max_tool_rounds=1,
            context=_context("sess_xml_tool_call_answer"),
        )
    )

    assert output.answer == "已完成并汇总结果。"
    rejected = [event.payload for event in session_repo.list_events("sess_xml_tool_call_answer") if event.type == "assistant_answer_rejected"]
    assert any(item["reason"] == "tool_call_markup" for item in rejected)


def test_runtime_recovers_when_final_answer_is_unusable_refusal(tmp_path: Path) -> None:
    model = SequenceModelClient(
        responses=[
            ModelResponse(content="我无法处理你的请求。", tool_calls=[]),
            ModelResponse(content="已完成并汇总结果。", tool_calls=[]),
        ]
    )
    runtime, session_repo, _ = _build_runtime(tmp_path, model)

    output = runtime.run(
        AgentRunInput(
            session_id="sess_unusable_refusal_answer",
            user_message="给我最终结果。",
            skill_names=["base"],
            max_tool_rounds=1,
            context=_context("sess_unusable_refusal_answer"),
        )
    )

    assert output.answer == "已完成并汇总结果。"
    rejected = [
        event.payload
        for event in session_repo.list_events("sess_unusable_refusal_answer")
        if event.type == "assistant_answer_rejected"
    ]
    assert any(item["reason"] == "weak_completed_workflow_answer" for item in rejected)


def test_runtime_terminal_workflow_result_fallback_uses_completed_refs(tmp_path: Path) -> None:
    class CompletedWorkflowTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="tool_search",
                description="Search tools.",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="tool_search",
                success=True,
                content=json.dumps(
                    {
                        "workflow_runtime_result": True,
                        "policy": "block",
                        "terminal": True,
                        "stage": "resume_diagnosis",
                        "stage_status": "completed",
                        "next_action": "ResumeProfile 和 CareerProfile 已完成；不要继续读工具，直接答复用户。",
                        "missing_outputs": [],
                        "completed_refs": {
                            "resume_profile_id": "resume_profile_alpha",
                            "career_profile_id": "career_profile_default",
                            "diagnosis_artifact_id": "artifact_diagnosis",
                        },
                        "next_allowed_tools": [],
                    },
                    ensure_ascii=False,
                ),
            )

    class CompletedWorkflowBadRecoveryModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="tool_search", arguments={"query": "read artifact"})],
                )
            assert tools == []
            return ModelResponse(
                content=(
                    "<tool_call>\n"
                    "<function=session_read_artifact>\n"
                    "<parameter=artifact_id>artifact_diagnosis</parameter>\n"
                    "</function>\n"
                    "</tool_call>"
                ),
                tool_calls=[],
            )

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = CompletedWorkflowBadRecoveryModelClient()
    runtime, session_repo, _ = _build_runtime(tmp_path, model, extra_tools=[CompletedWorkflowTool()])

    output = runtime.run(
        AgentRunInput(
            session_id="sess_terminal_workflow_completed_refs",
            user_message="诊断简历。",
            skill_names=["base", "tools"],
            max_tool_rounds=2,
            context=_context("sess_terminal_workflow_completed_refs"),
        )
    )

    assert "简历诊断与画像沉淀已完成" in output.answer
    assert "ResumeProfile: `resume_profile_alpha`" in output.answer
    assert "CareerProfile: `career_profile_default`" in output.answer
    assert "简历诊断报告: `artifact_diagnosis`" in output.answer
    assert "当前没有生成可用的最终答复" not in output.answer
    assert model.calls == 3
    events = session_repo.list_events("sess_terminal_workflow_completed_refs")
    assert any(
        event.type == "workflow_runtime_decision" and event.payload.get("reason") == "workflow_final_answer_ready"
        for event in events
    )
    rejected = [event.payload for event in events if event.type == "assistant_answer_rejected"]
    assert any(item["reason"] == "tool_call_markup_after_recovery" for item in rejected)


def test_runtime_does_not_accept_final_answer_when_runtime_plan_has_pending_tool(tmp_path: Path) -> None:
    class RuntimePlanSearchTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="tool_search",
                description="Search tools.",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="tool_search",
                success=True,
                content=json.dumps(
                    {
                        "runtime_plan_applied": True,
                        "runtime_plan_phase": "jd_fit",
                        "runtime_final_answer_ready": False,
                        "runtime_next_action": "只创建 CareerApplication 串联本次求职项目。",
                        "runtime_next_allowed_tools": ["career_application_create"],
                        "runtime_missing_outputs": ["career_application"],
                        "runtime_known_refs": {
                            "resume_profile_id": "resume_profile_alpha",
                            "jd_analysis_id": "jd_alpha",
                            "job_fit_report_id": "fit_alpha",
                        },
                        "revealed_tool_names": ["career_application_create"],
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationCreateTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_create",
                description="Create career application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_application_create",
                success=True,
                content=json.dumps({"record_type": "career_application", "record_id": "application_alpha"}),
            )

    class PrematureFinalModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = system_prompt
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            if self.calls == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="tool_search", arguments={"query": "创建求职项目"})],
                )
            if self.calls == 2:
                assert "career_application_create" in tool_names
                return ModelResponse(content="匹配报告已完成。", tool_calls=[])
            if self.calls == 3:
                assert any("运行时守卫" in str(message.get("content", "")) for message in messages)
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_application_create",
                            arguments={"application_id": "application_alpha"},
                        )
                    ],
                )
            return ModelResponse(content="已创建求职项目。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = PrematureFinalModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[RuntimePlanSearchTool(), ApplicationCreateTool()],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_premature_runtime_plan",
            user_message="创建求职项目",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_premature_runtime_plan"),
        )
    )

    assert output.answer == "已创建求职项目。"
    assert model.calls == 4
    tool_calls = [event.payload["name"] for event in session_repo.list_events("sess_premature_runtime_plan") if event.type == "tool_call"]
    assert tool_calls == ["tool_search", "career_application_create"]
    decisions = [
        event.payload
        for event in session_repo.list_events("sess_premature_runtime_plan")
        if event.type == "workflow_runtime_decision"
    ]
    assert decisions[0]["reason"] == "premature_final_answer_with_pending_runtime_tools"


def test_runtime_does_not_execute_extra_tool_search_when_required_tool_is_visible(tmp_path: Path) -> None:
    class RuntimePlanSearchTool:
        def __init__(self) -> None:
            self.calls = 0

        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="tool_search",
                description="Search tools.",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            self.calls += 1
            return ToolExecutionResult(
                tool_name="tool_search",
                success=True,
                content=json.dumps(
                    {
                        "runtime_plan_applied": True,
                        "runtime_plan_phase": "resume_version",
                        "runtime_final_answer_ready": False,
                        "runtime_next_action": "只调用 career_resume_version_create 生成定制简历。",
                        "runtime_next_allowed_tools": ["career_resume_version_create"],
                        "runtime_missing_outputs": ["resume_version"],
                        "revealed_tool_names": ["career_resume_version_create"],
                    },
                    ensure_ascii=False,
                ),
            )

    class ResumeVersionTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_resume_version_create",
                description="Create resume version.",
                parameters_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_resume_version_create",
                success=True,
                content=json.dumps({"ok": True}, ensure_ascii=False),
            )

    class RepeatedSearchModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = system_prompt
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            if self.calls == 1:
                return ModelResponse(content="", tool_calls=[ToolCall(name="tool_search", arguments={"query": "定制简历"})])
            if self.calls == 2:
                assert "career_resume_version_create" in tool_names
                assert "tool_search" not in tool_names
                assert "memory_write" not in tool_names
                assert tool_names == {"career_resume_version_create"}
                return ModelResponse(content="", tool_calls=[ToolCall(name="tool_search", arguments={"query": "再搜一次"})])
            if self.calls == 3:
                assert tool_names == {"career_resume_version_create"}
                assert any("运行时守卫" in str(message.get("content", "")) for message in messages)
                assert any("本轮没有工具搜索阶段" in str(message.get("content", "")) for message in messages)
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="career_resume_version_create", arguments={"title": "定制简历"})],
                )
            return ModelResponse(content="已生成定制简历。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    search_tool = RuntimePlanSearchTool()
    model = RepeatedSearchModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[search_tool, ResumeVersionTool()],
        tool_schema_disclosure_mode="search",
        tool_schema_always_visible=["tool_search", "memory_write"],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_schema_search_pending_runtime",
            user_message="生成定制简历",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_schema_search_pending_runtime"),
        )
    )

    assert output.answer == "已生成定制简历。"
    assert search_tool.calls == 1
    tool_calls = [
        event.payload["name"]
        for event in session_repo.list_events("sess_schema_search_pending_runtime")
        if event.type == "tool_call"
    ]
    assert tool_calls == ["tool_search", "career_resume_version_create"]
    decisions = [
        event.payload
        for event in session_repo.list_events("sess_schema_search_pending_runtime")
        if event.type == "workflow_runtime_decision"
    ]
    assert decisions[0]["reason"] == "schema_search_suppressed_required_tool_visible"


def test_runtime_requires_application_merge_after_resume_version_success(tmp_path: Path) -> None:
    class ResumeVersionTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_resume_version_create",
                description="Create resume version.",
                parameters_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_resume_version_create",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "resume_version",
                        "record_id": "resume_version_alpha",
                        "record": {
                            "resume_version_id": "resume_version_alpha",
                            "artifact_id": "artifact_resume_version_alpha",
                        },
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationMergeTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_merge",
                description="Merge application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_application_merge",
                success=True,
                content=json.dumps({"record_type": "career_application", "record_id": "application_alpha"}),
            )

    class ResumeVersionThenPrematureModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = system_prompt
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            if self.calls == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="career_resume_version_create", arguments={"title": "定制简历"})],
                )
            if self.calls == 2:
                assert "career_application_merge" in tool_names
                assert "tool_search" not in tool_names
                return ModelResponse(content="定制简历已生成。", tool_calls=[])
            if self.calls == 3:
                assert any("career_application_merge" in str(message.get("content", "")) for message in messages)
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="career_application_merge", arguments={"application_id": "application_alpha"})],
                )
            return ModelResponse(content="定制简历已生成并关联项目。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = ResumeVersionThenPrematureModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[ResumeVersionTool(), ApplicationMergeTool()],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_resume_version_then_merge",
            user_message="生成定制简历",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_resume_version_then_merge"),
        )
    )

    assert output.answer == "定制简历已生成并关联项目。"
    assert model.calls == 4
    tool_calls = [
        event.payload["name"]
        for event in session_repo.list_events("sess_resume_version_then_merge")
        if event.type == "tool_call"
    ]
    assert tool_calls == ["career_resume_version_create", "career_application_merge"]
    decisions = [
        event.payload
        for event in session_repo.list_events("sess_resume_version_then_merge")
        if event.type == "workflow_runtime_decision"
    ]
    assert decisions[0]["reason"] == "premature_final_answer_with_pending_runtime_tools"


def test_runtime_auto_executes_strict_required_tool_when_hidden_read_is_called(tmp_path: Path) -> None:
    class ResumeVersionTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_resume_version_create",
                description="Create resume version.",
                parameters_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_resume_version_create",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "resume_version",
                        "record_id": "resume_version_alpha",
                        "application_id": "application_alpha",
                        "record": {
                            "resume_version_id": "resume_version_alpha",
                            "artifact_id": "artifact_resume_version_alpha",
                        },
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationMergeTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_merge",
                description="Merge application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = context
            assert arguments["application_id"] == "application_alpha"
            assert arguments["updates"] == {"resume_version_ids": ["resume_version_alpha"]}
            return ToolExecutionResult(
                tool_name="career_application_merge",
                success=True,
                content=json.dumps({"record_type": "career_application", "record_id": "application_alpha"}),
            )

    class HiddenReadInsteadOfMergeModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            if self.calls == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="career_resume_version_create", arguments={"title": "定制简历"})],
                )
            if self.calls == 2:
                assert tool_names == {"career_application_merge"}
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_application_get",
                            arguments={"application_id": "application_alpha"},
                            tool_call_id="call_hidden_get",
                        )
                    ],
                )
            return ModelResponse(content="定制简历已生成并关联项目。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = HiddenReadInsteadOfMergeModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[ResumeVersionTool(), ApplicationMergeTool()],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_strict_auto_required_tool",
            user_message="生成定制简历",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_strict_auto_required_tool"),
        )
    )

    assert output.answer == "定制简历已生成并关联项目。"
    events = session_repo.list_events("sess_strict_auto_required_tool")
    tool_results = [event.payload for event in events if event.type == "tool_result"]
    assert [item["tool_name"] for item in tool_results] == [
        "career_resume_version_create",
        "career_application_merge",
    ]
    assert not any("tool_schema_not_revealed" in item["content"] for item in tool_results)
    decisions = [event.payload for event in events if event.type == "workflow_runtime_decision"]
    assert any(item["reason"] == "strict_hidden_tool_replaced_with_required_tool" for item in decisions)
    assert any(item["reason"] == "workflow_final_answer_ready" for item in decisions)


def test_runtime_deterministic_final_fallback_lists_completed_refs(tmp_path: Path) -> None:
    class ResumeVersionTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_resume_version_create",
                description="Create resume version.",
                parameters_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_resume_version_create",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "resume_version",
                        "record_id": "resume_version_alpha",
                        "application_id": "application_alpha",
                        "record": {
                            "resume_version_id": "resume_version_alpha",
                            "artifact_id": "artifact_resume_version_alpha",
                        },
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationMergeTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_merge",
                description="Merge application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_application_merge",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "career_application",
                        "record_id": "application_alpha",
                        "resume_version_id": "resume_version_alpha",
                    },
                    ensure_ascii=False,
                ),
            )

    class EmptyRecoveryModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="career_resume_version_create", arguments={"title": "定制简历"})],
                )
            if self.calls == 2:
                assert {item["function"]["name"] for item in tools} == {"career_application_merge"}
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_application_merge",
                            arguments={
                                "application_id": "application_alpha",
                                "updates": {"resume_version_ids": ["resume_version_alpha"]},
                            },
                        )
                    ],
                )
            assert tools == []
            return ModelResponse(content="", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = EmptyRecoveryModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[ResumeVersionTool(), ApplicationMergeTool()],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_deterministic_completed_fallback",
            user_message="生成定制简历",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_deterministic_completed_fallback"),
        )
    )

    assert "定制简历版本生成已完成" in output.answer
    assert "ResumeVersion: `resume_version_alpha`" in output.answer
    assert "CareerApplication: `application_alpha`" in output.answer
    assert "模型没有生成可用总结" not in output.answer
    assert model.calls == 3
    decisions = [
        event.payload
        for event in session_repo.list_events("sess_deterministic_completed_fallback")
        if event.type == "workflow_runtime_decision"
    ]
    assert any(item["reason"] == "workflow_final_answer_ready" for item in decisions)


def test_runtime_rejects_weak_answer_after_workflow_is_complete(tmp_path: Path) -> None:
    class ResumeVersionTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_resume_version_create",
                description="Create resume version.",
                parameters_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_resume_version_create",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "resume_version",
                        "record_id": "resume_version_alpha",
                        "application_id": "application_alpha",
                        "record": {
                            "resume_version_id": "resume_version_alpha",
                            "artifact_id": "artifact_resume_version_alpha",
                        },
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationMergeTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_merge",
                description="Merge application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_application_merge",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "career_application",
                        "record_id": "application_alpha",
                        "resume_version_id": "resume_version_alpha",
                    },
                    ensure_ascii=False,
                ),
            )

    class WeakCompletedWorkflowModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="career_resume_version_create", arguments={"title": "定制简历"})],
                )
            if self.calls == 2:
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_application_merge",
                            arguments={
                                "application_id": "application_alpha",
                                "updates": {"resume_version_ids": ["resume_version_alpha"]},
                            },
                        )
                    ],
                )
            if self.calls == 3:
                assert tools == []
                return ModelResponse(
                    content="当前 workflow 守卫限制了我的直接工具调用，我需要委派子任务来完成定制简历的创建和合并。",
                    tool_calls=[],
                )
            assert tools == []
            return ModelResponse(content="定制简历已生成并关联项目。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = WeakCompletedWorkflowModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[ResumeVersionTool(), ApplicationMergeTool()],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_weak_completed_workflow_answer",
            user_message="生成定制简历",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_weak_completed_workflow_answer"),
        )
    )

    assert output.answer == "定制简历已生成并关联项目。"
    rejected = [
        event.payload
        for event in session_repo.list_events("sess_weak_completed_workflow_answer")
        if event.type == "assistant_answer_rejected"
    ]
    assert any(item["reason"] == "weak_completed_workflow_answer" for item in rejected)


def test_runtime_suppresses_hidden_read_when_required_tool_is_visible(tmp_path: Path) -> None:
    class RuntimePlanSearchTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="tool_search",
                description="Search tools.",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="tool_search",
                success=True,
                content=json.dumps(
                    {
                        "runtime_plan_applied": True,
                        "runtime_plan_phase": "resume_version",
                        "runtime_next_action": "先读取 CareerApplication，再创建 ResumeVersion。",
                        "runtime_next_allowed_tools": ["career_application_get"],
                        "required_tools": ["career_application_get"],
                        "runtime_missing_outputs": ["career_application_read", "resume_version"],
                        "runtime_known_refs": {
                            "application_id": "application_alpha",
                            "resume_profile_id": "resume_profile_alpha",
                            "jd_analysis_id": "jd_alpha",
                            "job_fit_report_id": "fit_alpha",
                        },
                        "revealed_tool_names": ["career_application_get"],
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationGetTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_get",
                description="Get application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_application_get",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "career_application",
                        "record_id": "application_alpha",
                        "resume_profile_id": "resume_profile_alpha",
                        "jd_analysis_id": "jd_alpha",
                        "job_fit_report_id": "fit_alpha",
                    },
                    ensure_ascii=False,
                ),
            )

    class ResumeVersionTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_resume_version_create",
                description="Create resume version.",
                parameters_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_resume_version_create",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "resume_version",
                        "record_id": "resume_version_alpha",
                        "application_id": "application_alpha",
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationMergeTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_merge",
                description="Merge application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_application_merge",
                success=True,
                content=json.dumps({"record_type": "career_application", "record_id": "application_alpha"}),
            )

    class HiddenReadModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = system_prompt
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            if self.calls == 1:
                return ModelResponse(content="", tool_calls=[ToolCall(name="tool_search", arguments={"query": "定制简历"})])
            if self.calls == 2:
                assert tool_names == {"career_application_get"}
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_application_get",
                            arguments={"application_id": "application_alpha"},
                            tool_call_id="call_get_first",
                        )
                    ],
                )
            if self.calls == 3:
                assert tool_names == {"career_resume_version_create"}
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_application_get",
                            arguments={"application_id": "application_alpha"},
                            tool_call_id="call_get_hidden",
                        )
                    ],
                )
            if self.calls == 4:
                assert tool_names == {"career_application_merge"}
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_application_merge",
                            arguments={
                                "application_id": "application_alpha",
                                "updates": {"resume_version_ids": ["resume_version_alpha"]},
                            },
                        )
                    ],
                )
            assert tools == []
            return ModelResponse(content="定制简历已生成并关联项目。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = HiddenReadModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[RuntimePlanSearchTool(), ApplicationGetTool(), ResumeVersionTool(), ApplicationMergeTool()],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_hidden_read_suppressed_required_visible",
            user_message="生成定制简历",
            skill_names=["base", "tools"],
            max_tool_rounds=5,
            context=_context("sess_hidden_read_suppressed_required_visible"),
        )
    )

    assert output.answer == "定制简历已生成并关联项目。"
    events = session_repo.list_events("sess_hidden_read_suppressed_required_visible")
    tool_calls = [event.payload["name"] for event in events if event.type == "tool_call"]
    assert tool_calls == [
        "tool_search",
        "career_application_get",
        "career_application_get",
        "career_resume_version_create",
        "career_application_merge",
    ]
    assert not any(
        event.type == "tool_result" and "tool_hidden_by_runtime_plan" in event.payload.get("content", "")
        for event in events
    )
    decisions = [event.payload for event in events if event.type == "workflow_runtime_decision"]
    assert any(item["reason"] == "strict_hidden_tool_replaced_with_required_tool" for item in decisions)


def test_runtime_auto_executes_resume_version_safe_fallback_on_premature_answer(tmp_path: Path) -> None:
    class RuntimePlanSearchTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="tool_search",
                description="Search tools.",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="tool_search",
                success=True,
                content=json.dumps(
                    {
                        "runtime_plan_applied": True,
                        "runtime_plan_phase": "resume_version",
                        "runtime_next_action": "先读取 CareerApplication，再创建 ResumeVersion。",
                        "runtime_next_allowed_tools": ["career_application_get"],
                        "required_tools": ["career_application_get"],
                        "runtime_missing_outputs": ["career_application_read", "resume_version"],
                        "runtime_known_refs": {
                            "application_id": "application_alpha",
                            "resume_profile_id": "resume_profile_alpha",
                            "jd_analysis_id": "jd_alpha",
                            "job_fit_report_id": "fit_alpha",
                        },
                        "revealed_tool_names": ["career_application_get"],
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationGetTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_get",
                description="Get application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_application_get",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "career_application",
                        "record_id": "application_alpha",
                        "resume_profile_id": "resume_profile_alpha",
                        "jd_analysis_id": "jd_alpha",
                        "job_fit_report_id": "fit_alpha",
                    },
                    ensure_ascii=False,
                ),
            )

    class ResumeVersionTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_resume_version_create",
                description="Create resume version.",
                parameters_schema={
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "use_safe_fallback": {"type": "boolean"}},
                },
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = context
            assert arguments["base_resume_profile_id"] == "resume_profile_alpha"
            assert arguments["target_jd_analysis_id"] == "jd_alpha"
            assert arguments["use_safe_fallback"] is True
            return ToolExecutionResult(
                tool_name="career_resume_version_create",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "resume_version",
                        "record_id": "resume_version_alpha",
                        "record": {
                            "resume_version_id": "resume_version_alpha",
                            "artifact_id": "artifact_resume_version_alpha",
                        },
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationMergeTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_merge",
                description="Merge application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = context
            assert arguments["application_id"] == "application_alpha"
            assert arguments["updates"] == {"resume_version_ids": ["resume_version_alpha"]}
            return ToolExecutionResult(
                tool_name="career_application_merge",
                success=True,
                content=json.dumps({"record_type": "career_application", "record_id": "application_alpha"}),
            )

    class PrematureAnswerModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            if self.calls == 1:
                return ModelResponse(content="", tool_calls=[ToolCall(name="tool_search", arguments={"query": "定制简历"})])
            if self.calls == 2:
                assert tool_names == {"career_application_get"}
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="career_application_get", arguments={"application_id": "application_alpha"})],
                )
            if self.calls == 3:
                assert tool_names == {"career_resume_version_create"}
                return ModelResponse(content="定制简历已生成。", tool_calls=[])
            if self.calls == 4:
                assert tool_names == {"career_resume_version_create"}
                assert any("运行时守卫" in str(message.get("content", "")) for message in messages)
                return ModelResponse(content="定制简历已生成。", tool_calls=[])
            if self.calls == 5:
                assert tool_names == {"career_application_merge"}
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_application_merge",
                            arguments={
                                "application_id": "application_alpha",
                                "updates": {"resume_version_ids": ["resume_version_alpha"]},
                            },
                        )
                    ],
                )
            assert tools == []
            return ModelResponse(content="定制简历已生成并关联项目。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = PrematureAnswerModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[RuntimePlanSearchTool(), ApplicationGetTool(), ResumeVersionTool(), ApplicationMergeTool()],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_resume_version_auto_safe_fallback",
            user_message="生成定制简历",
            skill_names=["base", "tools"],
            max_tool_rounds=5,
            context=_context("sess_resume_version_auto_safe_fallback"),
        )
    )

    assert output.answer == "定制简历已生成并关联项目。"
    events = session_repo.list_events("sess_resume_version_auto_safe_fallback")
    tool_results = [event.payload["tool_name"] for event in events if event.type == "tool_result"]
    assert tool_results == [
        "tool_search",
        "career_application_get",
        "career_resume_version_create",
        "career_application_merge",
    ]
    decisions = [event.payload for event in events if event.type == "workflow_runtime_decision"]
    assert any(item["reason"] == "strict_premature_answer_replaced_with_required_tool" for item in decisions)


def test_runtime_executor_runs_resume_version_project_action_without_tool_loop(tmp_path: Path) -> None:
    class ApplicationGetTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_get",
                description="Get application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = context
            assert arguments == {"application_id": "application_alpha"}
            return ToolExecutionResult(
                tool_name="career_application_get",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "career_application",
                        "record_id": "application_alpha",
                        "record": {
                            "application_id": "application_alpha",
                            "resume_profile_id": "resume_profile_alpha",
                            "jd_analysis_id": "jd_alpha",
                            "job_fit_report_id": "fit_alpha",
                        },
                    },
                    ensure_ascii=False,
                ),
            )

    class ResumeVersionTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_resume_version_create",
                description="Create resume version.",
                parameters_schema={"type": "object", "properties": {"content": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = context
            assert arguments["base_resume_profile_id"] == "resume_profile_alpha"
            assert arguments["target_jd_analysis_id"] == "jd_alpha"
            assert arguments["content"] == "# 张三\n\nPython FastAPI RAG 项目经验。"
            assert arguments["evidence_refs"] == [
                "application_alpha",
                "resume_profile_alpha",
                "jd_alpha",
                "fit_alpha",
            ]
            assert "use_safe_fallback" not in arguments
            return ToolExecutionResult(
                tool_name="career_resume_version_create",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "resume_version",
                        "record_id": "resume_version_alpha",
                        "record": {
                            "resume_version_id": "resume_version_alpha",
                            "artifact_id": "artifact_resume_version_alpha",
                        },
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationMergeTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_merge",
                description="Merge application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = context
            assert arguments == {
                "application_id": "application_alpha",
                "updates": {"resume_version_ids": ["resume_version_alpha"]},
                "evidence_refs": [
                    "application_alpha",
                    "resume_profile_alpha",
                    "jd_alpha",
                    "fit_alpha",
                    "resume_version_alpha",
                ],
            }
            return ToolExecutionResult(
                tool_name="career_application_merge",
                success=True,
                content=json.dumps({"record_type": "career_application", "record_id": "application_alpha"}),
            )

    class ExecutorDraftModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            if "定制简历正文生成器" not in system_prompt:
                return ModelResponse(
                    content=json.dumps(
                        {
                            "active_context": [],
                            "decisions": [],
                            "progress": [],
                            "open_questions": [],
                            "candidate_long_term": [],
                            "artifact_refs": [],
                        },
                        ensure_ascii=False,
                    ),
                    tool_calls=[],
                )
            assert "定制简历正文生成器" in system_prompt
            assert tools == []
            assert "known_refs" in str(messages)
            self.calls += 1
            return ModelResponse(
                content=json.dumps(
                    {
                        "title": "AI 应用开发工程师定制简历",
                        "content": "# 张三\n\nPython FastAPI RAG 项目经验。",
                        "change_summary": ["强化 AI 应用后端相关表达"],
                        "keyword_strategy": ["Python", "FastAPI", "RAG"],
                        "risk_notes": ["缺少量化指标，未写入正文"],
                    },
                    ensure_ascii=False,
                ),
                tool_calls=[],
            )

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = ExecutorDraftModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[ApplicationGetTool(), ResumeVersionTool(), ApplicationMergeTool()],
    )
    session_id = "sess_resume_version_executor"
    session_repo.create_session(session_id)
    _append_success_tool_result(
        session_repo,
        session_id=session_id,
        tool_name="career_resume_profile_save",
        content={"record_type": "resume_profile", "record_id": "resume_profile_alpha"},
    )
    _append_success_tool_result(
        session_repo,
        session_id=session_id,
        tool_name="career_jd_analysis_save",
        content={"record_type": "jd_analysis", "record_id": "jd_alpha"},
    )
    _append_success_tool_result(
        session_repo,
        session_id=session_id,
        tool_name="career_job_fit_report_save",
        content={"record_type": "job_fit_report", "record_id": "fit_alpha"},
    )
    _append_success_tool_result(
        session_repo,
        session_id=session_id,
        tool_name="career_application_create",
        content={"record_type": "career_application", "record_id": "application_alpha"},
    )

    output = runtime.run(
        AgentRunInput(
            session_id=session_id,
            user_message="请基于当前求职项目 application_alpha 生成一版定制简历，并关联回项目。",
            skill_names=["base", "tools"],
            max_tool_rounds=5,
            context=_context(session_id),
        )
    )

    assert model.calls == 1
    assert output.answer.startswith("定制简历版本已生成并关联到当前求职项目。")
    assert [call.name for call in output.tool_calls] == [
        "career_resume_version_create",
        "career_application_merge",
    ]
    events = session_repo.list_events(session_id)
    decisions = [event.payload for event in events if event.type == "workflow_runtime_decision"]
    assert any(item["reason"] == "workflow_executor_contract_matched" for item in decisions)
    assert any(item["reason"] == "workflow_executor_completed" for item in decisions)
    assert not any(event.type == "llm_usage" and event.payload.get("phase") == "tool_loop" for event in events)
    assert any(event.type == "llm_usage" and event.payload.get("phase") == "workflow_executor" for event in events)


def test_runtime_stream_executor_runs_resume_version_project_action_without_tool_loop(tmp_path: Path) -> None:
    class ResumeVersionTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_resume_version_create",
                description="Create resume version.",
                parameters_schema={"type": "object", "properties": {"content": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = context
            assert arguments["base_resume_profile_id"] == "resume_profile_alpha"
            assert arguments["target_jd_analysis_id"] == "jd_alpha"
            assert arguments["content"] == "# 张三\n\nPython FastAPI RAG 项目经验。"
            assert arguments["evidence_refs"] == [
                "application_alpha",
                "resume_profile_alpha",
                "jd_alpha",
                "fit_alpha",
            ]
            assert "use_safe_fallback" not in arguments
            return ToolExecutionResult(
                tool_name="career_resume_version_create",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "resume_version",
                        "record_id": "resume_version_alpha",
                        "record": {
                            "resume_version_id": "resume_version_alpha",
                            "artifact_id": "artifact_resume_version_alpha",
                        },
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationMergeTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_merge",
                description="Merge application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = context
            assert arguments == {
                "application_id": "application_alpha",
                "updates": {"resume_version_ids": ["resume_version_alpha"]},
                "evidence_refs": [
                    "application_alpha",
                    "resume_profile_alpha",
                    "jd_alpha",
                    "fit_alpha",
                    "resume_version_alpha",
                ],
            }
            return ToolExecutionResult(
                tool_name="career_application_merge",
                success=True,
                content=json.dumps({"record_type": "career_application", "record_id": "application_alpha"}),
            )

    class StreamingExecutorDraftModelClient:
        def __init__(self) -> None:
            self.executor_stream_calls = 0
            self.tool_loop_stream_calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages, tools)
            return ModelResponse(
                content=json.dumps(
                    {
                        "active_context": [],
                        "decisions": [],
                        "progress": [],
                        "open_questions": [],
                        "candidate_long_term": [],
                        "artifact_refs": [],
                    },
                    ensure_ascii=False,
                ),
                tool_calls=[],
            )

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            assert tools == []
            if "定制简历正文生成器" not in system_prompt:
                self.tool_loop_stream_calls += 1
                raise AssertionError("streaming executor should not enter the normal tool loop")
            assert "known_refs" in str(messages)
            self.executor_stream_calls += 1
            payload = json.dumps(
                {
                    "title": "AI 应用开发工程师定制简历",
                    "content": "# 张三\n\nPython FastAPI RAG 项目经验。",
                    "change_summary": ["强化 AI 应用后端相关表达"],
                    "keyword_strategy": ["Python", "FastAPI", "RAG"],
                    "risk_notes": ["缺少量化指标，未写入正文"],
                },
                ensure_ascii=False,
            )
            midpoint = len(payload) // 2
            yield StreamChunk(delta=payload[:midpoint], finished=False, has_tool_call_delta=False)
            yield StreamChunk(delta=payload[midpoint:], finished=False, has_tool_call_delta=False)
            yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)

    class RecordingEventChannel(EventChannel):
        def __init__(self) -> None:
            super().__init__()
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def emit(self, event: str, data: dict[str, Any]) -> None:
            self.events.append((event, data))

    model = StreamingExecutorDraftModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[ResumeVersionTool(), ApplicationMergeTool()],
    )
    session_id = "sess_resume_version_stream_executor"
    session_repo.create_session(session_id)
    _append_success_tool_result(
        session_repo,
        session_id=session_id,
        tool_name="career_resume_profile_save",
        content={"record_type": "resume_profile", "record_id": "resume_profile_alpha"},
    )
    _append_success_tool_result(
        session_repo,
        session_id=session_id,
        tool_name="career_jd_analysis_save",
        content={"record_type": "jd_analysis", "record_id": "jd_alpha"},
    )
    _append_success_tool_result(
        session_repo,
        session_id=session_id,
        tool_name="career_job_fit_report_save",
        content={"record_type": "job_fit_report", "record_id": "fit_alpha"},
    )
    _append_success_tool_result(
        session_repo,
        session_id=session_id,
        tool_name="career_application_create",
        content={"record_type": "career_application", "record_id": "application_alpha"},
    )

    async def _run() -> tuple[AgentRunOutput, list[tuple[str, dict[str, Any]]]]:
        channel = RecordingEventChannel()
        output = await runtime.run_stream(
            AgentRunInput(
                session_id=session_id,
                user_message="请基于当前求职项目 application_alpha 生成一版定制简历，并关联回项目。",
                skill_names=["base", "tools"],
                max_tool_rounds=5,
                context=_context(session_id),
            ),
            channel,
        )
        return output, channel.events

    output, emitted_events = asyncio.run(_run())

    assert model.executor_stream_calls == 1
    assert model.tool_loop_stream_calls == 0
    assert output.answer.startswith("定制简历版本已生成并关联到当前求职项目。")
    assert [call.name for call in output.tool_calls] == [
        "career_resume_version_create",
        "career_application_merge",
    ]
    answer_deltas = [data["delta"] for event, data in emitted_events if event == "answer_delta"]
    assert answer_deltas == [output.answer]
    assert "change_summary" not in "".join(answer_deltas)
    assert any(event == "answer_meta" for event, _ in emitted_events)
    events = session_repo.list_events(session_id)
    decisions = [event.payload for event in events if event.type == "workflow_runtime_decision"]
    assert any(item["reason"] == "workflow_executor_contract_matched" for item in decisions)
    assert any(item["reason"] == "workflow_executor_completed" for item in decisions)
    assert not any(event.type == "llm_usage" and event.payload.get("phase") == "tool_loop" for event in events)
    assert any(
        event.type == "llm_usage"
        and event.payload.get("phase") == "workflow_executor"
        and event.payload.get("mode") == "stream"
        for event in events
    )


def _append_success_tool_result(
    repository: JsonlSessionRepository,
    *,
    session_id: str,
    tool_name: str,
    content: dict[str, Any],
) -> None:
    event_id = f"evt_seed_{tool_name}_{len(repository.list_agent_events(session_id, 'agent_main'))}"
    repository.append_agent_event(
        session_id,
        "agent_main",
        EventRecord(
            event_id=event_id,
            session_id=session_id,
            type="tool_result",
            payload={
                "tool_name": tool_name,
                "success": True,
                "content": json.dumps(content, ensure_ascii=False),
                "tool_call_id": f"call_seed_{tool_name}",
            },
            created_at=datetime.now(UTC),
            agent_id="agent_main",
            run_id=f"run_seed_{session_id}",
        ),
    )


def test_runtime_breaks_repeated_schema_search_after_resume_version_pending_merge(tmp_path: Path) -> None:
    class ToolSearch:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="tool_search",
                description="Search tools.",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            raise AssertionError("tool_search should be hidden once career_application_merge is required")

    class ResumeVersionTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_resume_version_create",
                description="Create resume version.",
                parameters_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_resume_version_create",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "resume_version",
                        "record_id": "resume_version_alpha",
                        "record": {
                            "resume_version_id": "resume_version_alpha",
                            "artifact_id": "artifact_resume_version_alpha",
                        },
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationMergeTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_merge",
                description="Merge application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_application_merge",
                success=True,
                content=json.dumps({"record_type": "career_application", "record_id": "application_alpha"}),
            )

    class RepeatedSearchBeforeMergeModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = system_prompt
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            if self.calls == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="career_resume_version_create", arguments={"title": "定制简历"})],
                )
            if self.calls in {2, 3, 4}:
                assert "career_application_merge" in tool_names
                assert "tool_search" not in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="tool_search", arguments={"query": "career_application_merge"})],
                )
            if self.calls == 5:
                assert any("下一步只调用这些已揭示工具" in str(message.get("content", "")) for message in messages)
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="career_application_merge", arguments={"application_id": "application_alpha"})],
                )
            return ModelResponse(content="定制简历已生成并关联项目。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = RepeatedSearchBeforeMergeModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[ToolSearch(), ResumeVersionTool(), ApplicationMergeTool()],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_resume_version_search_then_merge",
            user_message="生成定制简历",
            skill_names=["base", "tools"],
            max_tool_rounds=4,
            context=_context("sess_resume_version_search_then_merge"),
        )
    )

    assert output.answer == "定制简历已生成并关联项目。"
    assert model.calls == 6
    tool_calls = [
        event.payload["name"]
        for event in session_repo.list_events("sess_resume_version_search_then_merge")
        if event.type == "tool_call"
    ]
    assert tool_calls == ["career_resume_version_create", "career_application_merge"]
    hidden_search_results = [
        event
        for event in session_repo.list_events("sess_resume_version_search_then_merge")
        if event.type == "tool_result" and event.payload["tool_name"] == "tool_search"
    ]
    assert hidden_search_results == []
    decisions = [
        event.payload
        for event in session_repo.list_events("sess_resume_version_search_then_merge")
        if event.type == "workflow_runtime_decision"
    ]
    assert [item["reason"] for item in decisions] == [
        "schema_search_suppressed_required_tool_visible",
        "schema_search_suppressed_required_tool_visible",
        "schema_search_suppressed_required_tool_visible",
        "workflow_final_answer_ready",
    ]


def test_gateway_runtime_allows_one_schema_search_correction_before_stagnation(tmp_path: Path) -> None:
    class ToolSearch:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="tool_search",
                description="Search tools.",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            raise AssertionError("tool_search should be hidden once career_application_merge is required")

    class ResumeVersionTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_resume_version_create",
                description="Create resume version.",
                parameters_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_resume_version_create",
                success=True,
                content=json.dumps(
                    {
                        "record_type": "resume_version",
                        "record_id": "resume_version_alpha",
                        "record": {
                            "resume_version_id": "resume_version_alpha",
                            "artifact_id": "artifact_resume_version_alpha",
                        },
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationMergeTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_merge",
                description="Merge application.",
                parameters_schema={"type": "object", "properties": {"application_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_application_merge",
                success=True,
                content=json.dumps({"record_type": "career_application", "record_id": "application_alpha"}),
            )

    class DoubleSearchThenMergeModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = system_prompt
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            if self.calls == 1:
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="career_resume_version_create", arguments={"title": "定制简历"})],
                )
            if self.calls == 2:
                assert "career_application_merge" in tool_names
                assert "tool_search" not in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(name="tool_search", arguments={"query": "career_application_merge"}),
                        ToolCall(name="tool_search", arguments={"query": "career_application_merge"}),
                    ],
                )
            if self.calls == 3:
                assert any("career_application_merge" in str(message.get("content", "")) for message in messages)
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="career_application_merge", arguments={"application_id": "application_alpha"})],
                )
            return ModelResponse(content="定制简历已生成并关联项目。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = DoubleSearchThenMergeModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[ToolSearch(), ResumeVersionTool(), ApplicationMergeTool()],
        tool_call_ledger=JsonlToolCallLedger(data_dir=tmp_path),
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_gateway_schema_search_correction",
            user_message="生成定制简历",
            skill_names=["base", "tools"],
            max_tool_rounds=4,
            context=_context("sess_gateway_schema_search_correction"),
        )
    )

    assert output.answer == "定制简历已生成并关联项目。"
    assert model.calls == 4
    tool_calls = [
        event.payload["name"]
        for event in session_repo.list_events("sess_gateway_schema_search_correction")
        if event.type == "tool_call"
    ]
    assert tool_calls == [
        "career_resume_version_create",
        "career_application_merge",
    ]
    decisions = [
        event.payload
        for event in session_repo.list_events("sess_gateway_schema_search_correction")
        if event.type == "workflow_runtime_decision"
    ]
    assert any(item.get("reason") == "schema_search_suppressed_required_tool_visible" for item in decisions)
    assert not any(item.get("reason") == "tool_loop_stagnation" for item in decisions)


def test_runtime_auto_executes_interview_review_application_merge_after_repeated_schema_search(
    tmp_path: Path,
) -> None:
    class RuntimePlanSearchTool:
        def __init__(self) -> None:
            self.calls = 0

        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="tool_search",
                description="Search tools.",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            self.calls += 1
            return ToolExecutionResult(
                tool_name="tool_search",
                success=True,
                content=json.dumps(
                    {
                        "runtime_plan_applied": True,
                        "runtime_plan_phase": "interview_review_update",
                        "runtime_final_answer_ready": False,
                        "runtime_next_action": "面试复盘 Note 已保存；下一步只调用 career_application_merge 更新项目。",
                        "runtime_next_allowed_tools": ["career_application_merge"],
                        "runtime_missing_outputs": ["career_application_update"],
                        "runtime_known_refs": {
                            "application_id": "application_alpha",
                            "note_id": "note_alpha",
                            "resume_profile_id": "resume_profile_alpha",
                            "career_profile_id": "career_profile_default",
                            "jd_analysis_id": "jd_alpha",
                            "job_fit_report_id": "fit_alpha",
                        },
                        "revealed_tool_names": ["career_application_merge"],
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationMergeTool:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_merge",
                description="Merge application.",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "application_id": {"type": "string"},
                        "updates": {"type": "object"},
                        "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    },
                },
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = context
            self.calls.append(arguments)
            return ToolExecutionResult(
                tool_name="career_application_merge",
                success=True,
                content=json.dumps(
                    {"record_type": "career_application", "record_id": arguments["application_id"]},
                    ensure_ascii=False,
                ),
            )

    class RepeatedSchemaSearchModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = system_prompt
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            if self.calls == 1:
                assert "tool_search" in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="tool_search", arguments={"query": "career_application_merge"})],
                )
            if self.calls in {2, 3}:
                assert tool_names == {"career_application_merge"}
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="tool_search", arguments={"query": "career_application_merge"})],
                )
            assert tools == []
            return ModelResponse(content="面试复盘已保存并更新到求职项目。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    search_tool = RuntimePlanSearchTool()
    merge_tool = ApplicationMergeTool()
    model = RepeatedSchemaSearchModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[search_tool, merge_tool],
        tool_schema_disclosure_mode="search",
        tool_schema_always_visible=["tool_search", "memory_write"],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_interview_review_schema_search_auto_merge",
            user_message="继续",
            skill_names=["base", "tools"],
            max_tool_rounds=5,
            context=_context("sess_interview_review_schema_search_auto_merge"),
        )
    )

    assert output.answer == "面试复盘已保存并更新到求职项目。"
    assert search_tool.calls == 1
    assert len(merge_tool.calls) == 1
    merge_args = merge_tool.calls[0]
    assert merge_args["application_id"] == "application_alpha"
    assert merge_args["updates"]["stage"] == "interviewing"
    assert "note_alpha" in merge_args["updates"]["notes"]
    assert "note_alpha" in merge_args["evidence_refs"]
    assert "application_alpha" in merge_args["evidence_refs"]
    tool_calls = [
        event.payload["name"]
        for event in session_repo.list_events("sess_interview_review_schema_search_auto_merge")
        if event.type == "tool_call"
    ]
    assert tool_calls == ["tool_search", "career_application_merge"]
    decisions = [
        event.payload
        for event in session_repo.list_events("sess_interview_review_schema_search_auto_merge")
        if event.type == "workflow_runtime_decision"
    ]
    assert any(item.get("reason") == "schema_search_suppressed_required_tool_visible" for item in decisions)
    assert any(item.get("reason") == "strict_schema_search_replaced_with_required_tool" for item in decisions)


def test_runtime_uses_workflow_guard_next_allowed_tools_as_pending_plan(tmp_path: Path) -> None:
    class DelegateTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="delegate_agents",
                description="Delegate agents.",
                parameters_schema={"type": "object", "properties": {"tasks": {"type": "array"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            raise AssertionError("delegate_agents should be blocked by workflow guard")

    class ApplicationCreateTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_create",
                description="Create career application.",
                parameters_schema={"type": "object", "properties": {"job_fit_report_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_application_create",
                success=True,
                content=json.dumps({"record_type": "career_application", "record_id": "application_alpha"}),
            )

    class ApplicationFlowGuard:
        def inspect(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
            _ = context
            if tool_call.name != "delegate_agents":
                return WorkflowGuardDecision(tool_call=tool_call)
            payload = {
                "workflow_runtime_result": True,
                "policy": "block",
                "recoverable": True,
                "terminal": False,
                "tool": "delegate_agents",
                "reason": "main_jd_fit_records_ready_create_application",
                "next_action": "下一步只调用 career_application_create 创建求职项目。",
                "next_allowed_tools": ["career_application_create"],
                "missing_outputs": ["career_application"],
                "blocked_tools": ["delegate_agents"],
                "completed_refs": {
                    "resume_profile_id": "resume_profile_alpha",
                    "jd_analysis_id": "jd_alpha",
                    "job_fit_report_id": "fit_alpha",
                },
            }
            return WorkflowGuardDecision(
                tool_call=tool_call,
                result=ToolExecutionResult(
                    tool_name="delegate_agents",
                    success=True,
                    content=json.dumps(payload, ensure_ascii=False),
                ),
                event_payload={
                    "workflow_runtime_result": True,
                    "policy": "block",
                    "tool_name": "delegate_agents",
                    "reason": "main_jd_fit_records_ready_create_application",
                    "next_allowed_tools": ["career_application_create"],
                    "missing_outputs": ["career_application"],
                },
            )

    class GuardPlanModelClient:
        def __init__(self) -> None:
            self.calls = 0
            self.tool_names_by_call: list[set[str]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = system_prompt
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            self.tool_names_by_call.append(tool_names)
            if self.calls == 1:
                assert "delegate_agents" in tool_names
                assert "career_application_create" not in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="delegate_agents", arguments={"tasks": []})],
                )
            if self.calls == 2:
                assert "career_application_create" in tool_names
                assert "delegate_agents" not in tool_names
                return ModelResponse(content="匹配报告已经完成。", tool_calls=[])
            if self.calls == 3:
                assert any("运行时守卫" in str(message.get("content", "")) for message in messages)
                assert "delegate_agents" not in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(name="career_application_create", arguments={"job_fit_report_id": "fit_alpha"})
                    ],
                )
            return ModelResponse(content="已创建求职项目。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = GuardPlanModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[DelegateTool(), ApplicationCreateTool()],
        tool_schema_disclosure_mode="search",
        tool_schema_always_visible=["delegate_agents", "memory_write"],
        workflow_guard=ApplicationFlowGuard(),
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_guard_plan",
            user_message="创建求职项目",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_guard_plan"),
        )
    )

    assert output.answer == "已创建求职项目。"
    assert model.calls == 4
    assert model.tool_names_by_call[1] >= {"career_application_create"}
    tool_calls = [event.payload["name"] for event in session_repo.list_events("sess_guard_plan") if event.type == "tool_call"]
    assert tool_calls == ["delegate_agents", "career_application_create"]
    decisions = [
        event.payload
        for event in session_repo.list_events("sess_guard_plan")
        if event.type == "workflow_runtime_decision"
    ]
    assert [decision["reason"] for decision in decisions] == [
        "main_jd_fit_records_ready_create_application",
        "premature_final_answer_with_pending_runtime_tools",
    ]


def test_runtime_uses_delegate_result_refs_as_application_create_plan(tmp_path: Path) -> None:
    class DelegateTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="delegate_agents",
                description="Delegate agents.",
                parameters_schema={"type": "object", "properties": {"tasks": {"type": "array"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="delegate_agents",
                success=True,
                content=json.dumps(
                    {
                        "status": "completed",
                        "results": [
                            {
                                "target_agent_id": "job_agent",
                                "status": "completed",
                                "summary": "JDAnalysis 和 JobFitReport 已完成。",
                                "output_artifact_refs": ["artifact_fit_report"],
                                "product_refs": ["jd_alpha", "fit_alpha"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationCreateTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_create",
                description="Create career application.",
                parameters_schema={"type": "object", "properties": {"job_fit_report_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            assert arguments["job_fit_report_id"] == "fit_alpha"
            _ = context
            return ToolExecutionResult(
                tool_name="career_application_create",
                success=True,
                content=json.dumps({"record_type": "career_application", "record_id": "application_alpha"}),
            )

    class DelegatePlanModelClient:
        def __init__(self) -> None:
            self.calls = 0
            self.tool_names_by_call: list[set[str]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = system_prompt
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            self.tool_names_by_call.append(tool_names)
            if self.calls == 1:
                assert "delegate_agents" in tool_names
                assert "career_application_create" not in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="delegate_agents", arguments={"tasks": []})],
                )
            if self.calls == 2:
                assert "career_application_create" in tool_names
                assert "delegate_agents" not in tool_names
                return ModelResponse(content="匹配报告已经完成。", tool_calls=[])
            if self.calls == 3:
                assert any("运行时守卫" in str(message.get("content", "")) for message in messages)
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(name="career_application_create", arguments={"job_fit_report_id": "fit_alpha"})
                    ],
                )
            return ModelResponse(content="已创建求职项目。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = DelegatePlanModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[DelegateTool(), ApplicationCreateTool()],
        tool_schema_disclosure_mode="search",
        tool_schema_always_visible=["delegate_agents", "memory_write"],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_delegate_result_plan",
            user_message="完成 JD 匹配并创建求职项目",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_delegate_result_plan"),
        )
    )

    assert output.answer == "已创建求职项目。"
    assert model.calls == 4
    assert model.tool_names_by_call[1] >= {"career_application_create"}
    tool_calls = [
        event.payload["name"]
        for event in session_repo.list_events("sess_delegate_result_plan")
        if event.type == "tool_call"
    ]
    assert tool_calls == ["delegate_agents", "career_application_create"]
    decisions = [
        event.payload
        for event in session_repo.list_events("sess_delegate_result_plan")
        if event.type == "workflow_runtime_decision"
    ]
    assert decisions[0]["reason"] == "premature_final_answer_with_pending_runtime_tools"


def test_runtime_replaces_hidden_delegate_with_required_application_create(tmp_path: Path) -> None:
    class DelegateTool:
        def __init__(self) -> None:
            self.calls = 0

        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="delegate_agents",
                description="Delegate agents.",
                parameters_schema={"type": "object", "properties": {"tasks": {"type": "array"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("hidden delegate_agents should be replaced with the required tool")
            return ToolExecutionResult(
                tool_name="delegate_agents",
                success=True,
                content=json.dumps(
                    {
                        "status": "completed",
                        "results": [
                            {
                                "target_agent_id": "job_agent",
                                "status": "completed",
                                "summary": "JDAnalysis 和 JobFitReport 已完成。",
                                "output_artifact_refs": ["artifact_fit_report"],
                                "product_refs": [
                                    "resume_profile_alpha",
                                    "career_profile_default",
                                    "jd_alpha",
                                    "fit_alpha",
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            )

    class ApplicationCreateTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_create",
                description="Create career application.",
                parameters_schema={"type": "object", "properties": {"job_fit_report_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = context
            assert arguments["job_fit_report_id"] == "fit_alpha"
            assert arguments["jd_analysis_id"] == "jd_alpha"
            assert arguments["evidence_refs"] == [
                "resume_profile_alpha",
                "career_profile_default",
                "jd_alpha",
                "fit_alpha",
                "artifact_fit_report",
            ]
            return ToolExecutionResult(
                tool_name="career_application_create",
                success=True,
                content=json.dumps({"record_type": "career_application", "record_id": "application_alpha"}),
            )

    class HiddenDelegateModelClient:
        def __init__(self) -> None:
            self.calls = 0
            self.tool_names_by_call: list[set[str]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            self.tool_names_by_call.append(tool_names)
            if self.calls == 1:
                assert "delegate_agents" in tool_names
                assert "career_application_create" not in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="delegate_agents", arguments={"tasks": []})],
                )
            if self.calls == 2:
                assert "career_application_create" in tool_names
                assert "delegate_agents" not in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="delegate_agents", arguments={"tasks": []})],
                )
            return ModelResponse(content="已创建求职项目。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = HiddenDelegateModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[DelegateTool(), ApplicationCreateTool()],
        tool_schema_disclosure_mode="search",
        tool_schema_always_visible=["delegate_agents", "memory_write"],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_hidden_delegate_replaced_application_create",
            user_message="完成 JD 匹配并创建求职项目",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_hidden_delegate_replaced_application_create"),
        )
    )

    assert output.answer == "已创建求职项目。"
    assert model.calls == 3
    events = session_repo.list_events("sess_hidden_delegate_replaced_application_create")
    tool_calls = [event.payload["name"] for event in events if event.type == "tool_call"]
    assert tool_calls == ["delegate_agents", "delegate_agents", "career_application_create"]
    assert not any(
        event.type == "tool_result" and "tool_hidden_by_runtime_plan" in event.payload.get("content", "")
        for event in events
    )
    decisions = [event.payload for event in events if event.type == "workflow_runtime_decision"]
    assert any(item.get("reason") == "strict_hidden_tool_replaced_with_required_tool" for item in decisions)


def test_runtime_terminal_blocks_hidden_tool_search_after_delegate_final_ready(tmp_path: Path) -> None:
    class RuntimePlanSearchTool:
        def __init__(self) -> None:
            self.calls = 0

        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="tool_search",
                description="Search tools.",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            self.calls += 1
            return ToolExecutionResult(
                tool_name="tool_search",
                success=True,
                content=json.dumps(
                    {
                        "runtime_plan_applied": True,
                        "runtime_plan_phase": "resume_diagnosis",
                        "runtime_final_answer_ready": False,
                        "runtime_next_action": "委派 resume_agent 完成简历诊断。",
                        "runtime_next_allowed_tools": ["delegate_agents"],
                        "runtime_missing_outputs": ["resume_profile"],
                        "revealed_tool_names": ["delegate_agents"],
                    },
                    ensure_ascii=False,
                ),
            )

    class DelegateTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="delegate_agents",
                description="Delegate agents.",
                parameters_schema={"type": "object", "properties": {"tasks": {"type": "array"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="delegate_agents",
                success=True,
                content=json.dumps(
                    {
                        "status": "completed",
                        "results": [
                            {
                                "target_agent_id": "resume_agent",
                                "status": "completed",
                                "summary": "已生成 resume_profile_alpha 和 artifact_diagnosis。",
                                "output_artifact_refs": ["artifact_diagnosis"],
                                "product_refs": ["resume_profile_alpha"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            )

    class FinalReadySearchModelClient:
        def __init__(self) -> None:
            self.calls = 0
            self.tool_names_by_call: list[set[str]] = []
            self.searched = False
            self.delegated = False

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = system_prompt
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            self.tool_names_by_call.append(tool_names)
            if not self.searched:
                assert "tool_search" in tool_names
                self.searched = True
                return ModelResponse(content="", tool_calls=[ToolCall(name="tool_search", arguments={"query": "简历诊断"})])
            if not self.delegated:
                assert "delegate_agents" in tool_names
                self.delegated = True
                return ModelResponse(content="", tool_calls=[ToolCall(name="delegate_agents", arguments={"tasks": []})])
            if self.delegated and tool_names and self.calls < 4:
                assert "tool_search" not in tool_names
                assert "delegate_agents" not in tool_names
                return ModelResponse(content="", tool_calls=[ToolCall(name="tool_search", arguments={"query": "career_profile_merge"})])
            return ModelResponse(content="简历诊断已完成。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    search_tool = RuntimePlanSearchTool()
    model = FinalReadySearchModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[search_tool, DelegateTool()],
        tool_schema_disclosure_mode="search",
        tool_schema_always_visible=["tool_search", "memory_write"],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_final_ready_hidden_search",
            user_message="诊断简历",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_final_ready_hidden_search"),
        )
    )

    assert output.answer == "简历诊断已完成。"
    assert search_tool.calls <= 1
    assert model.calls == 3
    events = session_repo.list_events("sess_final_ready_hidden_search")
    tool_calls = [
        event.payload["name"]
        for event in events
        if event.type == "tool_call"
    ]
    assert tool_calls[-2:] == ["tool_search", "delegate_agents"]
    decisions = [event.payload for event in events if event.type == "workflow_runtime_decision"]
    assert any(item["reason"] == "workflow_final_answer_ready" for item in decisions)


def test_child_job_fit_success_results_narrow_next_round_tools(tmp_path: Path) -> None:
    class JsonTool:
        def __init__(self, name: str, payload: dict[str, Any]) -> None:
            self._name = name
            self._payload = payload

        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name=self._name,
                description=f"{self._name} test tool.",
                parameters_schema={"type": "object", "properties": {}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name=self._name,
                success=True,
                content=json.dumps(self._payload, ensure_ascii=False),
            )

    class JobFitPlanModelClient:
        def __init__(self) -> None:
            self.calls = 0
            self.tool_names_by_call: list[set[str]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            self.tool_names_by_call.append(tool_names)
            if self.calls == 1:
                assert {
                    "career_jd_analysis_save",
                    "session_create_text_artifact",
                    "session_read_artifact",
                } <= tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_jd_analysis_save",
                            arguments={"source_artifact_id": "artifact_jd"},
                        )
                    ],
                )
            if self.calls == 2:
                assert "session_create_text_artifact" in tool_names
                assert "session_read_artifact" not in tool_names
                assert "career_resume_profile_get" not in tool_names
                assert "career_job_fit_report_save" not in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="session_create_text_artifact",
                            arguments={"title": "岗位匹配报告 - AI 应用开发工程师"},
                        )
                    ],
                )
            if self.calls == 3:
                assert "career_job_fit_report_save" in tool_names
                assert "session_read_artifact" not in tool_names
                assert "session_create_text_artifact" not in tool_names
                assert "career_jd_analysis_save" not in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_job_fit_report_save",
                            arguments={
                                "jd_analysis_id": "jd_alpha",
                                "report_artifact_id": "artifact_fit_report",
                            },
                        )
                    ],
                )
            return ModelResponse(content="匹配报告已保存。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = JobFitPlanModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[
            JsonTool(
                "career_jd_analysis_save",
                {
                    "record_type": "jd_analysis",
                    "record_id": "jd_alpha",
                    "record": {"jd_analysis_id": "jd_alpha"},
                },
            ),
            JsonTool(
                "session_create_text_artifact",
                {
                    "artifact_id": "artifact_fit_report",
                    "title": "岗位匹配报告 - AI 应用开发工程师",
                    "kind": "generated_file",
                },
            ),
            JsonTool(
                "career_job_fit_report_save",
                {
                    "record_type": "job_fit_report",
                    "record_id": "fit_alpha",
                    "record": {"job_fit_report_id": "fit_alpha"},
                },
            ),
            JsonTool("session_read_artifact", {"artifact_id": "artifact_jd"}),
            JsonTool(
                "career_resume_profile_get",
                {"record_type": "resume_profile", "record_id": "resume_profile_alpha"},
            ),
            JsonTool("career_profile_get", {"record_type": "career_profile", "record_id": "career_profile_default"}),
            JsonTool("career_jd_analysis_get", {"record_type": "jd_analysis", "record_id": "jd_alpha"}),
            JsonTool("career_job_fit_report_get", {"record_type": "job_fit_report", "record_id": "fit_alpha"}),
        ],
        tool_schema_disclosure_mode="search",
    )

    context = RunContext(
        session_id="sess_child_job_fit_plan",
        run_id="run_child_job_fit_plan",
        agent_id="job_agent",
        turn_id="turn_child_job_fit_plan",
        entry_agent_id="agent_main",
        parent_run_id="run_parent",
    )
    output = runtime.run(
        AgentRunInput(
            session_id="sess_child_job_fit_plan",
            user_message="完成 JD 匹配子任务",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=context,
        )
    )

    assert output.answer == "匹配报告已保存。"
    assert model.calls == 4
    assert model.tool_names_by_call[1] >= {"session_create_text_artifact"}
    assert model.tool_names_by_call[2] >= {"career_job_fit_report_save"}
    tool_calls = [
        event.payload["name"]
        for event in session_repo.list_agent_events("sess_child_job_fit_plan", "job_agent")
        if event.type == "tool_call"
    ]
    assert tool_calls == [
        "career_jd_analysis_save",
        "session_create_text_artifact",
        "career_job_fit_report_save",
    ]


def test_job_fit_report_save_without_pending_plan_still_hides_completed_stage_tools(tmp_path: Path) -> None:
    class JsonTool:
        def __init__(self, name: str, payload: dict[str, Any]) -> None:
            self._name = name
            self._payload = payload

        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name=self._name,
                description=f"{self._name} test tool.",
                parameters_schema={"type": "object", "properties": {}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name=self._name,
                success=True,
                content=json.dumps(self._payload, ensure_ascii=False),
            )

    class SaveWithoutPendingPlanModelClient:
        def __init__(self) -> None:
            self.calls = 0
            self.tool_names_by_call: list[set[str]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            self.tool_names_by_call.append(tool_names)
            if self.calls == 1:
                assert "career_job_fit_report_save" in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_job_fit_report_save",
                            arguments={"jd_analysis_id": "jd_alpha", "report_artifact_id": "artifact_fit_report"},
                        )
                    ],
                )
            assert "career_job_fit_report_save" not in tool_names
            assert "session_create_text_artifact" not in tool_names
            assert "career_jd_analysis_save" not in tool_names
            return ModelResponse(content="匹配报告已保存。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = SaveWithoutPendingPlanModelClient()
    runtime, _, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[
            JsonTool(
                "career_job_fit_report_save",
                {
                    "record_type": "job_fit_report",
                    "record_id": "fit_alpha",
                    "record": {
                        "job_fit_report_id": "fit_alpha",
                        "jd_analysis_id": "jd_alpha",
                        "report_artifact_id": "artifact_fit_report",
                    },
                },
            ),
            JsonTool(
                "session_create_text_artifact",
                {"artifact_id": "artifact_late", "title": "求职项目记录"},
            ),
            JsonTool("career_jd_analysis_save", {"record_type": "jd_analysis", "record_id": "jd_alpha"}),
        ],
        tool_schema_disclosure_mode="search",
        tool_schema_always_visible=[
            "memory_write",
            "career_job_fit_report_save",
            "session_create_text_artifact",
            "career_jd_analysis_save",
        ],
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_job_fit_save_without_pending",
            user_message="完成 JD 匹配子任务",
            skill_names=["base", "tools"],
            max_tool_rounds=2,
            context=RunContext(
                session_id="sess_job_fit_save_without_pending",
                run_id="run_job_fit_save_without_pending",
                agent_id="job_agent",
                turn_id="turn_job_fit_save_without_pending",
                entry_agent_id="agent_main",
                parent_run_id="run_parent",
            ),
        )
    )

    assert output.answer == "匹配报告已保存。"
    assert model.calls == 2
    assert "career_job_fit_report_save" not in model.tool_names_by_call[1]
    assert "session_create_text_artifact" not in model.tool_names_by_call[1]
    assert "career_jd_analysis_save" not in model.tool_names_by_call[1]


def test_runtime_uses_workflow_guard_tool_search_block_to_reveal_next_allowed_schema(tmp_path: Path) -> None:
    class ApplicationCreateTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="career_application_create",
                description="Create career application.",
                parameters_schema={"type": "object", "properties": {"job_fit_report_id": {"type": "string"}}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(
                tool_name="career_application_create",
                success=True,
                content=json.dumps({"record_type": "career_application", "record_id": "application_alpha"}),
            )

    class ToolSearchStageGuard:
        def inspect(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
            _ = context
            if tool_call.name != "tool_search":
                return WorkflowGuardDecision(tool_call=tool_call)
            payload = {
                "workflow_runtime_result": True,
                "policy": "block",
                "recoverable": True,
                "terminal": False,
                "tool": "tool_search",
                "reason": "main_jd_fit_records_ready_create_application",
                "stage": "jd_fit",
                "next_action": "下一步只调用 career_application_create 创建求职项目。",
                "next_allowed_tools": ["career_application_create"],
                "missing_outputs": ["career_application"],
                "completed_refs": {
                    "resume_profile_id": "resume_profile_alpha",
                    "jd_analysis_id": "jd_alpha",
                    "job_fit_report_id": "fit_alpha",
                },
            }
            return WorkflowGuardDecision(
                tool_call=tool_call,
                result=ToolExecutionResult(
                    tool_name="tool_search",
                    success=True,
                    content=json.dumps(payload, ensure_ascii=False),
                ),
                event_payload={
                    "workflow_runtime_result": True,
                    "policy": "block",
                    "tool_name": "tool_search",
                    "reason": "main_jd_fit_records_ready_create_application",
                    "next_allowed_tools": ["career_application_create"],
                    "missing_outputs": ["career_application"],
                },
            )

    class GuardedToolSearchModelClient:
        def __init__(self) -> None:
            self.calls = 0
            self.tool_names_by_call: list[set[str]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = system_prompt
            self.calls += 1
            tool_names = {item["function"]["name"] for item in tools}
            self.tool_names_by_call.append(tool_names)
            if self.calls == 1:
                assert "tool_search" in tool_names
                assert "career_application_create" not in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[ToolCall(name="tool_search", arguments={"query": "创建求职项目"})],
                )
            if self.calls == 2:
                assert "career_application_create" in tool_names
                return ModelResponse(content="匹配报告已经完成。", tool_calls=[])
            if self.calls == 3:
                assert any("运行时守卫" in str(message.get("content", "")) for message in messages)
                assert "career_application_create" in tool_names
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(name="career_application_create", arguments={"job_fit_report_id": "fit_alpha"})
                    ],
                )
            return ModelResponse(content="已创建求职项目。", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = GuardedToolSearchModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[ApplicationCreateTool()],
        register_tool_search=True,
        tool_schema_disclosure_mode="search",
        workflow_guard=ToolSearchStageGuard(),
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_guarded_tool_search_plan",
            user_message="创建求职项目",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_context("sess_guarded_tool_search_plan"),
        )
    )

    assert output.answer == "已创建求职项目。"
    assert model.calls == 4
    assert "career_application_create" in model.tool_names_by_call[1]
    tool_calls = [
        event.payload["name"]
        for event in session_repo.list_events("sess_guarded_tool_search_plan")
        if event.type == "tool_call"
    ]
    assert tool_calls == ["tool_search", "career_application_create"]
    decisions = [
        event.payload
        for event in session_repo.list_events("sess_guarded_tool_search_plan")
        if event.type == "workflow_runtime_decision"
    ]
    assert [decision["reason"] for decision in decisions] == [
        "main_jd_fit_records_ready_create_application",
        "premature_final_answer_with_pending_runtime_tools",
    ]


def test_runtime_search_disclosure_keeps_child_agent_on_full_schema(tmp_path: Path) -> None:
    class SessionReadTool:
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="session_read_artifact",
                description="Read artifact.",
                parameters_schema={"type": "object", "properties": {}},
            )

        def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
            _ = (arguments, context)
            return ToolExecutionResult(tool_name="session_read_artifact", success=True, content="ok")

    class CapturingModelClient:
        def __init__(self) -> None:
            self.tool_names: set[str] = set()

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages)
            self.tool_names = {item["function"]["name"] for item in tools}
            return ModelResponse(content="child ok", tool_calls=[])

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, messages, tools)
            if False:
                yield StreamChunk(delta="", finished=True, has_tool_call_delta=False)
            raise NotImplementedError("stream path is not used in this test")

    model = CapturingModelClient()
    runtime, session_repo, _ = _build_runtime(
        tmp_path,
        model,
        extra_tools=[SessionReadTool()],
        register_tool_search=True,
        tool_schema_disclosure_mode="search",
    )

    output = runtime.run(
        AgentRunInput(
            session_id="sess_child_full_tools",
            user_message="child task",
            skill_names=["base", "tools"],
            max_tool_rounds=1,
            context=RunContext(
                session_id="sess_child_full_tools",
                run_id="run_child_full_tools",
                agent_id="resume_agent",
                turn_id="turn_child_full_tools",
                entry_agent_id="agent_main",
            ),
        )
    )
    usage = next(event for event in session_repo.list_events("sess_child_full_tools") if event.type == "llm_usage")

    assert output.answer == "child ok"
    assert "session_read_artifact" in model.tool_names
    assert "tool_search" not in model.tool_names
    assert usage.payload["tool_disclosure_mode"] == "full"


def test_runtime_stream_recovers_when_final_round_returns_empty_answer(tmp_path: Path) -> None:
    model = SequenceModelClient(
        responses=[
            ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="memory_write",
                        arguments={"content": "stream memory", "tags": ["preference"]},
                    )
                ],
            ),
            ModelResponse(content="", tool_calls=[]),
            ModelResponse(content="这是补出来的流式最终答复。", tool_calls=[]),
        ]
    )
    runtime, _, _ = _build_runtime(tmp_path, model)

    async def _run() -> AgentRunOutput:
        from app.runtime.event_channel import EventChannel

        return await runtime.run_stream(
            AgentRunInput(
                session_id="sess_recover_stream",
                user_message="stream recover",
                skill_names=["base", "memory"],
                max_tool_rounds=3,
                context=_context("sess_recover_stream"),
            ),
            EventChannel(),
        )

    output = asyncio.run(_run())

    assert output.answer == "这是补出来的流式最终答复。"


def test_runtime_stream_rejects_internal_limit_text_from_model_answer(tmp_path: Path) -> None:
    model = SequenceModelClient(
        responses=[
            ModelResponse(content="Tool call limit reached before generating final answer.", tool_calls=[]),
            ModelResponse(content="这是流式可用最终答复。", tool_calls=[]),
        ]
    )
    runtime, session_repo, _ = _build_runtime(tmp_path, model)

    class RecordingEventChannel(EventChannel):
        def __init__(self) -> None:
            super().__init__()
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def emit(self, event: str, data: dict[str, Any]) -> None:
            self.events.append((event, data))

    async def _run() -> tuple[AgentRunOutput, list[tuple[str, dict[str, Any]]]]:
        channel = RecordingEventChannel()
        output = await runtime.run_stream(
            AgentRunInput(
                session_id="sess_stream_internal_answer_recovery",
                user_message="给我最终结果",
                skill_names=["base"],
                max_tool_rounds=1,
                context=_context("sess_stream_internal_answer_recovery"),
            ),
            channel,
        )
        return output, channel.events

    output, events = asyncio.run(_run())

    assert output.answer == "这是流式可用最终答复。"
    answer_deltas = [data["delta"] for event, data in events if event == "answer_delta"]
    assert not any("Tool call limit reached" in delta for delta in answer_deltas)
    session_events = session_repo.list_events("sess_stream_internal_answer_recovery")
    assert any(event.type == "assistant_answer_rejected" for event in session_events)


def test_runtime_stream_compacts_consumed_tool_exchange(tmp_path: Path) -> None:
    class CapturingStreamModelClient:
        def __init__(self) -> None:
            self.calls: list[list[dict[str, Any]]] = []

        def generate(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> ModelResponse:
            _ = (system_prompt, messages, tools)
            raise NotImplementedError("sync path is not used in this test")

        async def generate_stream(
            self,
            system_prompt: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[StreamChunk]:
            _ = (system_prompt, tools)
            self.calls.append(messages)
            if len(self.calls) == 1:
                yield StreamChunk(
                    finished=True,
                    tool_calls=[
                        ToolCall(
                            name="memory_write",
                            arguments={"content": "stream first memory", "tags": ["t"]},
                            tool_call_id="call_stream_first",
                        )
                    ],
                )
                return
            if len(self.calls) == 2:
                tool_messages = [message for message in messages if message.get("role") == "tool"]
                assert [message.get("tool_call_id") for message in tool_messages] == ["call_stream_first"]
                yield StreamChunk(
                    finished=True,
                    tool_calls=[
                        ToolCall(
                            name="memory_write",
                            arguments={"content": "stream second memory", "tags": ["t"]},
                            tool_call_id="call_stream_second",
                        )
                    ],
                )
                return
            tool_messages = [message for message in messages if message.get("role") == "tool"]
            state_messages = [
                message
                for message in messages
                if message.get("role") == "assistant" and "runtime_tool_state" in str(message.get("content"))
            ]
            assert [message.get("tool_call_id") for message in tool_messages] == ["call_stream_second"]
            assert state_messages
            assert "call_stream_first" in str(state_messages[0]["content"])
            yield StreamChunk(delta="stream done", finished=True)

    model = CapturingStreamModelClient()
    runtime, session_repo, _ = _build_runtime(tmp_path, model, tool_context_window_mode="compact")

    async def _run() -> AgentRunOutput:
        return await runtime.run_stream(
            AgentRunInput(
                session_id="sess_stream_tool_context_window",
                user_message="run stream compact tool window",
                skill_names=["base", "tools"],
                max_tool_rounds=3,
                context=_context("sess_stream_tool_context_window"),
            ),
            EventChannel(),
        )

    output = asyncio.run(_run())
    usage_events = [
        event for event in session_repo.list_events("sess_stream_tool_context_window") if event.type == "llm_usage"
    ]

    assert output.answer == "stream done"
    assert usage_events[2].payload["tool_context_window_mode"] == "compact"
    assert usage_events[2].payload["compacted_tool_observation_count"] == 1


def test_runtime_stream_does_not_emit_and_reset_partial_answer_before_tool_call(tmp_path: Path) -> None:
    model = SequenceModelClient(
        responses=[
            ModelResponse(
                content="我先帮你看一下",
                tool_calls=[
                    ToolCall(
                        name="memory_write",
                        arguments={"content": "stream memory", "tags": ["preference"]},
                    )
                ],
            ),
            ModelResponse(content="已经处理完毕。", tool_calls=[]),
        ]
    )
    runtime, _, _ = _build_runtime(tmp_path, model)

    class RecordingEventChannel(EventChannel):
        def __init__(self) -> None:
            super().__init__()
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def emit(self, event: str, data: dict[str, Any]) -> None:
            self.events.append((event, data))

    async def _run() -> tuple[AgentRunOutput, list[tuple[str, dict[str, Any]]]]:
        channel = RecordingEventChannel()
        output = await runtime.run_stream(
            AgentRunInput(
                session_id="sess_stream_tool_buffer",
                user_message="stream tool buffer",
                skill_names=["base", "memory"],
                max_tool_rounds=3,
                context=_context("sess_stream_tool_buffer"),
            ),
            channel,
        )
        return output, channel.events

    output, events = asyncio.run(_run())

    answer_deltas = [data["delta"] for event, data in events if event == "answer_delta"]
    event_names = [event for event, _ in events]

    assert output.answer == "已经处理完毕。"
    assert answer_deltas == ["已经处理完毕。"]
    assert "answer_reset" not in event_names
    assert "answer_meta_reset" not in event_names


def test_runtime_post_run_maintenance_is_single_flight_per_session_agent(tmp_path: Path) -> None:
    class SlowFlusher(MidTermFlusher):
        def __init__(self) -> None:
            self.calls = 0
            self._lock = threading.Lock()

        def flush_for_run_finished(self, context: RunContext) -> MidTermFlushResult:
            with self._lock:
                self.calls += 1
            time.sleep(0.05)
            return MidTermFlushResult(
                flushed=False,
                reason="threshold_not_met",
                session_id=context.session_id,
                agent_id=context.agent_id,
                event_count=0,
                signal_score=0,
            )

    runtime, _, _ = _build_runtime(tmp_path, StaticModelClient(content="ok"))
    slow_flusher = SlowFlusher()
    runtime._mid_term_flusher = slow_flusher  # noqa: SLF001
    runtime._context_compactor = None  # noqa: SLF001

    for index in range(12):
        context = RunContext(
            session_id="sess_single_flight",
            run_id=f"run_{index}",
            agent_id="agent_main",
            turn_id=f"turn_{index}",
            entry_agent_id="agent_main",
            parent_run_id=None,
            trace_flags={},
        )
        runtime._dispatch_post_run_maintenance_sync(context)  # noqa: SLF001

    time.sleep(0.25)

    assert 1 <= slow_flusher.calls <= 2
