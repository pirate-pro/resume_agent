"""Test helpers and fake model clients."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from app.domain.protocols import ChatModelClient, ModelResponse
from app.infra.locks.session_lock_manager import SessionLockManager
from app.infra.storage.jsonl_memory_repository import JsonlMemoryRepository
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.event_recorder import EventRecorder
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.services.chat_service import ChatService
from app.tools.builtins import MemorySearchTool, MemoryWriteTool, WorkspaceReadFileTool, WorkspaceWriteFileTool
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
    memory_repository = JsonlMemoryRepository(data_dir=data_dir)
    skill_repository = MarkdownSkillRepository(skills_dir=Path("app/skills"))

    tool_registry = ToolRegistry()
    tool_registry.register(MemoryWriteTool(memory_repository=memory_repository))
    tool_registry.register(MemorySearchTool(memory_repository=memory_repository))
    tool_registry.register(WorkspaceWriteFileTool(session_repository=session_repository))
    tool_registry.register(WorkspaceReadFileTool(session_repository=session_repository))

    memory_manager = MemoryManager(memory_repository=memory_repository)
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
        session_lock_manager=SessionLockManager(),
    )
    return service, memory_manager
