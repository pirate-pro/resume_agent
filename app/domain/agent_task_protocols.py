"""Protocols for durable agent task coordination."""

from __future__ import annotations

from typing import Protocol

from app.domain.agent_tasks import AgentTaskGroupRecord, AgentTaskRecord, AgentTaskSpec

__all__ = ["AgentTaskStore"]


class AgentTaskStore(Protocol):
    def create_group(
        self,
        *,
        session_id: str,
        source_agent_id: str,
        source_run_id: str,
        max_concurrency: int,
        specs: list[AgentTaskSpec],
    ) -> AgentTaskGroupRecord: ...

    def get_group(self, session_id: str, task_group_id: str) -> AgentTaskGroupRecord | None: ...

    def list_group_tasks(self, session_id: str, task_group_id: str) -> list[AgentTaskRecord]: ...

    def get_task(self, session_id: str, task_id: str) -> AgentTaskRecord | None: ...

    def mark_running(self, session_id: str, task_id: str, *, child_run_id: str) -> AgentTaskRecord: ...

    def mark_completed(
        self,
        session_id: str,
        task_id: str,
        *,
        summary: str,
        answer: str,
        artifact_refs: list[str],
    ) -> AgentTaskRecord: ...

    def mark_failed(self, session_id: str, task_id: str, *, error: str) -> AgentTaskRecord: ...
