"""Dispatch LangGraph workflow runs by workflow id."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.models import AgentRunInput
from app.domain.workflow_instance_protocols import WorkflowInstanceStore
from app.domain.workflow_resume_locks import WorkflowResumeLeaseStore
from app.runtime.event_channel import EventChannel
from app.runtime.langgraph.types import WorkflowGraphRunResult, WorkflowResumeRequest

__all__ = ["WorkflowRunnerDispatcher"]


class _WorkflowRunner(Protocol):
    async def run_stream(
        self,
        run_input: AgentRunInput,
        *,
        channel: EventChannel | None = None,
    ) -> WorkflowGraphRunResult: ...

    async def resume_stream(
        self,
        request: WorkflowResumeRequest,
        *,
        channel: EventChannel | None = None,
    ) -> WorkflowGraphRunResult: ...


@dataclass(slots=True)
class WorkflowRunnerDispatcher:
    """Route start/resume calls to the runner that owns a workflow instance."""

    runners: Mapping[str, _WorkflowRunner]
    workflow_store: WorkflowInstanceStore | None = None
    resume_lease_store: WorkflowResumeLeaseStore | None = None
    resume_lease_ttl_seconds: float = 600.0
    _workflow_instances: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.resume_lease_ttl_seconds <= 0:
            raise ValidationError("resume_lease_ttl_seconds must be positive.")

    async def run_workflow_stream(
        self,
        workflow_id: str,
        run_input: AgentRunInput,
        *,
        channel: EventChannel | None = None,
    ) -> WorkflowGraphRunResult:
        runner = self.runners.get(workflow_id)
        if runner is None:
            return WorkflowGraphRunResult(handled=False, status="skipped")
        result = await runner.run_stream(run_input, channel=channel)
        if result.workflow_instance_id:
            self._workflow_instances[result.workflow_instance_id] = workflow_id
        return result

    async def resume_workflow_stream(
        self,
        workflow_instance_id: str,
        request: WorkflowResumeRequest,
        *,
        channel: EventChannel | None = None,
    ) -> WorkflowGraphRunResult:
        workflow_id = self._workflow_instances.get(workflow_instance_id)
        if workflow_id is None:
            record = self.workflow_store.find_by_instance_id(workflow_instance_id) if self.workflow_store else None
            if record is None:
                raise ValidationError(
                    "Unknown workflow_instance_id for LangGraph dispatcher. "
                    "Start the workflow before resuming it."
                )
            if record.session_id != request.session_id:
                raise ValidationError("workflow_instance_id does not belong to the requested session.")
            workflow_id = record.workflow_id
            self._workflow_instances[workflow_instance_id] = workflow_id
        if self.workflow_store is not None:
            record = self.workflow_store.prepare_resume(
                session_id=request.session_id,
                workflow_instance_id=workflow_instance_id,
                expected_version=request.expected_version,
            )
            workflow_id = record.workflow_id
            self._workflow_instances[workflow_instance_id] = workflow_id
        runner = self.runners.get(workflow_id)
        if runner is None:
            raise ValidationError(f"LangGraph workflow runner is not registered: {workflow_id}")
        if self.resume_lease_store is None:
            return await runner.resume_stream(request, channel=channel)
        owner_id = f"{request.context.run_id}:{uuid4().hex}"
        lease = await self.resume_lease_store.acquire(
            workflow_instance_id=workflow_instance_id,
            owner_id=owner_id,
            ttl_seconds=self.resume_lease_ttl_seconds,
        )
        try:
            return await runner.resume_stream(request, channel=channel)
        finally:
            await self.resume_lease_store.release(lease)
