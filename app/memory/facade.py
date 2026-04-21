"""Memory facade implementation for file-based backend."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.memory.consolidation import MemoryConsolidationService
from app.memory.contracts import MemoryStore
from app.memory.lifecycle import MemoryLifecycleService
from app.memory.models import (
    CandidateResult,
    ConsolidateResult,
    ForgetResult,
    MemoryCandidate,
    MemoryConsolidateRequest,
    MemoryForgetRequest,
    MemoryReadBundle,
    MemoryReadRequest,
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

