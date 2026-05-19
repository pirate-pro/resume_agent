"""Tests for controlled child-agent invocation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.errors import ValidationError
from app.domain.models import RunContext, SessionArtifact
from app.domain.protocols import ModelResponse, StreamChunk
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.file_store import FileMemoryStore
from app.memory.models import MemoryScope
from app.runtime.agent_capability import AgentCapability, AgentCapabilityRegistry
from app.runtime.agent_events import (
    AGENT_RESULT_SUMMARY_EVENT,
    AGENT_TASK_ASSIGNED_EVENT,
    AGENT_TASK_PROGRESS_EVENT,
)
from app.runtime.agent_registry import AgentRegistry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.event_recorder import EventRecorder
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.services.agent_invocation_service import AgentInvocationRequest, AgentInvocationService
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.tools.registry import ToolRegistry

__all__ = []


def _add_shared_artifact(repository: JsonlSessionRepository, session_id: str, artifact_id: str) -> None:
    root = repository.get_session_root_path(session_id)
    artifact_dir = root / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "original.bin").write_text("resume content", encoding="utf-8")
    (artifact_dir / "content.txt").write_text("resume content", encoding="utf-8")
    now = datetime.now(UTC)
    repository.add_or_update_session_artifact(
        SessionArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            kind="uploaded_file",
            title="resume.txt",
            media_type="text/plain",
            size_bytes=14,
            status="ready",
            visibility="session_shared",
            created_at=now,
            updated_at=now,
            storage_relpath=f"artifacts/{artifact_id}/original.bin",
            text_relpath=f"artifacts/{artifact_id}/content.txt",
            text_char_count=14,
            token_estimate=4,
            parsed_at=now,
        )
    )


class CapturingModelClient:
    """Static model client that records runtime context passed to the model."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": messages,
                "tools": tools,
            }
        )
        return ModelResponse(content=self._content, tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        _ = (system_prompt, messages, tools)
        yield StreamChunk(delta=self._content, finished=False, has_tool_call_delta=False)
        yield StreamChunk(delta="", tool_calls=[], finished=True, has_tool_call_delta=False)


@dataclass(slots=True)
class InvocationBundle:
    service: AgentInvocationService
    assembler: ContextAssembler
    session_repository: JsonlSessionRepository
    model_client: CapturingModelClient


def _write_docs(root: Path, agent_id: str, *, agent_text: str, soul_text: str) -> None:
    agent_dir = root / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENT.md").write_text(agent_text, encoding="utf-8")
    (agent_dir / "SOUL.md").write_text(soul_text, encoding="utf-8")


def _capability_registry() -> AgentCapabilityRegistry:
    return AgentCapabilityRegistry(
        {
            "agent_main": AgentCapability(
                agent_id="agent_main",
                allowed_tools=["*"],
                allowed_skills=["*"],
                default_skills=["base", "memory", "tools"],
                memory_read_scopes=[MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                memory_write_scopes=[MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
            ),
            "resume_agent": AgentCapability(
                agent_id="resume_agent",
                allowed_tools=["memory_search"],
                allowed_skills=["base", "tools", "file-reader"],
                default_skills=["base", "tools", "file-reader"],
                memory_read_scopes=[MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                memory_write_scopes=[MemoryScope.AGENT_LONG],
            ),
        }
    )


def _registry_payload() -> dict[str, object]:
    return {
        "agents": [
            {
                "agent_id": "agent_main",
                "display_name": "MainCareerAgent",
                "description": "主 agent",
                "role": "main_orchestrator",
                "enabled": True,
                "is_main_agent": True,
                "document_agent_id": "default",
                "can_invoke_agents": True,
                "invokable_agent_ids": ["resume_agent"],
            },
            {
                "agent_id": "resume_agent",
                "display_name": "ResumeAgent",
                "description": "简历 agent",
                "role": "resume_parser",
                "enabled": True,
                "is_main_agent": False,
                "document_agent_id": "resume_agent",
                "can_invoke_agents": False,
                "invokable_agent_ids": [],
            },
        ],
    }


def _source_context(session_id: str, *, agent_id: str = "agent_main") -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{agent_id}",
        agent_id=agent_id,
        turn_id=f"turn_{agent_id}",
        entry_agent_id=agent_id,
        parent_run_id=None,
        trace_flags={},
    )


def _build_bundle(tmp_path: Path, *, answer: str = "简历解析完成") -> InvocationBundle:
    session_repository = JsonlSessionRepository(data_dir=tmp_path / "sessions")
    state_manager = StateManager(store=JsonlFileStateStore(root_dir=tmp_path / "state"))
    capability_registry = _capability_registry()
    memory_manager = MemoryManager(
        capability_registry=capability_registry,
        memory_store=FileMemoryStore(root_dir=tmp_path / "memory"),
    )
    agents_dir = tmp_path / "agents"
    _write_docs(agents_dir, "default", agent_text="# Main Agent", soul_text="# Main Soul")
    _write_docs(agents_dir, "resume_agent", agent_text="# Resume Agent", soul_text="# Resume Soul")
    agent_document_repository = MarkdownAgentDocumentRepository(agents_dir=agents_dir)
    tool_registry = ToolRegistry(capability_registry=capability_registry)
    assembler = ContextAssembler(
        session_repository=session_repository,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=agent_document_repository,
        memory_manager=memory_manager,
        state_manager=state_manager,
        tool_executor=tool_registry,
    )
    event_recorder = EventRecorder(session_repository=session_repository)
    model_client = CapturingModelClient(content=answer)
    runtime = AgentRuntime(
        session_manager=SessionManager(session_repository=session_repository),
        event_recorder=event_recorder,
        context_assembler=assembler,
        model_client=model_client,
        tool_executor=tool_registry,
    )
    registry = AgentRegistry.from_payload(
        _registry_payload(),
        capability_registry=capability_registry,
        document_repository=agent_document_repository,
    )
    service = AgentInvocationService(
        agent_registry=registry,
        runtime=runtime,
        event_recorder=event_recorder,
        session_repository=session_repository,
    )
    return InvocationBundle(
        service=service,
        assembler=assembler,
        session_repository=session_repository,
        model_client=model_client,
    )


def test_agent_invocation_records_assignment_child_run_and_result_summary(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_invoke")
    _add_shared_artifact(bundle.session_repository, "sess_invoke", "artifact_resume_001")
    source_context = _source_context("sess_invoke")

    result = bundle.service.invoke(
        AgentInvocationRequest(
            source_context=source_context,
            target_agent_id="resume_agent",
            instruction="解析当前会话里的简历文件",
            constraints=["只输出结构化摘要"],
            artifact_refs=["artifact_resume_001"],
            max_tool_rounds=0,
        )
    )

    orchestration_events = bundle.session_repository.list_orchestration_events("sess_invoke")
    event_types = [event.type for event in orchestration_events]
    task_event_types = [event.type for event in orchestration_events if event.type != "llm_usage"]
    assert result.status == "completed"
    assert result.source_agent_id == "agent_main"
    assert result.target_agent_id == "resume_agent"
    assert result.summary == "简历解析完成"
    assert task_event_types == [
        AGENT_TASK_ASSIGNED_EVENT,
        AGENT_TASK_PROGRESS_EVENT,
        AGENT_TASK_PROGRESS_EVENT,
        AGENT_TASK_PROGRESS_EVENT,
        AGENT_TASK_PROGRESS_EVENT,
        AGENT_RESULT_SUMMARY_EVENT,
    ]
    usage_events = [event for event in orchestration_events if event.type == "llm_usage"]
    assert len(usage_events) == 1
    assert usage_events[0].agent_id == "resume_agent"
    assert usage_events[0].run_id == result.child_run_id
    assert usage_events[0].parent_run_id == "run_agent_main"
    assert usage_events[0].payload["operation"] == "model.generate"
    assert usage_events[0].payload["total_tokens"] > 0
    progress_events = [event for event in orchestration_events if event.type == AGENT_TASK_PROGRESS_EVENT]
    assert [event.payload["source_event_type"] for event in progress_events] == [
        "run_started",
        "memory_retrieval",
        "assistant_message",
        "run_finished",
    ]
    assert progress_events[-1].payload["status"] == "completed"

    assignment = orchestration_events[0]
    assert assignment.agent_id == "agent_main"
    assert assignment.run_id == "run_agent_main"
    assert assignment.payload["target_agent_id"] == "resume_agent"
    assert assignment.payload["instruction"] == "解析当前会话里的简历文件"

    child_events = bundle.session_repository.list_agent_events("sess_invoke", "resume_agent")
    assert [event.type for event in child_events] == [
        "run_started",
        "user_message",
        "memory_retrieval",
        "llm_usage",
        "assistant_message",
        "run_finished",
        AGENT_RESULT_SUMMARY_EVENT,
    ]
    assert all(event.agent_id == "resume_agent" for event in child_events)
    assert all(event.run_id == result.child_run_id for event in child_events)
    assert all(event.parent_run_id == "run_agent_main" for event in child_events)

    summary = orchestration_events[-1]
    assert summary.agent_id == "resume_agent"
    assert summary.parent_run_id == "run_agent_main"
    assert summary.payload["target_agent_id"] == "agent_main"
    assert summary.payload["summary"] == "简历解析完成"


def test_agent_invocation_rejects_disallowed_direction(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_reject")

    with pytest.raises(ValidationError, match="not allowed to invoke"):
        bundle.service.invoke(
            AgentInvocationRequest(
                source_context=_source_context("sess_reject", agent_id="resume_agent"),
                target_agent_id="agent_main",
                instruction="反向调用主 agent",
            )
        )


def test_agent_invocation_child_prompt_contains_assigned_task(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_child_prompt")

    bundle.service.invoke(
        AgentInvocationRequest(
            source_context=_source_context("sess_child_prompt"),
            target_agent_id="resume_agent",
            instruction="提取简历中的项目经历",
            constraints=["不要生成求职建议"],
            max_tool_rounds=0,
        )
    )

    assert len(bundle.model_client.calls) == 1
    prompt = bundle.model_client.calls[0]["system_prompt"]
    assert "AGENT.md:\n# Resume Agent" in prompt
    assert "Assigned agent tasks:" in prompt
    assert "task_id=" in prompt
    assert "instruction=提取简历中的项目经历" in prompt
    assert "constraints: 不要生成求职建议" in prompt
    assert "Main orchestration state:" not in prompt


def test_agent_invocation_rejects_unallowed_child_skill(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_child_skill")

    with pytest.raises(ValidationError, match="Skill not allowed"):
        bundle.service.invoke(
            AgentInvocationRequest(
                source_context=_source_context("sess_child_skill"),
                target_agent_id="resume_agent",
                instruction="提取简历中的项目经历",
                skill_names=["memory-editor"],
                max_tool_rounds=0,
            )
        )


def test_agent_invocation_result_summary_is_visible_to_main_context(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path, answer="resume_agent 已完成项目经历提取")
    bundle.session_repository.create_session("sess_main_prompt")

    bundle.service.invoke(
        AgentInvocationRequest(
            source_context=_source_context("sess_main_prompt"),
            target_agent_id="resume_agent",
            instruction="提取简历中的项目经历",
            max_tool_rounds=0,
        )
    )

    main_bundle = bundle.assembler.assemble(
        context=_source_context("sess_main_prompt"),
        user_message="汇总子 agent 结果",
        skill_names=["base"],
    )

    assert "Child agent result summaries:" in main_bundle.system_prompt
    assert "agent=resume_agent status=completed" in main_bundle.system_prompt
    assert "resume_agent 已完成项目经历提取" in main_bundle.system_prompt
