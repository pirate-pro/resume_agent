"""Memory facade implementation for file-based backend."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.memory.consolidation import MemoryConsolidationService
from app.memory.contracts import MemoryStore
from app.memory.lifecycle import MemoryLifecycleService
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
from app.memory.policies import MemoryPolicy, default_memory_policy
from app.memory.retrieval import MemoryRetrievalService

__all__ = ["FileMemoryFacade"]


class FileMemoryFacade:
    """High-level memory API used by runtime and tools."""

    def __init__(self, store: MemoryStore, policy: MemoryPolicy | None = None) -> None:
        self._policy = policy or default_memory_policy()
        self._retrieval = MemoryRetrievalService(store=store, policy=self._policy)
        self._consolidation = MemoryConsolidationService(store=store, policy=self._policy)
        self._lifecycle = MemoryLifecycleService(store=store)
        self._store = store

    def read_context(self, request: MemoryReadRequest) -> MemoryReadBundle:
        return self._retrieval.read(request)

    def write_candidate(self, request: MemoryWriteCandidateRequest) -> CandidateResult:
        candidate = MemoryCandidate(
            candidate_id=f"cand_{uuid4().hex[:12]}",
            agent_id=request.agent_id,
            session_id=request.session_id,
            scope_hint=request.scope_hint,
            memory_type=request.memory_type,
            content=request.content,
            tags=request.tags,
            confidence=request.confidence,
            source_event_id=request.source_event_id,
            idempotency_key=request.idempotency_key,
            created_at=datetime.now(UTC),
            metadata=request.metadata,
        )
        self._store.add_candidate(candidate)
        return CandidateResult(candidate_id=candidate.candidate_id, accepted=True, reason="queued")

    def consolidate(self, request: MemoryConsolidateRequest) -> ConsolidateResult:
        return self._consolidation.consolidate(request)

    def forget(self, request: MemoryForgetRequest) -> ForgetResult:
        return self._lifecycle.forget(request)

    def compact(self, request: MemoryCompactRequest) -> CompactResult:
        return self._lifecycle.compact(request)

    def backfill_structured_metadata(
        self,
        request: MemoryStructuredBackfillRequest,
    ) -> MemoryStructuredBackfillResult:
        return self._lifecycle.backfill_structured_metadata(request)

    def list_active_records_by_canonical_key(
        self,
        *,
        agent_id: str,
        session_id: str | None,
        include_scopes: list[MemoryScope],
        canonical_key: str,
    ) -> list[MemoryRecord]:
        now = datetime.now(UTC)
        matches: list[MemoryRecord] = []
        seen_memory_ids: set[str] = set()
        for scope in include_scopes:
            owner_agent_id = None if scope == MemoryScope.SHARED_LONG else agent_id
            scope_session_id = session_id if scope == MemoryScope.AGENT_SHORT else None
            for record in self._store.list_active_records_by_canonical_key(
                scope=scope,
                agent_id=owner_agent_id,
                session_id=scope_session_id,
                canonical_key=canonical_key,
                now=now,
            ):
                if record.memory_id in seen_memory_ids:
                    continue
                matches.append(record)
                seen_memory_ids.add(record.memory_id)
        matches.sort(key=lambda item: (item.updated_at, item.version, item.created_at, item.memory_id), reverse=True)
        return matches

    def refresh_record_metadata(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        memory_id: str,
        metadata_patch: dict[str, str],
    ) -> MemoryRecord | None:
        return self._store.refresh_record_metadata(
            scope=scope,
            agent_id=agent_id,
            session_id=session_id,
            memory_id=memory_id,
            metadata_patch=metadata_patch,
            now=datetime.now(UTC),
        )
