"""Consolidation service for candidate memories."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.memory.contracts import MemoryStore
from app.memory.models import ConsolidateResult, MemoryConsolidateRequest, MemoryRecord, MemoryScope, MemoryStatus, make_content_hash
from app.memory.policies import MemoryPolicy, default_memory_policy

__all__ = ["MemoryConsolidationService"]


class MemoryConsolidationService:
    """Consume candidate queue and produce normalized memory records."""

    def __init__(self, store: MemoryStore, policy: MemoryPolicy | None = None) -> None:
        self._store = store
        self._policy = policy or default_memory_policy()

    def consolidate(self, request: MemoryConsolidateRequest) -> ConsolidateResult:
        candidates = self._store.list_pending_candidates(request.max_candidates)
        if not candidates:
            return ConsolidateResult(
                consumed_candidates=0,
                written_records=0,
                merged_records=0,
                promoted_shared=0,
                conflicts=0,
            )

        now = datetime.now(UTC)
        dedup: dict[str, MemoryRecord] = {}
        merged_records = 0
        promoted_shared = 0

        for candidate in candidates:
            content_hash = make_content_hash(candidate.content)
            if content_hash in dedup:
                merged_records += 1
                continue

            scope = candidate.scope_hint
            owner_agent_id: str | None = candidate.agent_id
            session_id = candidate.session_id
            if scope == MemoryScope.SHARED_LONG:
                owner_agent_id = None
                session_id = None
                if candidate.confidence >= self._policy.shared_promotion_min_confidence:
                    promoted_shared += 1

            expires_at = None
            if scope == MemoryScope.AGENT_SHORT:
                expires_at = now + timedelta(seconds=self._policy.short_ttl_seconds)

            record = MemoryRecord(
                memory_id=f"mem_{uuid4().hex[:12]}",
                scope=scope,
                owner_agent_id=owner_agent_id,
                session_id=session_id,
                memory_type=candidate.memory_type,
                content=candidate.content,
                tags=candidate.tags,
                importance=min(1.0, max(0.1, candidate.confidence)),
                confidence=candidate.confidence,
                status=MemoryStatus.ACTIVE,
                created_at=now,
                updated_at=now,
                expires_at=expires_at,
                source_event_id=candidate.source_event_id,
                source_agent_id=candidate.agent_id,
                version=1,
                parent_memory_id=None,
                content_hash=content_hash,
                metadata=candidate.metadata,
            )
            dedup[content_hash] = record

        records = list(dedup.values())
        self._store.write_records(records)
        archived_count = self._store.archive_pending_candidates([item.candidate_id for item in candidates], processed_at=now)
        return ConsolidateResult(
            consumed_candidates=archived_count,
            written_records=len(records),
            merged_records=merged_records,
            promoted_shared=promoted_shared,
            conflicts=0,
        )

