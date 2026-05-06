"""Concurrent task-group execution for delegated child agents."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Self
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.models import RunContext
from app.services.agent_invocation_service import AgentInvocationRequest, AgentInvocationService

__all__ = [
    "AgentTaskGroupRequest",
    "AgentTaskGroupResult",
    "AgentTaskRecord",
    "AgentTaskResult",
    "AgentTaskRuntime",
    "AgentTaskSpec",
    "InMemoryAgentTaskStore",
]

_DEFAULT_MAX_CONCURRENCY = 3
_MAX_TASKS_PER_GROUP = 8


@dataclass(slots=True)
class AgentTaskSpec:
    """One independent child-agent task."""

    target_agent_id: str
    instruction: str
    constraints: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    skill_names: list[str] = field(default_factory=lambda: ["base", "tools", "file-reader"])
    max_tool_rounds: int = 2
    depends_on: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.target_agent_id = _require_non_empty("target_agent_id", self.target_agent_id)
        self.instruction = _require_non_empty("instruction", self.instruction)
        self.constraints = _normalize_string_list("constraints", self.constraints)
        self.artifact_refs = _normalize_string_list("artifact_refs", self.artifact_refs)
        self.skill_names = _normalize_string_list("skill_names", self.skill_names)
        self.depends_on = _normalize_string_list("depends_on", self.depends_on)
        if self.max_tool_rounds < 0 or self.max_tool_rounds > 10:
            raise ValidationError("max_tool_rounds must be in range 0..10.")


@dataclass(slots=True)
class AgentTaskGroupRequest:
    """Input contract for one task group."""

    source_context: RunContext
    tasks: list[AgentTaskSpec]
    wait: bool = True
    max_concurrency: int = _DEFAULT_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        if not isinstance(self.source_context, RunContext):
            raise ValidationError("source_context must be RunContext.")
        if not isinstance(self.tasks, list) or not self.tasks:
            raise ValidationError("tasks must be a non-empty list.")
        if len(self.tasks) > _MAX_TASKS_PER_GROUP:
            raise ValidationError(f"tasks cannot exceed {_MAX_TASKS_PER_GROUP} items.")
        for task in self.tasks:
            if not isinstance(task, AgentTaskSpec):
                raise ValidationError("tasks must contain AgentTaskSpec items.")
        if not isinstance(self.wait, bool):
            raise ValidationError("wait must be bool.")
        if self.max_concurrency <= 0:
            raise ValidationError("max_concurrency must be positive.")
        self.max_concurrency = min(self.max_concurrency, len(self.tasks), _MAX_TASKS_PER_GROUP)


@dataclass(slots=True)
class AgentTaskRecord:
    """Mutable task status snapshot held by the task store."""

    task_id: str
    task_group_id: str
    target_agent_id: str
    instruction: str
    status: str
    child_run_id: str | None = None
    summary: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        self.task_id = _require_non_empty("task_id", self.task_id)
        self.task_group_id = _require_non_empty("task_group_id", self.task_group_id)
        self.target_agent_id = _require_non_empty("target_agent_id", self.target_agent_id)
        self.instruction = _require_non_empty("instruction", self.instruction)
        self.status = _require_non_empty("status", self.status)
        self.child_run_id = _normalize_optional_string("child_run_id", self.child_run_id)
        self.summary = _normalize_optional_string("summary", self.summary)
        self.error = _normalize_optional_string("error", self.error)

    def copy(self) -> Self:
        return type(self)(
            task_id=self.task_id,
            task_group_id=self.task_group_id,
            target_agent_id=self.target_agent_id,
            instruction=self.instruction,
            status=self.status,
            child_run_id=self.child_run_id,
            summary=self.summary,
            error=self.error,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


@dataclass(slots=True)
class AgentTaskResult:
    """Completed task result returned to main-agent tooling."""

    task_id: str
    target_agent_id: str
    status: str
    summary: str
    answer: str
    child_run_id: str | None = None
    artifact_refs: list[str] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        self.task_id = _require_non_empty("task_id", self.task_id)
        self.target_agent_id = _require_non_empty("target_agent_id", self.target_agent_id)
        self.status = _require_non_empty("status", self.status)
        self.summary = _require_non_empty("summary", self.summary)
        self.answer = _require_non_empty("answer", self.answer)
        self.child_run_id = _normalize_optional_string("child_run_id", self.child_run_id)
        self.artifact_refs = _normalize_string_list("artifact_refs", self.artifact_refs)
        self.error = _normalize_optional_string("error", self.error)

    def to_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "target_agent_id": self.target_agent_id,
            "status": self.status,
            "summary": self.summary,
            "answer": self.answer,
            "child_run_id": self.child_run_id,
            "artifact_refs": self.artifact_refs,
            "error": self.error,
        }


@dataclass(slots=True)
class AgentTaskGroupResult:
    """Aggregated result for one delegated task group."""

    task_group_id: str
    status: str
    results: list[AgentTaskResult]
    max_concurrency: int

    def __post_init__(self) -> None:
        self.task_group_id = _require_non_empty("task_group_id", self.task_group_id)
        self.status = _require_non_empty("status", self.status)
        if not isinstance(self.results, list):
            raise ValidationError("results must be a list.")
        if self.max_concurrency <= 0:
            raise ValidationError("max_concurrency must be positive.")

    def to_payload(self) -> dict[str, object]:
        return {
            "task_group_id": self.task_group_id,
            "status": self.status,
            "max_concurrency": self.max_concurrency,
            "results": [result.to_payload() for result in self.results],
        }


class InMemoryAgentTaskStore:
    """Thread-safe in-process task status store for the current runtime process."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._groups: dict[str, list[str]] = {}
        self._tasks: dict[str, AgentTaskRecord] = {}

    def create_group(self, specs: list[AgentTaskSpec]) -> list[AgentTaskRecord]:
        if not isinstance(specs, list) or not specs:
            raise ValidationError("specs must be a non-empty list.")
        task_group_id = f"task_group_{uuid4().hex[:12]}"
        records: list[AgentTaskRecord] = []
        with self._lock:
            self._groups[task_group_id] = []
            for spec in specs:
                task_id = f"task_{uuid4().hex[:12]}"
                record = AgentTaskRecord(
                    task_id=task_id,
                    task_group_id=task_group_id,
                    target_agent_id=spec.target_agent_id,
                    instruction=spec.instruction,
                    status="queued",
                )
                self._groups[task_group_id].append(task_id)
                self._tasks[task_id] = record
                records.append(record.copy())
        return records

    def mark_running(self, task_id: str) -> None:
        self._update(task_id, status="running")

    def mark_completed(self, task_id: str, *, child_run_id: str, summary: str) -> None:
        self._update(task_id, status="completed", child_run_id=child_run_id, summary=summary, error=None)

    def mark_failed(self, task_id: str, *, error: str) -> None:
        self._update(task_id, status="failed", error=error)

    def get_group(self, task_group_id: str) -> list[AgentTaskRecord]:
        normalized = _require_non_empty("task_group_id", task_group_id)
        with self._lock:
            task_ids = self._groups.get(normalized)
            if task_ids is None:
                raise ValidationError(f"Unknown task_group_id: {normalized}")
            return [self._tasks[task_id].copy() for task_id in task_ids]

    def _update(
        self,
        task_id: str,
        *,
        status: str,
        child_run_id: str | None = None,
        summary: str | None = None,
        error: str | None = None,
    ) -> None:
        normalized = _require_non_empty("task_id", task_id)
        with self._lock:
            record = self._tasks.get(normalized)
            if record is None:
                raise ValidationError(f"Unknown task_id: {normalized}")
            record.status = _require_non_empty("status", status)
            if child_run_id is not None:
                record.child_run_id = _require_non_empty("child_run_id", child_run_id)
            if summary is not None:
                record.summary = _require_non_empty("summary", summary)
            if error is not None:
                record.error = _require_non_empty("error", error)
            elif status == "completed":
                record.error = None
            record.updated_at = datetime.now(UTC)


