"""Dependency graph wiring for API layer."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.settings import Settings
from app.infra.llm.openai_compatible_client import OpenAICompatibleClient
from app.infra.locks.session_lock_manager import SessionLockManager
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.file_store import FileMemoryStore
from app.runtime.agent_capability import AgentCapabilityRegistry, load_agent_capability_registry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.context_compactor import ContextCompactionConfig, ContextCompactor, RetentionStrategy
from app.runtime.event_recorder import EventRecorder
from app.runtime.mid_term_flusher import MidTermFlusher
from app.runtime.mid_term_flush_worker import MidTermFlushWorker
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.services.chat_service import ChatService
from app.services.session_title_service import SessionTitleService
from app.tools.builtins import (
    MemoryExplainTool,
    MemoryForgetTool,
    MemoryInspectTool,
    MemorySearchTool,
    MemoryUpdateTool,
    MemoryWriteTool,
    SessionListFilesTool,
    SessionPlanFileAccessTool,
    SessionReadFileTool,
    SessionSearchFileTool,
    StateListTool,
    StatePublishTool,
    StateSetTool,
    WorkspaceReadFileTool,
    WorkspaceWriteFileTool,
)
from app.tools.registry import ToolRegistry

__all__ = [
    "get_agent_runtime",
    "get_agent_document_repository",
    "get_chat_service",
    "get_context_assembler",
    "get_event_recorder",
    "get_agent_capability_registry",
    "get_lock_manager",
    "get_memory_manager",
    "get_mid_term_flusher",
    "get_mid_term_flush_worker",
    "get_model_client",
    "get_memory_store",
    "get_state_manager",
    "get_state_store",
    "get_session_manager",
    "get_session_repository",
    "get_session_title_service",
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
def get_memory_store() -> FileMemoryStore:
    settings = get_settings()
    return FileMemoryStore(root_dir=settings.data_dir / "memory")


@lru_cache(maxsize=1)
def get_state_store() -> JsonlFileStateStore:
    settings = get_settings()
    return JsonlFileStateStore(root_dir=settings.data_dir / "state_v1")


@lru_cache(maxsize=1)
def get_state_manager() -> StateManager:
    return StateManager(store=get_state_store())


@lru_cache(maxsize=1)
def get_agent_capability_registry() -> AgentCapabilityRegistry:
    settings = get_settings()
    return load_agent_capability_registry(settings.agent_capabilities_path)


@lru_cache(maxsize=1)
def get_skill_repository() -> MarkdownSkillRepository:
    skills_dir = Path(__file__).resolve().parents[1] / "skills"
    return MarkdownSkillRepository(skills_dir=skills_dir)


@lru_cache(maxsize=1)
def get_agent_document_repository() -> MarkdownAgentDocumentRepository:
    agents_dir = Path(__file__).resolve().parents[1] / "agents"
    return MarkdownAgentDocumentRepository(agents_dir=agents_dir)


@lru_cache(maxsize=1)
def get_tool_registry() -> ToolRegistry:
    registry = ToolRegistry(capability_registry=get_agent_capability_registry())
    registry.register(MemoryWriteTool(memory_manager=get_memory_manager()))
    registry.register(MemorySearchTool(memory_manager=get_memory_manager()))
    registry.register(MemoryInspectTool(memory_manager=get_memory_manager()))
    registry.register(MemoryExplainTool())
    registry.register(MemoryForgetTool(memory_manager=get_memory_manager()))
    registry.register(MemoryUpdateTool(memory_manager=get_memory_manager()))
    registry.register(StateSetTool(state_manager=get_state_manager()))
    registry.register(StatePublishTool(state_manager=get_state_manager()))
    registry.register(StateListTool(state_manager=get_state_manager()))
    registry.register(WorkspaceWriteFileTool(session_repository=get_session_repository()))
    registry.register(WorkspaceReadFileTool(session_repository=get_session_repository()))
    registry.register(SessionListFilesTool(session_repository=get_session_repository()))
    registry.register(SessionPlanFileAccessTool(session_repository=get_session_repository()))
    registry.register(SessionReadFileTool(session_repository=get_session_repository()))
    registry.register(SessionSearchFileTool(session_repository=get_session_repository()))
    return registry


@lru_cache(maxsize=1)
def get_memory_manager() -> MemoryManager:
    return MemoryManager(
        capability_registry=get_agent_capability_registry(),
        memory_store=get_memory_store(),
    )


@lru_cache(maxsize=1)
def get_session_manager() -> SessionManager:
    return SessionManager(session_repository=get_session_repository())


@lru_cache(maxsize=1)
def get_event_recorder() -> EventRecorder:
    return EventRecorder(session_repository=get_session_repository())


@lru_cache(maxsize=1)
def get_mid_term_flusher() -> MidTermFlusher:
    settings = get_settings()
    return MidTermFlusher(
        session_repository=get_session_repository(),
        memory_store=get_memory_store(),
        model_client=get_model_client(),
        model_context_window_tokens=settings.mid_term_flush_model_context_window_tokens,
        model_input_ratio=settings.mid_term_flush_input_ratio,
        model_output_reserve_tokens=settings.mid_term_flush_output_reserve_tokens,
        prompt_overhead_tokens=settings.mid_term_flush_prompt_overhead_tokens,
        max_input_tokens=settings.mid_term_flush_max_input_tokens,
    )


@lru_cache(maxsize=1)
def get_mid_term_flush_worker() -> MidTermFlushWorker:
    settings = get_settings()
    return MidTermFlushWorker(
        flusher=get_mid_term_flusher(),
        poll_interval_seconds=settings.mid_term_flush_worker_poll_interval_seconds,
        max_agents_per_tick=settings.mid_term_flush_worker_max_agents_per_tick,
        max_jobs_per_agent=settings.mid_term_flush_worker_max_jobs_per_agent,
    )


@lru_cache(maxsize=1)
def get_context_compactor() -> ContextCompactor:
    settings = get_settings()
    return ContextCompactor(
        session_repository=get_session_repository(),
        model_client=get_model_client(),
        config=ContextCompactionConfig(
            enabled=settings.context_compaction_enabled,
            trigger_event_count=settings.context_compaction_trigger_event_count,
            trigger_token_count=settings.context_compaction_trigger_token_count,
            trigger_context_window_ratio=settings.context_compaction_trigger_context_window_ratio,
            model_context_window_tokens=settings.context_compaction_model_context_window_tokens,
            retention_strategy=RetentionStrategy(settings.context_compaction_retention_strategy),
            retain_event_count=settings.context_compaction_retain_event_count,
            retain_token_count=settings.context_compaction_retain_token_count,
            retain_context_window_ratio=settings.context_compaction_retain_context_window_ratio,
            model_input_ratio=settings.context_compaction_model_input_ratio,
            model_output_reserve_tokens=settings.context_compaction_model_output_reserve_tokens,
            prompt_overhead_tokens=settings.context_compaction_prompt_overhead_tokens,
        ),
    )


@lru_cache(maxsize=1)
def get_context_assembler() -> ContextAssembler:
    return ContextAssembler(
        session_repository=get_session_repository(),
        skill_repository=get_skill_repository(),
        agent_document_repository=get_agent_document_repository(),
        memory_manager=get_memory_manager(),
        state_manager=get_state_manager(),
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
def get_session_title_service() -> SessionTitleService:
    return SessionTitleService(model_client=get_model_client())


@lru_cache(maxsize=1)
def get_agent_runtime() -> AgentRuntime:
    return AgentRuntime(
        session_manager=get_session_manager(),
        event_recorder=get_event_recorder(),
        context_assembler=get_context_assembler(),
        model_client=get_model_client(),
        tool_executor=get_tool_registry(),
        mid_term_flusher=get_mid_term_flusher(),
        context_compactor=get_context_compactor(),
    )


@lru_cache(maxsize=1)
def get_lock_manager() -> SessionLockManager:
    return SessionLockManager()


@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    settings = get_settings()
    return ChatService(
        runtime=get_agent_runtime(),
        session_manager=get_session_manager(),
        session_repository=get_session_repository(),
        memory_manager=get_memory_manager(),
        capability_registry=get_agent_capability_registry(),
        session_lock_manager=get_lock_manager(),
        session_title_service=get_session_title_service(),
        stream_heartbeat_interval_seconds=settings.chat_stream_heartbeat_interval_seconds,
        stream_run_timeout_seconds=settings.chat_stream_run_timeout_seconds,
    )
