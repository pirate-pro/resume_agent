"""Runtime dependency providers."""

from __future__ import annotations

from functools import lru_cache

from app.api.dependencies.config import get_settings
from app.api.dependencies.infrastructure import (
    get_agent_document_repository,
    get_memory_store,
    get_session_repository,
    get_skill_repository,
)
from app.api.dependencies.managers import (
    get_agent_registry,
    get_event_recorder,
    get_memory_manager,
    get_session_manager,
    get_state_manager,
)
from app.api.dependencies.model import get_maintenance_model_client, get_model_client
from app.api.dependencies.tools import get_tool_registry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.context_compactor import ContextCompactionConfig, ContextCompactor, RetentionStrategy
from app.runtime.mid_term_flusher import MidTermFlusher
from app.runtime.mid_term_flush_worker import MidTermFlushWorker

__all__ = [
    "get_agent_runtime",
    "get_context_assembler",
    "get_context_compactor",
    "get_mid_term_flusher",
    "get_mid_term_flush_worker",
]


@lru_cache(maxsize=1)
def get_mid_term_flusher() -> MidTermFlusher:
    settings = get_settings()
    return MidTermFlusher(
        session_repository=get_session_repository(),
        memory_store=get_memory_store(),
        model_client=get_maintenance_model_client(),
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
        model_client=get_maintenance_model_client(),
        coverage_checker=get_mid_term_flusher(),
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
    settings = get_settings()
    return ContextAssembler(
        session_repository=get_session_repository(),
        skill_repository=get_skill_repository(),
        agent_document_repository=get_agent_document_repository(),
        memory_manager=get_memory_manager(),
        state_manager=get_state_manager(),
        tool_executor=get_tool_registry(),
        agent_registry=get_agent_registry(),
        tool_schema_disclosure_mode=settings.tool_schema_disclosure_mode,
        tool_schema_always_visible=settings.tool_schema_always_visible,
    )


@lru_cache(maxsize=1)
def get_agent_runtime() -> AgentRuntime:
    settings = get_settings()
    return AgentRuntime(
        session_manager=get_session_manager(),
        event_recorder=get_event_recorder(),
        context_assembler=get_context_assembler(),
        model_client=get_model_client(),
        tool_executor=get_tool_registry(),
        mid_term_flusher=get_mid_term_flusher(),
        context_compactor=get_context_compactor(),
        tool_schema_disclosure_mode=settings.tool_schema_disclosure_mode,
        tool_schema_always_visible=settings.tool_schema_always_visible,
        tool_context_window_mode=settings.tool_context_window_mode,
    )
