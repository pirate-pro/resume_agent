"""Protocols for durable LangGraph child-task attempts."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.graph_agent_tasks import GraphAgentTaskAttemptRecord, GraphAgentTaskAttemptSpec

__all__ = ["GraphAgentTaskStore"]


class GraphAgentTaskStore(Protocol):
    def ensure_attempt(
        self,
        spec: GraphAgentTaskAttemptSpec,
        *,
        retry_failed: bool = False,
    ) -> GraphAgentTaskAttemptRecord: ...

    def get_attempt(self, attempt_id: str) -> GraphAgentTaskAttemptRecord | None: ...

    def latest_attempt(
        self,
        *,
        session_id: str,
        workflow_instance_id: str,
        task_key: str,
    ) -> GraphAgentTaskAttemptRecord | None: ...

    def list_workflow_attempts(
        self,
        *,
        session_id: str,
        workflow_instance_id: str,
    ) -> list[GraphAgentTaskAttemptRecord]: ...

    def claim_attempt(
        self,
        attempt_id: str,
        *,
        owner_id: str,
        child_run_id: str,
        ttl_seconds: float,
    ) -> GraphAgentTaskAttemptRecord: ...

    def mark_completed(
        self,
        attempt_id: str,
        *,
        owner_id: str,
        summary: str,
        output_artifact_refs: list[str],
        product_refs: list[str],
    ) -> GraphAgentTaskAttemptRecord: ...

    def mark_failed(
        self,
        attempt_id: str,
        *,
        owner_id: str,
        error: str,
    ) -> GraphAgentTaskAttemptRecord: ...

    def reconcile_stale_running(self, *, now: datetime | None = None) -> list[GraphAgentTaskAttemptRecord]: ...
