"""Contracts for memory facade and storage adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.memory.models import (
    CandidateResult,
    CompactResult,
    ConsolidateResult,
    ForgetResult,
    MemoryCandidate,
    MemoryCompactRequest,
    MemoryConsolidateRequest,
    MemoryForgetRequest,
    MemoryReadBundle,
    MemoryReadRequest,
    MemoryRecord,
    MemoryScope,
    MemoryWriteCandidateRequest,
)

__all__ = ["MemoryFacade", "MemoryStore"]


class MemoryFacade(Protocol):
    def read_context(self, request: MemoryReadRequest) -> MemoryReadBundle: ...

    def write_candidate(self, request: MemoryWriteCandidateRequest) -> CandidateResult: ...

    def consolidate(self, request: MemoryConsolidateRequest) -> ConsolidateResult: ...

    def forget(self, request: MemoryForgetRequest) -> ForgetResult: ...

    def compact(self, request: MemoryCompactRequest) -> CompactResult: ...


class MemoryStore(Protocol):
    def add_candidate(self, candidate: MemoryCandidate) -> None: ...

    def list_pending_candidates(self, limit: int) -> list[MemoryCandidate]: ...

    def archive_pending_candidates(self, candidate_ids: list[str], processed_at: datetime) -> int: ...

    def write_records(self, records: list[MemoryRecord]) -> None: ...

    def search_records(
        self,
        *,
        scope: MemoryScope,
        agent_id: str,
        session_id: str | None,
        query: str,
        limit: int,
        now: datetime,
    ) -> list[MemoryRecord]: ...

    def count_active_records_by_hash(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        content_hash: str,
        now: datetime,
    ) -> int: ...

    def forget(self, request: MemoryForgetRequest, now: datetime) -> ForgetResult: ...

    def compact(self, request: MemoryCompactRequest, now: datetime) -> CompactResult: ...
