"""Application service dependency providers."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.api.dependencies.config import get_settings
from app.api.dependencies.infrastructure import (
    get_career_product_store,
    get_graph_agent_task_store,
    get_lock_manager,
    get_session_repository,
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
)
from app.api.dependencies.model import get_model_client
from app.api.dependencies.runtime import get_agent_runtime, get_workflow_runtime_guard
from app.api.dependencies.tools import get_tool_registry
from app.runtime.agent.tool_gateway import ToolGateway
from app.runtime.langgraph import (
    INTERVIEW_REVIEW_WORKFLOW_ID,
    MULTI_AGENT_CAREER_WORKFLOW_ID,
    RAG_NOTE_WORKFLOW_ID,
    InterviewReviewWorkflowRunner,
    MultiAgentCareerWorkflowRunner,
    RagNoteWorkflowRunner,
    WorkflowRouter,
    WorkflowRunnerDispatcher,
)
from app.infra.storage.jsonl_agent_task_store import JsonlAgentTaskStore
from app.services.agent_invocation_service import AgentInvocationService
from app.services.agent_task_runtime import AgentTaskRuntime
from app.services.answer_normalizer import AnswerNormalizer
from app.services.chat_service import ChatService
from app.services.graph_agent_task_executor import GraphAgentTaskExecutor
from app.services.graph_agent_task_output_validator import GraphAgentTaskOutputValidator
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
    "get_graph_agent_task_executor",
    "get_memory_query_service",
    "get_interview_review_workflow_runner",
    "get_multi_agent_career_workflow_runner",
    "get_rag_note_workflow_runner",
    "get_session_artifact_service",
    "get_session_query_service",
    "get_session_title_service",
    "get_workflow_runner_dispatcher",
    "get_workflow_router",
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
def get_graph_agent_task_executor() -> GraphAgentTaskExecutor:
    settings = get_settings()
    return GraphAgentTaskExecutor(
        invocation_service=get_agent_invocation_service(),
        task_store=get_graph_agent_task_store(),
        task_context_builder=TaskContextBuilder(
            session_repository=get_session_repository(),
            career_store=get_career_product_store(),
        ),
        output_validator=GraphAgentTaskOutputValidator(
            career_store=get_career_product_store(),
            session_repository=get_session_repository(),
        ),
        lease_ttl_seconds=settings.langgraph_task_lease_ttl_seconds,
    )


@lru_cache(maxsize=1)
def get_answer_normalizer() -> AnswerNormalizer:
    return AnswerNormalizer()


@lru_cache(maxsize=1)
def get_session_title_service() -> SessionTitleService:
    return SessionTitleService(model_client=get_model_client())


@lru_cache(maxsize=1)
def get_workflow_router() -> WorkflowRouter:
    settings = get_settings()
    return WorkflowRouter(
        enabled=settings.langgraph_workflow_enabled,
        interactive_note_enabled=settings.langgraph_interactive_note_enabled,
        interactive_interview_review_enabled=settings.langgraph_interactive_interview_review_enabled,
        multi_agent_career_enabled=settings.langgraph_multi_agent_career_enabled,
    )


@lru_cache(maxsize=1)
def get_rag_note_workflow_runner() -> RagNoteWorkflowRunner:
    settings = get_settings()
    return RagNoteWorkflowRunner(
        tool_gateway=_build_workflow_tool_gateway(),
        model_client=get_model_client(),
        event_recorder=get_event_recorder(),
        workflow_store=get_workflow_instance_store(),
        checkpoint_backend=settings.langgraph_workflow_backend,
        checkpoint_path=settings.langgraph_checkpoint_path,
        node_timeout_seconds=settings.langgraph_node_timeout_seconds,
        draft_node_timeout_seconds=settings.resolved_langgraph_draft_node_timeout_seconds(),
        node_retry_attempts=settings.langgraph_node_retry_attempts,
    )


@lru_cache(maxsize=1)
def get_interview_review_workflow_runner() -> InterviewReviewWorkflowRunner:
    settings = get_settings()
    return InterviewReviewWorkflowRunner(
        tool_gateway=_build_workflow_tool_gateway(),
        model_client=get_model_client(),
        event_recorder=get_event_recorder(),
        workflow_store=get_workflow_instance_store(),
        checkpoint_backend=settings.langgraph_workflow_backend,
        checkpoint_path=settings.langgraph_checkpoint_path,
        node_timeout_seconds=settings.langgraph_node_timeout_seconds,
        draft_node_timeout_seconds=settings.resolved_langgraph_draft_node_timeout_seconds(),
        node_retry_attempts=settings.langgraph_node_retry_attempts,
    )


@lru_cache(maxsize=1)
def get_multi_agent_career_workflow_runner() -> MultiAgentCareerWorkflowRunner:
    settings = get_settings()
    return MultiAgentCareerWorkflowRunner(
        task_executor=get_graph_agent_task_executor(),
        tool_gateway=_build_workflow_tool_gateway(),
        event_recorder=get_event_recorder(),
        session_repository=get_session_repository(),
        career_store=get_career_product_store(),
        workflow_store=get_workflow_instance_store(),
        checkpoint_backend=settings.langgraph_workflow_backend,
        checkpoint_path=settings.langgraph_checkpoint_path,
        node_timeout_seconds=max(
            settings.langgraph_node_timeout_seconds,
            settings.chat_stream_run_timeout_seconds,
        ),
    )


@lru_cache(maxsize=1)
def get_workflow_runner_dispatcher() -> WorkflowRunnerDispatcher:
    settings = get_settings()
    runners: dict[str, Any] = {}
    if settings.langgraph_interactive_note_enabled:
        runners[RAG_NOTE_WORKFLOW_ID] = get_rag_note_workflow_runner()
    if settings.langgraph_interactive_interview_review_enabled:
        runners[INTERVIEW_REVIEW_WORKFLOW_ID] = get_interview_review_workflow_runner()
    if settings.langgraph_multi_agent_career_enabled:
        runners[MULTI_AGENT_CAREER_WORKFLOW_ID] = get_multi_agent_career_workflow_runner()
    return WorkflowRunnerDispatcher(
        runners=runners,
        workflow_store=get_workflow_instance_store(),
        resume_lease_store=get_workflow_resume_lease_store(),
        resume_lease_ttl_seconds=settings.langgraph_resume_lease_ttl_seconds,
    )


def _build_workflow_tool_gateway() -> ToolGateway:
    return ToolGateway(
        tool_executor=get_tool_registry(),
        ledger=get_tool_call_ledger(),
        workflow_guard=get_workflow_runtime_guard(),
    )


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
        workflow_router=get_workflow_router(),
        workflow_runner=get_workflow_runner_dispatcher() if settings.langgraph_workflow_enabled else None,
        stream_heartbeat_interval_seconds=settings.chat_stream_heartbeat_interval_seconds,
        stream_run_timeout_seconds=settings.chat_stream_run_timeout_seconds,
    )
