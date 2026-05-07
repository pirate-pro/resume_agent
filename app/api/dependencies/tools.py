"""Tool registry dependency providers."""

from __future__ import annotations

from functools import lru_cache

from app.api.dependencies.infrastructure import get_session_repository
from app.api.dependencies.managers import get_agent_capability_registry, get_memory_manager, get_state_manager
from app.services.agent_task_runtime import AgentTaskRuntime
from app.tools.builtins import (
    DelegateAgentsTool,
    MemoryExplainTool,
    MemoryForgetTool,
    MemoryInspectTool,
    MemorySearchTool,
    MemoryUpdateTool,
    MemoryWriteTool,
    SessionListArtifactsTool,
    SessionPlanArtifactAccessTool,
    SessionReadArtifactTool,
    SessionSearchArtifactTool,
    StateListTool,
    StatePublishTool,
    StateSetTool,
    PublishArtifactTool,
    WorkspaceReadFileTool,
    WorkspaceWriteFileTool,
)
from app.tools.registry import ToolRegistry

__all__ = ["get_tool_registry"]


@lru_cache(maxsize=1)
def get_tool_registry() -> ToolRegistry:
    registry = ToolRegistry(capability_registry=get_agent_capability_registry())
    registry.register(DelegateAgentsTool(agent_task_runtime_provider=_get_agent_task_runtime_lazy))
    registry.register(MemoryWriteTool(memory_manager=get_memory_manager()))
    registry.register(MemorySearchTool(memory_manager=get_memory_manager()))
    registry.register(MemoryInspectTool(memory_manager=get_memory_manager()))
    registry.register(MemoryExplainTool())
    registry.register(MemoryForgetTool(memory_manager=get_memory_manager()))
    registry.register(MemoryUpdateTool(memory_manager=get_memory_manager()))
    registry.register(StateSetTool(state_manager=get_state_manager()))
    registry.register(StatePublishTool(state_manager=get_state_manager()))
    registry.register(StateListTool(state_manager=get_state_manager()))
    registry.register(PublishArtifactTool(session_repository=get_session_repository()))
    registry.register(WorkspaceWriteFileTool(session_repository=get_session_repository()))
    registry.register(WorkspaceReadFileTool(session_repository=get_session_repository()))
    registry.register(SessionListArtifactsTool(session_repository=get_session_repository()))
    registry.register(SessionPlanArtifactAccessTool(session_repository=get_session_repository()))
    registry.register(SessionReadArtifactTool(session_repository=get_session_repository()))
    registry.register(SessionSearchArtifactTool(session_repository=get_session_repository()))
    return registry


def _get_agent_task_runtime_lazy() -> AgentTaskRuntime:
    from app.api.dependencies.services import get_agent_task_runtime

    return get_agent_task_runtime()
