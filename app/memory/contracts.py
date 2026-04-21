"""Contracts for memory facade and storage adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.memory.models import (
    CandidateResult,
    ConsolidateResult,
    ForgetResult,
    MemoryCandidate,
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

    def forget(self, request: MemoryForgetRequest, now: datetime) -> ForgetResult: ...

