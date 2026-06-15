"""Protocols for durable workflow instance tracking."""

from __future__ import annotations

from typing import Any, Protocol

from app.domain.workflow_instances import WorkflowInstanceRecord

__all__ = ["WorkflowInstanceStore"]


class WorkflowInstanceStore(Protocol):
    def create_or_update(
        self,
        *,
        session_id: str,
        workflow_instance_id: str,
        workflow_id: str,
        thread_id: str,
        run_id: str | None,
        status: str,
        phase: str,
        state_snapshot: dict[str, Any],
        pending_interrupt_payload: dict[str, Any] | None = None,
        output_refs: dict[str, Any] | None = None,
        last_error: dict[str, Any] | None = None,
    ) -> WorkflowInstanceRecord: ...

    def prepare_resume(
        self,
        *,
        session_id: str,
        workflow_instance_id: str,
        expected_version: int | None = None,
    ) -> WorkflowInstanceRecord: ...

    def get(self, session_id: str, workflow_instance_id: str) -> WorkflowInstanceRecord | None: ...

    def find_by_instance_id(self, workflow_instance_id: str) -> WorkflowInstanceRecord | None: ...

    def list_session_instances(
        self,
        session_id: str,
        *,
        statuses: set[str] | None = None,
    ) -> list[WorkflowInstanceRecord]: ...
