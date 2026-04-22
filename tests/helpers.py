"""Test helpers and fake model clients."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from app.domain.protocols import ChatModelClient, ModelResponse
from app.infra.locks.session_lock_manager import SessionLockManager
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.facade import FileMemoryFacade
from app.memory.policies import default_memory_policy
from app.memory.stores.jsonl_file_store import JsonlFileMemoryStore
from app.runtime.agent_capability import AgentCapabilityRegistry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.event_recorder import EventRecorder
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.services.chat_service import ChatService
from app.tools.builtins import (
    MemorySearchTool,
    MemoryWriteTool,
    SessionListFilesTool,
    SessionPlanFileAccessTool,
    SessionReadFileTool,
    SessionSearchFileTool,
    WorkspaceReadFileTool,
    WorkspaceWriteFileTool,
)
from app.tools.registry import ToolRegistry

__all__ = [
    "SequenceModelClient",
    "StaticModelClient",
    "build_chat_service",
]


class StaticModelClient:
    """Always return the same model response."""

    def __init__(self, content: str) -> None:
        self._content = content

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = (system_prompt, messages, tools)
        return ModelResponse(content=self._content, tool_calls=[])


class SequenceModelClient:
    """Return a predefined sequence of model responses."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        if not responses:
            raise ValueError("responses cannot be empty")
        self._responses: deque[ModelResponse] = deque(responses)
        self._last_response: ModelResponse = responses[-1]

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = (system_prompt, messages, tools)
        if self._responses:
            self._last_response = self._responses.popleft()
        return self._last_response



def build_chat_service(data_dir: Path, model_client: ChatModelClient) -> tuple[ChatService, MemoryManager]:
    session_repository = JsonlSessionRepository(data_dir=data_dir)
    memory_store = JsonlFileMemoryStore(root_dir=data_dir / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    capability_registry = AgentCapabilityRegistry.for_tests()
    memory_manager = MemoryManager(memory_facade=memory_facade, capability_registry=capability_registry)
    skill_repository = MarkdownSkillRepository(skills_dir=Path("app/skills"))

    tool_registry = ToolRegistry(capability_registry=capability_registry)
    tool_registry.register(MemoryWriteTool(memory_manager=memory_manager))
    tool_registry.register(MemorySearchTool(memory_manager=memory_manager))
    tool_registry.register(WorkspaceWriteFileTool(session_repository=session_repository))
    tool_registry.register(WorkspaceReadFileTool(session_repository=session_repository))
    tool_registry.register(SessionListFilesTool(session_repository=session_repository))
    tool_registry.register(SessionPlanFileAccessTool(session_repository=session_repository))
    tool_registry.register(SessionReadFileTool(session_repository=session_repository))
    tool_registry.register(SessionSearchFileTool(session_repository=session_repository))
    session_manager = SessionManager(session_repository=session_repository)
    event_recorder = EventRecorder(session_repository=session_repository)
    context_assembler = ContextAssembler(
        session_repository=session_repository,
        skill_repository=skill_repository,
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
    service = ChatService(
        runtime=runtime,
        session_manager=session_manager,
        session_repository=session_repository,
        memory_manager=memory_manager,
        capability_registry=capability_registry,
        session_lock_manager=SessionLockManager(),
    )
    return service, memory_manager
