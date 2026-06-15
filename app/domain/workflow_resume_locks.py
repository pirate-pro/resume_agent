"""Protocols for workflow resume concurrency control."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol

__all__ = ["WorkflowResumeLease", "WorkflowResumeLeaseStore"]


@dataclass(frozen=True, slots=True)
class WorkflowResumeLease:
    """A held lease for resuming one workflow instance."""

    workflow_instance_id: str
    owner_id: str
    expires_at: datetime


class WorkflowResumeLeaseStore(Protocol):
    async def acquire(
        self,
        *,
        workflow_instance_id: str,
        owner_id: str,
        ttl_seconds: float,
    ) -> WorkflowResumeLease: ...

    async def release(self, lease: WorkflowResumeLease) -> None: ...

    async def __aenter__(self) -> "WorkflowResumeLeaseStore": ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...
