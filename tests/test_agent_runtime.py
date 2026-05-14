"""Tests for agent runtime execution loop."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.domain.models import AgentRunInput, AgentRunOutput, RunContext, ToolCall
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
from app.runtime.session_manager import SessionManager
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.tools.builtins import MemoryWriteTool
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

    session_manager = SessionManager(session_repository=session_repo)
    event_recorder = EventRecorder(session_repository=session_repo)
    context_assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=skill_repo,
        agent_document_repository=agent_document_repository,
        memory_manager=memory_manager,
        state_manager=state_manager,
        tool_executor=tool_registry,
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
