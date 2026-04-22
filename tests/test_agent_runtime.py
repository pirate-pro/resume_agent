"""Tests for agent runtime execution loop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.domain.models import AgentRunInput, RunContext, ToolCall
from app.domain.protocols import ChatModelClient, ModelResponse
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.facade import FileMemoryFacade
from app.memory.models import MemoryReadRequest
from app.memory.policies import default_memory_policy
from app.memory.stores.jsonl_file_store import JsonlFileMemoryStore
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.event_recorder import EventRecorder
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.tools.builtins import MemoryWriteTool
from app.tools.registry import ToolRegistry
from tests.helpers import SequenceModelClient, StaticModelClient

__all__ = []


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
) -> tuple[AgentRuntime, JsonlSessionRepository, FileMemoryFacade]:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    skill_repo = MarkdownSkillRepository(skills_dir=Path("app/skills"))

    tool_registry = ToolRegistry()
    tool_registry.register(MemoryWriteTool(memory_facade=memory_facade))

    session_manager = SessionManager(session_repository=session_repo)
    event_recorder = EventRecorder(session_repository=session_repo)
    memory_manager = MemoryManager(memory_facade=memory_facade)
    context_assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=skill_repo,
        memory_manager=memory_manager,
        tool_executor=tool_registry,
    )
    runtime = AgentRuntime(
        session_manager=session_manager,
        event_recorder=event_recorder,
        context_assembler=context_assembler,
        model_client=model_client,
        tool_executor=tool_registry,
    )
    return runtime, session_repo, memory_facade



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
    runtime, session_repo, memory_facade = _build_runtime(tmp_path, model)

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
    memories = memory_facade.read_context(
        MemoryReadRequest(
            agent_id="agent_main",
            session_id="sess_2",
            query="jsonl",
            limit=10,
            token_budget=2400,
        )
    ).items

    assert output.answer == "saved"
    assert len(output.tool_calls) == 1
    assert any(event.type == "tool_call" for event in events)
    assert any(event.type == "tool_result" for event in events)
    assert any(event.type == "memory_write" for event in events)
    assert len(memories) == 1



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
                    tool_calls=[
                        ToolCall(
                            name="memory_write",
                            arguments={"content": "remember", "tags": ["t"]},
                            tool_call_id="call_test_1",
                        )
                    ],
                )
            return ModelResponse(content="done", tool_calls=[])

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
    assert assistant_tool_call_message["tool_calls"][0]["id"] == "call_test_1"
    assert tool_result_message["tool_call_id"] == "call_test_1"
