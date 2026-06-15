"""Aggregate exports for API dependency providers."""

from __future__ import annotations

from app.api.dependencies.config import get_settings
from app.api.dependencies.debug import get_token_usage_debug_service
from app.api.dependencies.infrastructure import (
    get_agent_document_repository,
    get_career_product_store,
    get_knowledge_store,
    get_learning_store,
    get_lock_manager,
    get_memory_store,
    get_note_store,
    get_session_repository,
    get_skill_repository,
    get_state_store,
    get_tool_call_ledger,
    get_workflow_instance_store,
    get_workflow_resume_lease_store,
)
from app.api.dependencies.managers import (
    get_agent_capability_registry,
    get_agent_registry,
    get_event_recorder,
    get_memory_manager,
    get_session_manager,
    get_state_manager,
)
from app.api.dependencies.model import get_maintenance_model_client, get_model_client
from app.api.dependencies.runtime import (
    get_agent_runtime,
    get_context_assembler,
    get_context_compactor,
    get_mid_term_flusher,
    get_mid_term_flush_worker,
)
from app.api.dependencies.retrieval import get_retrieval_service
from app.api.dependencies.services import (
    get_agent_invocation_service,
    get_agent_task_runtime,
    get_agent_task_store,
    get_answer_normalizer,
    get_chat_service,
    get_interview_review_workflow_runner,
    get_memory_query_service,
    get_rag_note_workflow_runner,
    get_session_artifact_service,
    get_session_query_service,
    get_session_title_service,
    get_workflow_runner_dispatcher,
    get_workflow_router,
)
from app.api.dependencies.tools import get_tool_registry

__all__ = [
    "get_agent_capability_registry",
    "get_agent_document_repository",
    "get_agent_invocation_service",
    "get_agent_registry",
    "get_agent_runtime",
    "get_agent_task_runtime",
    "get_agent_task_store",
    "get_answer_normalizer",
    "get_chat_service",
    "get_career_product_store",
    "get_context_assembler",
    "get_context_compactor",
    "get_event_recorder",
    "get_interview_review_workflow_runner",
    "get_knowledge_store",
    "get_learning_store",
    "get_lock_manager",
    "get_memory_manager",
    "get_memory_query_service",
    "get_memory_store",
    "get_mid_term_flusher",
    "get_mid_term_flush_worker",
    "get_rag_note_workflow_runner",
    "get_note_store",
    "get_retrieval_service",
    "get_maintenance_model_client",
    "get_model_client",
    "get_session_manager",
    "get_session_artifact_service",
    "get_session_query_service",
    "get_session_repository",
    "get_session_title_service",
    "get_settings",
    "get_skill_repository",
    "get_state_manager",
    "get_state_store",
    "get_tool_registry",
    "get_tool_call_ledger",
    "get_token_usage_debug_service",
    "get_workflow_instance_store",
    "get_workflow_resume_lease_store",
    "get_workflow_runner_dispatcher",
    "get_workflow_router",
]
