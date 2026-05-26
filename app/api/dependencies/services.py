"""Application service dependency providers."""

from __future__ import annotations

from functools import lru_cache

from app.api.dependencies.config import get_settings
from app.api.dependencies.infrastructure import get_career_product_store, get_lock_manager, get_session_repository
from app.api.dependencies.managers import (
    get_agent_capability_registry,
    get_agent_registry,
    get_event_recorder,
    get_memory_manager,
    get_session_manager,
)
from app.api.dependencies.model import get_model_client
from app.api.dependencies.runtime import get_agent_runtime
from app.infra.storage.jsonl_agent_task_store import JsonlAgentTaskStore
from app.services.agent_invocation_service import AgentInvocationService
from app.services.agent_task_runtime import AgentTaskRuntime
from app.services.answer_normalizer import AnswerNormalizer
from app.services.chat_service import ChatService
from app.services.memory_query_service import MemoryQueryService
from app.services.session_artifact_service import SessionArtifactService
from app.services.session_query_service import SessionQueryService
from app.services.session_title_service import SessionTitleService
from app.services.task_context_builder import TaskContextBuilder

__all__ = [
    "get_agent_invocation_service",
    "get_agent_task_runtime",
    "get_agent_task_store",
    "get_answer_normalizer",
    "get_chat_service",
    "get_memory_query_service",
    "get_session_artifact_service",
    "get_session_query_service",
    "get_session_title_service",
]


@lru_cache(maxsize=1)
def get_agent_task_store() -> JsonlAgentTaskStore:
    return JsonlAgentTaskStore(data_dir=get_settings().data_dir)


@lru_cache(maxsize=1)
def get_agent_task_runtime() -> AgentTaskRuntime:
    return AgentTaskRuntime(
        invocation_service=get_agent_invocation_service(),
        task_store=get_agent_task_store(),
        event_recorder=get_event_recorder(),
        task_context_builder=TaskContextBuilder(
            session_repository=get_session_repository(),
            career_store=get_career_product_store(),
        ),
        default_max_concurrency=get_settings().agent_task_max_concurrency,
    )


@lru_cache(maxsize=1)
def get_agent_invocation_service() -> AgentInvocationService:
    return AgentInvocationService(
        agent_registry=get_agent_registry(),
        runtime=get_agent_runtime(),
        event_recorder=get_event_recorder(),
        session_repository=get_session_repository(),
    )


@lru_cache(maxsize=1)
def get_answer_normalizer() -> AnswerNormalizer:
    return AnswerNormalizer()


@lru_cache(maxsize=1)
def get_session_title_service() -> SessionTitleService:
    return SessionTitleService(model_client=get_model_client())


@lru_cache(maxsize=1)
def get_session_query_service() -> SessionQueryService:
    return SessionQueryService(
        session_repository=get_session_repository(),
        session_lock_manager=get_lock_manager(),
        answer_normalizer=get_answer_normalizer(),
    )


@lru_cache(maxsize=1)
def get_session_artifact_service() -> SessionArtifactService:
    return SessionArtifactService(
        session_manager=get_session_manager(),
        session_repository=get_session_repository(),
        session_lock_manager=get_lock_manager(),
        answer_normalizer=get_answer_normalizer(),
    )


@lru_cache(maxsize=1)
def get_memory_query_service() -> MemoryQueryService:
    return MemoryQueryService(memory_manager=get_memory_manager())


@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    settings = get_settings()
    return ChatService(
        runtime=get_agent_runtime(),
        session_manager=get_session_manager(),
        session_repository=get_session_repository(),
        capability_registry=get_agent_capability_registry(),
        session_lock_manager=get_lock_manager(),
        session_title_service=get_session_title_service(),
        answer_normalizer=get_answer_normalizer(),
        stream_heartbeat_interval_seconds=settings.chat_stream_heartbeat_interval_seconds,
        stream_run_timeout_seconds=settings.chat_stream_run_timeout_seconds,
    )
