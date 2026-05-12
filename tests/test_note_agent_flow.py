"""Deterministic runtime tests for NoteService agent boundaries."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import ValidationError
from app.domain.models import AgentRunInput, RunContext, ToolCall
from app.domain.protocols import ChatModelClient, ModelResponse, StreamChunk
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.file_store import FileMemoryStore
from app.notes.store import NoteStore
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
    MemoryWriteTool,
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


@dataclass(slots=True)
class NoteFlowBundle:
    runtime: AgentRuntime
    session_repository: JsonlSessionRepository
    note_store: NoteStore
    memory_manager: MemoryManager


class SaveReportAsNoteModel:
    """Drive an explicit save-as-note request with deterministic tool calls."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = system_prompt
        assert "note_create" in _tool_names(tools)
        if not _assistant_called(messages, "session_create_text_artifact"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="session_create_text_artifact",
                        arguments={
                            "title": "投递前检查报告.md",
                            "content": "# 投递前检查\n\nRAG 项目证据不足，先补充再投递。",
                            "kind": "generated_file",
                            "media_type": "text/markdown",
                        },
                    )
                ],
            )
        if not _assistant_called(messages, "note_create"):
            artifact_id = _latest_artifact_id(messages)
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="note_create",
                        arguments={
                            "note_id": "star_agent_review",
                            "source_artifact_id": artifact_id,
                            "evidence_refs": ["application_alpha", artifact_id],
                            "title": "星河智能投递前检查复盘",
                            "body_markdown": "## 结论\n先补 RAG 项目证据，再投递。",
                            "tags": ["投递前检查", "RAG"],
                            "related_application_id": "application_alpha",
                            "source_refs": [
                                {
                                    "source_type": "artifact",
                                    "source_id": artifact_id,
                                    "source_session_id": "sess_note_save",
                                    "title": "投递前检查报告",
                                }
                            ],
                            "summary": "投递前需要补齐 RAG 项目证据。",
                        },
                    )
                ],
            )
        return ModelResponse(content="已保存为笔记。", tool_calls=[])

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


class RememberPreferenceModel:
    """Drive a long-term preference request through memory, not notes."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = system_prompt
        assert "memory_write" in _tool_names(tools)
        if not _assistant_called(messages, "memory_write"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="memory_write",
                        arguments={
                            "content": "用户长期目标：优先投 AI 应用后端岗位。",
                            "tags": ["preference", "long_term"],
                        },
                    )
                ],
            )
        return ModelResponse(content="已记住你的长期目标。", tool_calls=[])

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


class PlainCareerAnswerModel:
    """Return an ordinary answer without writing notes or memory."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = (system_prompt, messages, tools)
        return ModelResponse(content="已完成简历诊断说明。", tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        _ = (system_prompt, messages, tools)
        yield StreamChunk(delta="已完成简历诊断说明。", finished=False, has_tool_call_delta=False)
        yield StreamChunk(delta="", tool_calls=[], finished=True, has_tool_call_delta=False)


def test_explicit_save_as_note_flow_creates_note_without_memory_write(tmp_path: Path) -> None:
    bundle = _build_note_flow_bundle(tmp_path, SaveReportAsNoteModel())
    bundle.session_repository.create_session("sess_note_save")

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_note_save",
            user_message="把这份投递前检查报告整理成笔记，后面面试复盘要继续追加。",
            skill_names=["base", "tools", "memory"],
            max_tool_rounds=3,
            context=_context("sess_note_save"),
        )
    )

    note = bundle.note_store.get_note("note_star_agent_review")
    events = bundle.session_repository.list_events("sess_note_save")

    assert output.answer == "已保存为笔记。"
    assert note is not None
    assert note.source_session_id == "sess_note_save"
    assert note.source_artifact_id is not None
    assert note.source_artifact_id in note.evidence_refs
    assert note.related_application_id == "application_alpha"
    assert note.title == "星河智能投递前检查复盘"
    assert bundle.memory_manager.search(query="RAG 项目证据", limit=5, context=_context("sess_note_save")) == []
    assert "note_create" in _tool_call_names(events)
    assert "session_create_text_artifact" in _tool_call_names(events)
    assert "memory_write" not in _tool_call_names(events)
    assert not any(event.type == "memory_write" for event in events)


