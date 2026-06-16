"""Shared types for LangGraph workflow execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from operator import add
from typing import Annotated, Any, Literal, TypedDict

from app.core.errors import ValidationError
from app.domain.models import AgentRunOutput, RunContext, ToolCall

__all__ = [
    "INTERVIEW_REVIEW_WORKFLOW_ID",
    "InterviewReviewGraphState",
    "MULTI_AGENT_CAREER_WORKFLOW_ID",
    "MultiAgentCareerGraphState",
    "RAG_NOTE_WORKFLOW_ID",
    "WorkflowGraphRunResult",
    "WorkflowGraphState",
    "WorkflowResumePayload",
    "WorkflowResumeRequest",
]

RAG_NOTE_WORKFLOW_ID = "rag.note.write.interactive.v1"
INTERVIEW_REVIEW_WORKFLOW_ID = "interview.review.update.interactive.v1"
MULTI_AGENT_CAREER_WORKFLOW_ID = "career.intake.analysis.interactive.v1"


class WorkflowGraphState(TypedDict, total=False):
    """LangGraph state for interactive workflow execution."""

    session_id: str
    run_id: str
    workflow_instance_id: str
    thread_id: str
    contract_id: str
    user_goal: str
    phase: str
    known_refs: dict[str, Any]
    retrieval_candidates: list[dict[str, Any]]
    selected_source_refs: list[dict[str, Any]]
    user_supplement: str | None
    context_pack: dict[str, Any] | None
    draft_note: dict[str, Any] | None
    pending_question: dict[str, Any] | None
    retry_counters: dict[str, int]
    last_error: dict[str, Any] | None
    outputs: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    answer: str


class InterviewReviewGraphState(WorkflowGraphState, total=False):
    """State reserved for the interactive interview-review workflow."""

    application_candidates: list[dict[str, Any]]
    selected_application_id: str | None
    review_facts: dict[str, Any]
    note_draft: dict[str, Any] | None
    application_update_preview: dict[str, Any] | None
    update_fields: list[str]
    save_note: bool
    update_application: bool


class MultiAgentCareerGraphState(WorkflowGraphState, total=False):
    """State for the code-owned multi-agent career intake workflow."""

    resume_artifact_id: str | None
    jd_artifact_id: str | None
    selected_career_profile_id: str | None
    task_specs: dict[str, dict[str, Any]]
    task_execution_keys: dict[str, str]
    task_attempts: dict[str, int]
    task_results: dict[str, dict[str, Any]]
    task_updates: Annotated[list[dict[str, Any]], add]
    failed_task_keys: list[str]
    retry_task_keys: list[str]
    input_candidates: list[dict[str, Any]]
    project_preview: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class WorkflowResumePayload:
    """Validated user input for resuming an interrupted workflow."""

    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.payload, dict):
            raise ValidationError("workflow resume payload must be an object.")


@dataclass(frozen=True, slots=True)
class WorkflowResumeRequest:
    """Internal request to resume a workflow graph thread."""

    session_id: str
    workflow_instance_id: str
    payload: WorkflowResumePayload
    context: RunContext
    expected_version: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        if not isinstance(self.workflow_instance_id, str) or not self.workflow_instance_id.strip():
            raise ValidationError("workflow_instance_id must be a non-empty string.")
        if not isinstance(self.payload, WorkflowResumePayload):
            raise ValidationError("payload must be WorkflowResumePayload.")
        if not isinstance(self.context, RunContext):
            raise ValidationError("context must be RunContext.")
        if self.expected_version is not None and self.expected_version <= 0:
            raise ValidationError("expected_version must be positive when provided.")

    @property
    def thread_id(self) -> str:
        return f"{self.session_id.strip()}:{self.workflow_instance_id.strip()}"


@dataclass(frozen=True, slots=True)
class WorkflowGraphRunResult:
    """Result returned by a graph workflow run or resume."""

    handled: bool
    output: AgentRunOutput | None = None
    status: Literal["completed", "interrupted", "failed", "cancelled", "skipped"] = "skipped"
    workflow_instance_id: str | None = None
    thread_id: str | None = None
    interrupt_payload: dict[str, Any] | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.handled and self.output is None:
            raise ValidationError("handled workflow result must include output.")
