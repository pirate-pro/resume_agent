"""Tool registry dependency providers."""

from __future__ import annotations

from functools import lru_cache

from app.domain.agent_task_protocols import AgentTaskStore
from app.api.dependencies.infrastructure import get_career_product_store, get_note_store, get_session_repository
from app.api.dependencies.managers import get_agent_capability_registry, get_memory_manager, get_state_manager
from app.services.agent_task_runtime import AgentTaskRuntime
from app.tools.builtins import (
    AgentTaskStatusTool,
    CareerApplicationCreateTool,
    CareerApplicationGetTool,
    CareerApplicationListTool,
    CareerApplicationMergeTool,
    CareerJobFitReportGetTool,
    CareerJobFitReportListTool,
    CareerJobFitReportSaveTool,
    CareerJDAnalysisGetTool,
    CareerJDAnalysisListTool,
    CareerJDAnalysisSaveTool,
    CareerProfileGetTool,
    CareerProfileMergeTool,
    CareerResumeProfileGetTool,
    CareerResumeProfileListTool,
    CareerResumeProfileSaveTool,
    CareerResumeVersionCreateTool,
    CareerResumeVersionGetTool,
    CareerResumeVersionListTool,
    DelegateAgentsTool,
    MemoryExplainTool,
    MemoryForgetTool,
    MemoryInspectTool,
    MemorySearchTool,
    MemoryUpdateTool,
    MemoryWriteTool,
    NoteAppendTool,
    NoteArchiveTool,
    NoteCollectionArchiveTool,
    NoteCollectionCreateTool,
    NoteCollectionGetTool,
    NoteCollectionListTool,
    NoteCollectionUpdateTool,
    NoteCreateTool,
    NoteGetTool,
    NoteListTool,
    NoteUpdateTool,
    SessionCreateTextArtifactTool,
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
    registry.register(AgentTaskStatusTool(agent_task_store_provider=_get_agent_task_store_lazy))
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
    registry.register(SessionCreateTextArtifactTool(session_repository=get_session_repository()))
    registry.register(SessionListArtifactsTool(session_repository=get_session_repository()))
    registry.register(SessionPlanArtifactAccessTool(session_repository=get_session_repository()))
    registry.register(SessionReadArtifactTool(session_repository=get_session_repository()))
    registry.register(SessionSearchArtifactTool(session_repository=get_session_repository()))
    registry.register(
        CareerResumeProfileSaveTool(
            career_store=get_career_product_store(),
            session_repository=get_session_repository(),
        )
    )
    registry.register(CareerResumeProfileGetTool(career_store=get_career_product_store()))
    registry.register(CareerResumeProfileListTool(career_store=get_career_product_store()))
    registry.register(CareerProfileGetTool(career_store=get_career_product_store()))
    registry.register(
        CareerProfileMergeTool(
            career_store=get_career_product_store(),
            session_repository=get_session_repository(),
        )
    )
    registry.register(
        CareerJDAnalysisSaveTool(
            career_store=get_career_product_store(),
            session_repository=get_session_repository(),
        )
    )
    registry.register(CareerJDAnalysisGetTool(career_store=get_career_product_store()))
    registry.register(CareerJDAnalysisListTool(career_store=get_career_product_store()))
    registry.register(
        CareerJobFitReportSaveTool(
            career_store=get_career_product_store(),
            session_repository=get_session_repository(),
        )
    )
    registry.register(CareerJobFitReportGetTool(career_store=get_career_product_store()))
    registry.register(CareerJobFitReportListTool(career_store=get_career_product_store()))
    registry.register(
        CareerResumeVersionCreateTool(
            career_store=get_career_product_store(),
            session_repository=get_session_repository(),
        )
    )
    registry.register(CareerResumeVersionGetTool(career_store=get_career_product_store()))
    registry.register(CareerResumeVersionListTool(career_store=get_career_product_store()))
    registry.register(
        CareerApplicationCreateTool(
            career_store=get_career_product_store(),
            session_repository=get_session_repository(),
        )
    )
    registry.register(CareerApplicationGetTool(career_store=get_career_product_store()))
    registry.register(CareerApplicationListTool(career_store=get_career_product_store()))
    registry.register(
        CareerApplicationMergeTool(
            career_store=get_career_product_store(),
            session_repository=get_session_repository(),
        )
    )
    registry.register(
        NoteCreateTool(
            note_store=get_note_store(),
            session_repository=get_session_repository(),
        )
    )
    registry.register(NoteGetTool(note_store=get_note_store()))
    registry.register(NoteListTool(note_store=get_note_store()))
    registry.register(
        NoteUpdateTool(
            note_store=get_note_store(),
            session_repository=get_session_repository(),
        )
    )
    registry.register(NoteAppendTool(note_store=get_note_store()))
    registry.register(NoteArchiveTool(note_store=get_note_store()))
    registry.register(NoteCollectionCreateTool(note_store=get_note_store()))
    registry.register(NoteCollectionGetTool(note_store=get_note_store()))
    registry.register(NoteCollectionListTool(note_store=get_note_store()))
    registry.register(NoteCollectionUpdateTool(note_store=get_note_store()))
    registry.register(NoteCollectionArchiveTool(note_store=get_note_store()))
    return registry


def _get_agent_task_runtime_lazy() -> AgentTaskRuntime:
    from app.api.dependencies.services import get_agent_task_runtime

    return get_agent_task_runtime()


def _get_agent_task_store_lazy() -> AgentTaskStore:
    from app.api.dependencies.services import get_agent_task_store

    return get_agent_task_store()