def test_long_term_preference_flow_writes_memory_but_not_note(tmp_path: Path) -> None:
    bundle = _build_note_flow_bundle(tmp_path, RememberPreferenceModel())
    bundle.session_repository.create_session("sess_memory_goal")

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_memory_goal",
            user_message="记住我以后优先投 AI 应用后端岗位。",
            skill_names=["base", "tools", "memory"],
            max_tool_rounds=2,
            context=_context("sess_memory_goal"),
        )
    )

    memories = bundle.memory_manager.search(query="AI 应用后端", limit=10, context=_context("sess_memory_goal"))
    events = bundle.session_repository.list_events("sess_memory_goal")

    assert output.answer == "已记住你的长期目标。"
    assert any("AI 应用后端" in item.content for item in memories)
    assert bundle.note_store.list_notes(include_archived=True) == []
    assert "memory_write" in _tool_call_names(events)
    assert "note_create" not in _tool_call_names(events)


def test_plain_career_answer_does_not_auto_create_note(tmp_path: Path) -> None:
    bundle = _build_note_flow_bundle(tmp_path, PlainCareerAnswerModel())
    bundle.session_repository.create_session("sess_plain_resume")

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_plain_resume",
            user_message="请诊断这份简历，但不用保存为笔记。",
            skill_names=["base", "tools"],
            max_tool_rounds=2,
            context=_context("sess_plain_resume"),
        )
    )

    assert output.answer == "已完成简历诊断说明。"
    assert bundle.note_store.list_notes(include_archived=True) == []
    assert bundle.memory_manager.search(query="简历诊断", limit=5, context=_context("sess_plain_resume")) == []


def test_note_agent_contract_and_capabilities_keep_note_memory_boundary() -> None:
    main_doc = Path("app/agents/default/AGENT.md").read_text(encoding="utf-8")
    capability = load_agent_capability_registry(Path("app/config/agent_capabilities.json"))
    main_capability = capability.require("agent_main")
    resume_capability = capability.require("resume_agent")
    job_capability = capability.require("job_agent")

    assert "用户明确说“存到笔记 / 保存为笔记 / 整理成笔记" in main_doc
    assert "不要自动创建 Note" in main_doc
    assert "不要在创建 note 后再自动调用 `memory_write`" in main_doc
    assert "如果用户表达“记一下”但无法判断" in main_doc
    assert main_capability.allows_tool("note_create")
    assert main_capability.allows_tool("note_append")
    assert main_capability.allows_tool("memory_write")
    assert not resume_capability.allows_tool("note_create")
    assert not job_capability.allows_tool("note_create")


def _build_note_flow_bundle(tmp_path: Path, model_client: ChatModelClient) -> NoteFlowBundle:
    session_repository = JsonlSessionRepository(data_dir=tmp_path / "sessions")
    note_store = NoteStore(root_dir=tmp_path / "notes")
    memory_store = FileMemoryStore(root_dir=tmp_path / "memory")
    capability_registry = AgentCapabilityRegistry.for_tests()
    memory_manager = MemoryManager(capability_registry=capability_registry, memory_store=memory_store)
    state_store = JsonlFileStateStore(root_dir=tmp_path / "state")
    state_manager = StateManager(store=state_store)
    tool_registry = ToolRegistry(capability_registry=capability_registry)
    tool_registry.register(MemoryWriteTool(memory_manager=memory_manager))
    tool_registry.register(SessionCreateTextArtifactTool(session_repository=session_repository))
    tool_registry.register(NoteCreateTool(note_store=note_store, session_repository=session_repository))
    tool_registry.register(NoteGetTool(note_store=note_store))
    tool_registry.register(NoteListTool(note_store=note_store))
    tool_registry.register(NoteUpdateTool(note_store=note_store, session_repository=session_repository))
    tool_registry.register(NoteAppendTool(note_store=note_store))
    tool_registry.register(NoteArchiveTool(note_store=note_store))
    tool_registry.register(NoteCollectionCreateTool(note_store=note_store))
    tool_registry.register(NoteCollectionGetTool(note_store=note_store))
    tool_registry.register(NoteCollectionListTool(note_store=note_store))
    tool_registry.register(NoteCollectionUpdateTool(note_store=note_store))
    tool_registry.register(NoteCollectionArchiveTool(note_store=note_store))
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
    return NoteFlowBundle(
        runtime=runtime,
        session_repository=session_repository,
        note_store=note_store,
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


def _latest_artifact_id(messages: list[dict[str, Any]]) -> str:
    artifact_ids: list[str] = []
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
        if isinstance(payload, dict):
            artifact_id = payload.get("artifact_id")
            if isinstance(artifact_id, str):
                artifact_ids.append(artifact_id)
    if not artifact_ids:
        raise ValidationError("expected artifact id in deterministic note flow")
    return artifact_ids[-1]


def _tool_call_names(events: list[Any]) -> list[str]:
    names: list[str] = []
    for event in events:
        if event.type != "tool_call":
            continue
        name = event.payload.get("name") if isinstance(event.payload, dict) else None
        if isinstance(name, str):
            names.append(name)
    return names
