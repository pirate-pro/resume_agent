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
    MemoryStructuredBackfillRequest,
    MemoryStructuredBackfillResult,
    MemoryWriteCandidateRequest,
)

__all__ = ["MemoryFacade", "MemoryStore"]


class MemoryFacade(Protocol):
    def read_context(self, request: MemoryReadRequest) -> MemoryReadBundle: ...

    def write_candidate(self, request: MemoryWriteCandidateRequest) -> CandidateResult: ...

    def consolidate(self, request: MemoryConsolidateRequest) -> ConsolidateResult: ...

    def forget(self, request: MemoryForgetRequest) -> ForgetResult: ...

    def compact(self, request: MemoryCompactRequest) -> CompactResult: ...

    def backfill_structured_metadata(
        self,
        request: MemoryStructuredBackfillRequest,
    ) -> MemoryStructuredBackfillResult: ...

    def list_active_records_by_canonical_key(
        self,
        *,
        agent_id: str,
        session_id: str | None,
        include_scopes: list[MemoryScope],
        canonical_key: str,
    ) -> list[MemoryRecord]: ...

    def refresh_record_metadata(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        memory_id: str,
        metadata_patch: dict[str, str],
    ) -> MemoryRecord | None: ...


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

    def count_active_records_by_canonical_value(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        canonical_key: str,
        normalized_value: str,
        now: datetime,
    ) -> int: ...

    def list_active_records_by_canonical_key(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        canonical_key: str,
        now: datetime,
    ) -> list[MemoryRecord]: ...

    def archive_records_by_memory_ids(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        memory_ids: list[str],
        now: datetime,
        reason: str,
        superseded_by_memory_id: str | None = None,
        superseded_by_normalized_value: str | None = None,
    ) -> int: ...

    def refresh_record_metadata(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        memory_id: str,
        metadata_patch: dict[str, str],
        now: datetime,
    ) -> MemoryRecord | None: ...

    def forget(self, request: MemoryForgetRequest, now: datetime) -> ForgetResult: ...

    def compact(self, request: MemoryCompactRequest, now: datetime) -> CompactResult: ...

    def backfill_structured_metadata(
        self,
        request: MemoryStructuredBackfillRequest,
        now: datetime,
    ) -> MemoryStructuredBackfillResult: ...
