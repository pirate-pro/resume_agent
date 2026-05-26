"""Domain models for durable multi-agent task coordination."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Self

from app.core.errors import ValidationError

__all__ = [
    "AgentTaskGroupRecord",
    "AgentTaskRecord",
    "AgentTaskSpec",
    "derive_group_status",
]

TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_CANCELLED = "cancelled"

GROUP_STATUS_QUEUED = "queued"
GROUP_STATUS_RUNNING = "running"
GROUP_STATUS_COMPLETED = "completed"
GROUP_STATUS_PARTIAL_FAILED = "partial_failed"
GROUP_STATUS_FAILED = "failed"
GROUP_STATUS_CANCELLED = "cancelled"

_TASK_STATUSES = {
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_CANCELLED,
}
_GROUP_STATUSES = {
    GROUP_STATUS_QUEUED,
    GROUP_STATUS_RUNNING,
    GROUP_STATUS_COMPLETED,
    GROUP_STATUS_PARTIAL_FAILED,
    GROUP_STATUS_FAILED,
    GROUP_STATUS_CANCELLED,
}
_ARTIFACT_ID_PATTERN = re.compile(r"^artifact_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


@dataclass(slots=True)
class AgentTaskSpec:
    """One independent child-agent task."""

    target_agent_id: str
    instruction: str
    constraints: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    skill_names: list[str] = field(default_factory=lambda: ["base", "tools", "file-reader"])
    max_tool_rounds: int = 10
    depends_on: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.target_agent_id = _require_non_empty("target_agent_id", self.target_agent_id)
        self.instruction = _require_non_empty("instruction", self.instruction)
        self.constraints = _normalize_string_list("constraints", self.constraints)
        self.artifact_refs = _normalize_artifact_refs("artifact_refs", self.artifact_refs)
        self.skill_names = _normalize_string_list("skill_names", self.skill_names)
        self.depends_on = _normalize_string_list("depends_on", self.depends_on)
        if self.max_tool_rounds < 0 or self.max_tool_rounds > 40:
            raise ValidationError("max_tool_rounds must be in range 0..40.")


@dataclass(slots=True)
class AgentTaskGroupRecord:
    """Durable task group snapshot."""

    task_group_id: str
    session_id: str
    source_agent_id: str
    source_run_id: str
    status: str
    max_concurrency: int
    task_ids: list[str]
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        self.task_group_id = _require_non_empty("task_group_id", self.task_group_id)
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.source_agent_id = _require_non_empty("source_agent_id", self.source_agent_id)
        self.source_run_id = _require_non_empty("source_run_id", self.source_run_id)
        self.status = _normalize_status("group", self.status, _GROUP_STATUSES)
        if self.max_concurrency <= 0:
            raise ValidationError("max_concurrency must be positive.")
        self.task_ids = _normalize_string_list("task_ids", self.task_ids)
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at cannot be earlier than created_at.")

    def copy(self) -> Self:
        return type(self)(
            task_group_id=self.task_group_id,
            session_id=self.session_id,
            source_agent_id=self.source_agent_id,
            source_run_id=self.source_run_id,
            status=self.status,
            max_concurrency=self.max_concurrency,
            task_ids=list(self.task_ids),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


@dataclass(slots=True)
class AgentTaskRecord:
    """Durable task status snapshot."""

    task_id: str
    task_group_id: str
    session_id: str
    source_agent_id: str
    source_run_id: str
    target_agent_id: str
    instruction: str
    constraints: list[str]
    artifact_refs: list[str]
    skill_names: list[str]
    max_tool_rounds: int
    status: str
    child_run_id: str | None = None
    summary: str | None = None
    answer: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        self.task_id = _require_non_empty("task_id", self.task_id)
        self.task_group_id = _require_non_empty("task_group_id", self.task_group_id)
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.source_agent_id = _require_non_empty("source_agent_id", self.source_agent_id)
        self.source_run_id = _require_non_empty("source_run_id", self.source_run_id)
        self.target_agent_id = _require_non_empty("target_agent_id", self.target_agent_id)
        self.instruction = _require_non_empty("instruction", self.instruction)
        self.constraints = _normalize_string_list("constraints", self.constraints)
        self.artifact_refs = _normalize_artifact_refs("artifact_refs", self.artifact_refs)
        self.skill_names = _normalize_string_list("skill_names", self.skill_names)
        if self.max_tool_rounds < 0 or self.max_tool_rounds > 40:
            raise ValidationError("max_tool_rounds must be in range 0..40.")
        self.status = _normalize_status("task", self.status, _TASK_STATUSES)
        self.child_run_id = _normalize_optional_string("child_run_id", self.child_run_id)
        self.summary = _normalize_optional_string("summary", self.summary)
        self.answer = _normalize_optional_string("answer", self.answer)
        self.error = _normalize_optional_string("error", self.error)
        if self.created_at is None:
            raise ValidationError("created_at is required.")
        if self.updated_at is None:
            raise ValidationError("updated_at is required.")
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at cannot be earlier than created_at.")

    def copy(self) -> Self:
        return type(self)(
            task_id=self.task_id,
            task_group_id=self.task_group_id,
            session_id=self.session_id,
            source_agent_id=self.source_agent_id,
            source_run_id=self.source_run_id,
            target_agent_id=self.target_agent_id,
            instruction=self.instruction,
            constraints=list(self.constraints),
            artifact_refs=list(self.artifact_refs),
            skill_names=list(self.skill_names),
            max_tool_rounds=self.max_tool_rounds,
            status=self.status,
            child_run_id=self.child_run_id,
            summary=self.summary,
            answer=self.answer,
            error=self.error,
            created_at=self.created_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
            updated_at=self.updated_at,
        )


def derive_group_status(tasks: list[AgentTaskRecord]) -> str:
    if not tasks:
        return GROUP_STATUS_QUEUED
    statuses = [task.status for task in tasks]
    if all(status == TASK_STATUS_COMPLETED for status in statuses):
        return GROUP_STATUS_COMPLETED
    if all(status == TASK_STATUS_FAILED for status in statuses):
        return GROUP_STATUS_FAILED
    if all(status == TASK_STATUS_CANCELLED for status in statuses):
        return GROUP_STATUS_CANCELLED
    if any(status == TASK_STATUS_COMPLETED for status in statuses) and any(
        status == TASK_STATUS_FAILED for status in statuses
    ):
        return GROUP_STATUS_PARTIAL_FAILED
    if any(status in {TASK_STATUS_RUNNING, TASK_STATUS_COMPLETED, TASK_STATUS_FAILED} for status in statuses):
        return GROUP_STATUS_RUNNING
    return GROUP_STATUS_QUEUED


def _require_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _normalize_optional_string(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_non_empty(name, value)


def _normalize_status(label: str, status: str, allowed: set[str]) -> str:
    normalized = _require_non_empty(f"{label}_status", status).lower()
    if normalized not in allowed:
        raise ValidationError(f"{label}_status is invalid: {normalized}")
    return normalized


def _normalize_string_list(name: str, values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(f"{name} must be a list.")
    output: list[str] = []
    for raw in values:
        output.append(_require_non_empty(name, raw))
    return output


def _normalize_artifact_refs(name: str, values: list[str]) -> list[str]:
    refs = _normalize_string_list(name, values)
    output: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if not _ARTIFACT_ID_PATTERN.fullmatch(ref):
            raise ValidationError(f"{name} must contain session artifact ids, not workspace paths or filenames: {ref}")
        if ref in seen:
            continue
        output.append(ref)
        seen.add(ref)
    return output
