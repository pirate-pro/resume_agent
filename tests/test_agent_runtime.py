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
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.file_store import FileMemoryStore
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



def test_runtime_stops_when_tool_round_limit_exceeded(tmp_path: Path) -> None:
    model = SequenceModelClient(
        responses=[
            ModelResponse(
                content="",
                tool_calls=[ToolCall(name="memory_write", arguments={"content": "x", "tags": []})],
            )
        ]
    )
    runtime, _, _ = _build_runtime(tmp_path, model)

    output = runtime.run(
        AgentRunInput(
            session_id="sess_3",
            user_message="loop",
            skill_names=["base"],
            max_tool_rounds=0,
            context=_context("sess_3"),
        )
    )

    assert "Tool call limit reached" in output.answer


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
    assert "career_resume_version_create" in model.tool_names_by_call[0]
    assert "career_application_get" in model.tool_names_by_call[0]
    assert "tool_search" not in model.tool_names_by_call[0]
    assert usage_event.payload["tool_disclosure_mode"] == "search"
    assert usage_event.payload["visible_tool_count"] > 1
    assert "career_resume_version_create" in usage_event.payload["visible_tool_names"]
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
                return ModelResponse(content="", tool_calls=[ToolCall(name="tool_search", arguments={"query": "再搜一次"})])
            if self.calls == 3:
                assert any("运行时守卫" in str(message.get("content", "")) for message in messages)
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
        tool_schema_always_visible=["tool_search"],
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
    assert decisions[0]["reason"] == "schema_search_with_pending_runtime_tools"


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