class AgentTaskRuntime:
    """Run independent child-agent tasks concurrently and aggregate results."""

    def __init__(
        self,
        *,
        invocation_service: AgentInvocationService,
        task_store: InMemoryAgentTaskStore,
        default_max_concurrency: int = _DEFAULT_MAX_CONCURRENCY,
    ) -> None:
        if default_max_concurrency <= 0:
            raise ValidationError("default_max_concurrency must be positive.")
        self._invocation_service = invocation_service
        self._task_store = task_store
        self._default_max_concurrency = default_max_concurrency

    def run_group(self, request: AgentTaskGroupRequest) -> AgentTaskGroupResult:
        return _run_coroutine_sync(self.run_group_async(request))

    async def run_group_async(self, request: AgentTaskGroupRequest) -> AgentTaskGroupResult:
        if not isinstance(request, AgentTaskGroupRequest):
            raise ValidationError("request must be AgentTaskGroupRequest.")
        if not request.wait:
            raise ValidationError("wait=false is not supported yet.")
        unsupported_dependencies = [task for task in request.tasks if task.depends_on]
        if unsupported_dependencies:
            raise ValidationError("depends_on is reserved for later; v1 only supports independent tasks.")

        max_concurrency = request.max_concurrency or self._default_max_concurrency
        task_records = self._task_store.create_group(request.tasks)
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run_one(spec: AgentTaskSpec, record: AgentTaskRecord) -> AgentTaskResult:
            async with semaphore:
                self._task_store.mark_running(record.task_id)
                try:
                    result = await asyncio.to_thread(
                        self._invocation_service.invoke,
                        AgentInvocationRequest(
                            source_context=request.source_context,
                            target_agent_id=spec.target_agent_id,
                            instruction=spec.instruction,
                            constraints=spec.constraints,
                            artifact_refs=spec.artifact_refs,
                            skill_names=spec.skill_names,
                            max_tool_rounds=spec.max_tool_rounds,
                            task_id=record.task_id,
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    error = _safe_error_message(exc)
                    self._task_store.mark_failed(record.task_id, error=error)
                    return AgentTaskResult(
                        task_id=record.task_id,
                        target_agent_id=spec.target_agent_id,
                        status="failed",
                        summary=error,
                        answer=error,
                        artifact_refs=spec.artifact_refs,
                        error=error,
                    )
                self._task_store.mark_completed(
                    record.task_id,
                    child_run_id=result.child_run_id,
                    summary=result.summary,
                )
                return AgentTaskResult(
                    task_id=record.task_id,
                    target_agent_id=spec.target_agent_id,
                    status="completed",
                    summary=result.summary,
                    answer=result.answer,
                    child_run_id=result.child_run_id,
                    artifact_refs=result.artifact_refs,
                )

        results = await asyncio.gather(
            *[_run_one(spec, record) for spec, record in zip(request.tasks, task_records, strict=True)]
        )
        group_status = "completed" if all(result.status == "completed" for result in results) else "partial_failed"
        return AgentTaskGroupResult(
            task_group_id=task_records[0].task_group_id,
            status=group_status,
            results=results,
            max_concurrency=max_concurrency,
        )


def _run_coroutine_sync(coro: Coroutine[object, object, AgentTaskGroupResult]) -> AgentTaskGroupResult:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: AgentTaskGroupResult | None = None
    error: BaseException | None = None

    def _runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            error = exc

    thread = threading.Thread(target=_runner, name="agent-task-runtime-sync-wrapper", daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    if result is None:
        raise ValidationError("agent task runtime returned no result.")
    return result


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _require_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _normalize_optional_string(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_non_empty(name, value)


def _normalize_string_list(name: str, values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(f"{name} must be a list.")
    output: list[str] = []
    for raw in values:
        output.append(_require_non_empty(name, raw))
    return output
