"""Domain manager dependency providers."""

from __future__ import annotations

from functools import lru_cache

from app.api.dependencies.config import get_settings
from app.api.dependencies.infrastructure import get_memory_store, get_session_repository, get_state_store
from app.runtime.agent_capability import AgentCapabilityRegistry, load_agent_capability_registry
from app.runtime.event_recorder import EventRecorder
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.state.manager import StateManager

__all__ = [
    "get_agent_capability_registry",
    "get_event_recorder",
    "get_memory_manager",
    "get_session_manager",
    "get_state_manager",
]


@lru_cache(maxsize=1)
def get_state_manager() -> StateManager:
    return StateManager(store=get_state_store())


@lru_cache(maxsize=1)
def get_agent_capability_registry() -> AgentCapabilityRegistry:
    settings = get_settings()
    return load_agent_capability_registry(settings.agent_capabilities_path)


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
