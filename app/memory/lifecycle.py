"""Lifecycle operations for memory records."""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.contracts import MemoryStore
from app.memory.models import (
    CompactResult,
    ForgetResult,
    MemoryCompactRequest,
    MemoryForgetRequest,
    MemoryScope,
    MemoryStructuredBackfillRequest,
    MemoryStructuredBackfillResult,
)

__all__ = ["MemoryLifecycleService"]


class MemoryLifecycleService:
    """Handle forget and expiry related operations."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def forget(self, request: MemoryForgetRequest) -> ForgetResult:
        return self._store.forget(request, now=datetime.now(UTC))

    def compact(self, request: MemoryCompactRequest) -> CompactResult:
        return self._store.compact(request, now=datetime.now(UTC))

    def backfill_structured_metadata(
        self,
        request: MemoryStructuredBackfillRequest,
    ) -> MemoryStructuredBackfillResult:
        return self._store.backfill_structured_metadata(request, now=datetime.now(UTC))

    def expire_short_memory(self, agent_id: str, session_id: str | None = None) -> ForgetResult:
        request = MemoryForgetRequest(
            agent_id=agent_id,
            session_id=session_id,
            scopes=[MemoryScope.AGENT_SHORT],
            before=datetime.now(UTC),
            memory_ids=[],
            hard_delete=False,
            reason="ttl_expired",
        )
        return self._store.forget(request, now=datetime.now(UTC))
