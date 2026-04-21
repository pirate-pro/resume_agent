"""Dependency graph wiring for API layer."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.settings import Settings
from app.infra.llm.openai_compatible_client import OpenAICompatibleClient
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
    "get_agent_runtime",
    "get_chat_service",
    "get_context_assembler",
    "get_event_recorder",
    "get_lock_manager",
    "get_memory_manager",
    "get_memory_repository",
    "get_model_client",
    "get_session_manager",
    "get_session_repository",
    "get_settings",
    "get_skill_repository",
    "get_tool_registry",
]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.load()


@lru_cache(maxsize=1)
def get_session_repository() -> JsonlSessionRepository:
    settings = get_settings()
    return JsonlSessionRepository(data_dir=settings.data_dir)


@lru_cache(maxsize=1)
def get_memory_repository() -> JsonlMemoryRepository:
    settings = get_settings()
    return JsonlMemoryRepository(data_dir=settings.data_dir)


@lru_cache(maxsize=1)
def get_skill_repository() -> MarkdownSkillRepository:
    skills_dir = Path(__file__).resolve().parents[1] / "skills"
    return MarkdownSkillRepository(skills_dir=skills_dir)


@lru_cache(maxsize=1)
def get_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(MemoryWriteTool(memory_repository=get_memory_repository()))
    registry.register(MemorySearchTool(memory_repository=get_memory_repository()))
    registry.register(WorkspaceWriteFileTool(session_repository=get_session_repository()))
    registry.register(WorkspaceReadFileTool(session_repository=get_session_repository()))
    registry.register(SessionListFilesTool(session_repository=get_session_repository()))
    registry.register(SessionPlanFileAccessTool(session_repository=get_session_repository()))
    registry.register(SessionReadFileTool(session_repository=get_session_repository()))
    registry.register(SessionSearchFileTool(session_repository=get_session_repository()))
    return registry


@lru_cache(maxsize=1)
def get_memory_manager() -> MemoryManager:
    return MemoryManager(memory_repository=get_memory_repository())


@lru_cache(maxsize=1)
def get_session_manager() -> SessionManager:
    return SessionManager(session_repository=get_session_repository())


@lru_cache(maxsize=1)
def get_event_recorder() -> EventRecorder:
    return EventRecorder(session_repository=get_session_repository())


@lru_cache(maxsize=1)
def get_context_assembler() -> ContextAssembler:
    return ContextAssembler(
        session_repository=get_session_repository(),
        skill_repository=get_skill_repository(),
        memory_manager=get_memory_manager(),
        tool_executor=get_tool_registry(),
    )


@lru_cache(maxsize=1)
def get_model_client() -> OpenAICompatibleClient:
    settings = get_settings()
    return OpenAICompatibleClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


@lru_cache(maxsize=1)
def get_agent_runtime() -> AgentRuntime:
    return AgentRuntime(
        session_manager=get_session_manager(),
        event_recorder=get_event_recorder(),
        context_assembler=get_context_assembler(),
        model_client=get_model_client(),
        tool_executor=get_tool_registry(),
    )


@lru_cache(maxsize=1)
def get_lock_manager() -> SessionLockManager:
    return SessionLockManager()


@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    return ChatService(
        runtime=get_agent_runtime(),
        session_manager=get_session_manager(),
        session_repository=get_session_repository(),
        memory_manager=get_memory_manager(),
        session_lock_manager=get_lock_manager(),
    )
