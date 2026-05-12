"""Deterministic runtime tests for retrieval agent boundaries."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from app.domain.models import AgentRunInput, RunContext, ToolCall
from app.domain.protocols import ChatModelClient, ModelResponse, StreamChunk
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.file_store import FileMemoryStore
from app.retrieval.service import RetrievalService
from app.runtime.agent_capability import load_agent_capability_registry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.event_recorder import EventRecorder
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.tools.builtins import MemoryWriteTool, RetrievalContextPackTool, RetrievalSearchTool
from app.tools.registry import ToolRegistry
from tests.test_retrieval_service import RetrievalStores, _seed_stores

__all__ = []


@dataclass(slots=True)
class RetrievalFlowBundle:
    runtime: AgentRuntime
    stores: RetrievalStores
    memory_manager: MemoryManager


class RecallPreviousApplicationModel:
    """Drive a no-id user request through retrieval_context_pack."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        assert "RetrievalService 用于只读召回" in system_prompt
        tool_names = _tool_names(tools)
        assert "retrieval_search" in tool_names
        assert "retrieval_context_pack" in tool_names
        assert "memory_write" in tool_names
        if not _assistant_called(messages, "retrieval_search"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="retrieval_search",
                        arguments={
                            "query": "根据我之前星河智能岗位准备二面",
                            "source_types": ["career_application"],
                            "top_k": 3,
                        },
                    )
                ],
            )
        if not _assistant_called(messages, "retrieval_context_pack"):
            application_id = _latest_search_hit_id(messages, source_type="career_application")
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="retrieval_context_pack",
                        arguments={
                            "query": "星河智能 RAG 二面准备",
                            "related_application_id": application_id,
                            "source_types": [
                                "career_application",
                                "job_fit_report",
                                "note",
                                "learning_task",
                                "interview_question",
                                "external_resource",
                            ],
                            "top_k": 8,
                            "max_chars": 4000,
                        },
                    )
                ],
            )
        context_pack = _latest_context_pack(messages)
        source_types = {
            hit["source"]["source_type"]
            for hit in context_pack["hits"]
            if isinstance(hit, dict) and isinstance(hit.get("source"), dict)
        }
        assert {"career_application", "job_fit_report", "note", "learning_task"} <= source_types
        return ModelResponse(
            content=(
                "已根据之前的星河智能岗位记录整理二面准备：重点补 RAG 检索评估、"
                "chunk 策略和 Agent Runtime 架构表达。依据来自求职项目、匹配报告、"
                "复盘笔记和学习任务。"
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
            yield StreamChunk()
        raise NotImplementedError("streaming is not used in this test")


def test_main_agent_recalls_product_context_without_user_ids_or_memory_write(tmp_path: Path) -> None:
    bundle = _build_retrieval_flow_bundle(tmp_path, RecallPreviousApplicationModel())

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_alpha",
            user_message="根据我之前星河智能岗位准备二面，不用我提供 ID。",
            skill_names=["base", "tools", "memory"],
            max_tool_rounds=2,
            context=_context("sess_alpha"),
        )
    )
    events = bundle.stores.sessions.list_events("sess_alpha")

    assert "星河智能" in output.answer
    assert "RAG" in output.answer
    assert "retrieval_search" in _tool_call_names(events)
    assert "retrieval_context_pack" in _tool_call_names(events)
    assert "memory_write" not in _tool_call_names(events)
    assert bundle.memory_manager.search(query="星河智能", limit=5, context=_context("sess_alpha")) == []


def test_retrieval_contract_and_capabilities_are_main_agent_only() -> None:
    main_doc = Path("app/agents/default/AGENT.md").read_text(encoding="utf-8")
    capability = load_agent_capability_registry(Path("app/config/agent_capabilities.json"))
    main_capability = capability.require("agent_main")
    resume_capability = capability.require("resume_agent")
    job_capability = capability.require("job_agent")

    assert "RetrievalService 用于只读召回 Career、Note、Knowledge、Learning 和当前 SessionArtifact" in main_doc
    assert "优先调用 `retrieval_context_pack` 获取可追溯上下文" in main_doc
    assert "Retrieval 工具只读，不会也不应该触发 memory 写入" in main_doc
    assert "`resume_agent` 和 `job_agent` 默认不调用全局 RetrievalService" in main_doc
    assert main_capability.allows_tool("retrieval_search")
    assert main_capability.allows_tool("retrieval_context_pack")
    assert not resume_capability.allows_tool("retrieval_search")
    assert not resume_capability.allows_tool("retrieval_context_pack")
    assert not job_capability.allows_tool("retrieval_search")
    assert not job_capability.allows_tool("retrieval_context_pack")


def _build_retrieval_flow_bundle(tmp_path: Path, model_client: ChatModelClient) -> RetrievalFlowBundle:
    stores = _seed_stores(tmp_path)
    capability_registry = load_agent_capability_registry(Path("app/config/agent_capabilities.json"))
    memory_store = FileMemoryStore(root_dir=tmp_path / "memory")
    memory_manager = MemoryManager(capability_registry=capability_registry, memory_store=memory_store)
    state_manager = StateManager(store=JsonlFileStateStore(root_dir=tmp_path / "state"))
    tool_registry = ToolRegistry(capability_registry=capability_registry)
    retrieval_service = RetrievalService(
        career_store=stores.career,
        note_store=stores.notes,
        knowledge_store=stores.knowledge,
        learning_store=stores.learning,
        session_repository=stores.sessions,
    )
    tool_registry.register(MemoryWriteTool(memory_manager=memory_manager))
    tool_registry.register(RetrievalSearchTool(retrieval_service=retrieval_service))
    tool_registry.register(RetrievalContextPackTool(retrieval_service=retrieval_service))
    context_assembler = ContextAssembler(
        session_repository=stores.sessions,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=MarkdownAgentDocumentRepository(agents_dir=Path("app/agents")),
        memory_manager=memory_manager,
        state_manager=state_manager,
        tool_executor=tool_registry,
    )
    runtime = AgentRuntime(
        session_manager=SessionManager(session_repository=stores.sessions),
        event_recorder=EventRecorder(session_repository=stores.sessions),
        context_assembler=context_assembler,
        model_client=model_client,
        tool_executor=tool_registry,
    )
    return RetrievalFlowBundle(runtime=runtime, stores=stores, memory_manager=memory_manager)


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


def _latest_context_pack(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        payload = json.loads(content)
        if isinstance(payload, dict) and isinstance(payload.get("context_pack"), dict):
            return cast(dict[str, Any], payload["context_pack"])
    raise AssertionError("context_pack tool result was not found")


def _latest_search_hit_id(messages: list[dict[str, Any]], *, source_type: str) -> str:
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        payload = json.loads(content)
        if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
            continue
        for hit in payload["hits"]:
            if not isinstance(hit, dict) or not isinstance(hit.get("source"), dict):
                continue
            source = hit["source"]
            if source.get("source_type") == source_type and isinstance(source.get("source_id"), str):
                return cast(str, source["source_id"])
    raise AssertionError(f"{source_type} search hit was not found")


def _tool_call_names(events: list[Any]) -> list[str]:
    names: list[str] = []
    for event in events:
        if event.type != "tool_call":
            continue
        name = event.payload.get("name")
        if isinstance(name, str):
            names.append(name)
    return names
