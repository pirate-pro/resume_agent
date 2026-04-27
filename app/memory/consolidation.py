"""Consolidation service for candidate memories."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from dataclasses import dataclass
from uuid import uuid4

from app.memory.contracts import MemoryStore
from app.memory.models import (
    ConsolidateResult,
    MemoryCandidate,
    MemoryConsolidateRequest,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    make_content_hash,
)
from app.memory.policies import MemoryPolicy, default_memory_policy

__all__ = ["MemoryConsolidationService"]
_EXPLICIT_RULE_TAGS = {"explicit_user_rule", "system_policy"}
_EXPLICIT_RULE_SOURCES = {"explicit_user_rule", "system_policy"}
_SOURCE_PRIORITY = {
    "system_policy": 100,
    "explicit_user_rule": 95,
    "explicit_user": 90,
    "user_feedback": 80,
    "tool_verified": 70,
    "repeated_behavior": 60,
    "assistant_inferred": 10,
}


@dataclass(slots=True)
class _PendingArchive:
    scope: MemoryScope
    owner_agent_id: str | None
    session_id: str | None
    memory_ids: list[str]
    superseded_by_memory_id: str
    superseded_by_normalized_value: str


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
                written_memory_ids=[],
            )

        now = datetime.now(UTC)
        # 批内重复统计：用于 shared 晋升阈值判断（重复次数门槛）。
        hash_repeat_count = _build_hash_repeat_count(candidates)
        dedup: dict[tuple[str, str, str, str], MemoryRecord] = {}
        canonical_winners: dict[tuple[str, str, str, str], tuple[tuple[str, str, str, str], MemoryRecord, int]] = {}
        pending_archives: dict[tuple[str, str, str, str], _PendingArchive] = {}
        merged_records = 0
        promoted_shared = 0
        conflicts = 0

        for candidate in candidates:
            content_hash = make_content_hash(candidate.content)
            scope, promoted = self._resolve_scope(candidate, content_hash, hash_repeat_count, now)
            owner_agent_id, session_id = _resolve_owner_and_session(scope=scope, candidate=candidate)
            dedup_key = _build_dedup_key(
                scope=scope,
                owner_agent_id=owner_agent_id,
                session_id=session_id,
                content_hash=content_hash,
                candidate=candidate,
            )
            if dedup_key in dedup:
                merged_records += 1
                continue
            canonical_key, normalized_value = _resolve_canonical_identity(candidate)
            if canonical_key is not None and normalized_value is not None:
                canonical_group = (scope.value, owner_agent_id or "-", session_id or "-", canonical_key)
                new_priority = _source_priority_for_candidate(candidate)
                existing_winner = canonical_winners.get(canonical_group)
                if existing_winner is not None:
                    winner_dedup_key, winner_record, winner_priority = existing_winner
                    winner_value = str(winner_record.metadata.get("normalized_value", "")).strip()
                    if winner_value == normalized_value:
                        merged_records += 1
                        continue
                    if new_priority < winner_priority:
                        conflicts += 1
                        continue
                    dedup.pop(winner_dedup_key, None)
                    pending_archives.pop(canonical_group, None)
                    merged_records += 1
                existing_canonical_count = self._store.count_active_records_by_canonical_value(
                    scope=scope,
                    agent_id=owner_agent_id,
                    session_id=session_id,
                    canonical_key=canonical_key,
                    normalized_value=normalized_value,
                    now=now,
                )
                if existing_canonical_count > 0:
                    merged_records += 1
                    continue
                conflicting_records = [
                    item
                    for item in self._store.list_active_records_by_canonical_key(
                        scope=scope,
                        agent_id=owner_agent_id,
                        session_id=session_id,
                        canonical_key=canonical_key,
                        now=now,
                    )
                    if str(item.metadata.get("normalized_value", "")).strip() != normalized_value
                ]
                if conflicting_records:
                    if not _can_supersede_existing_records(candidate, conflicting_records):
                        conflicts += 1
                        continue
                    next_version = max(item.version for item in conflicting_records) + 1
                    parent_memory_id = conflicting_records[0].memory_id
                else:
                    next_version = 1
                    parent_memory_id = None
            else:
                canonical_group = None
                new_priority = _source_priority_for_candidate(candidate)
                conflicting_records = []
                next_version = 1
                parent_memory_id = None
            # 跨轮去重：如果目标层已存在同 hash 的 active 记录，本轮不重复写入。
            existing_count = self._store.count_active_records_by_hash(
                scope=scope,
                agent_id=owner_agent_id,
                session_id=session_id,
                content_hash=content_hash,
                now=now,
            )
            if existing_count > 0:
                merged_records += 1
                continue
            if promoted:
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
                version=next_version,
                parent_memory_id=parent_memory_id,
                content_hash=content_hash,
                metadata=candidate.metadata,
            )
            dedup[dedup_key] = record
            if canonical_group is not None:
                canonical_winners[canonical_group] = (dedup_key, record, new_priority)
                if conflicting_records:
                    assert normalized_value is not None
                    pending_archives[canonical_group] = _PendingArchive(
                        scope=scope,
                        owner_agent_id=owner_agent_id,
                        session_id=session_id,
                        memory_ids=[item.memory_id for item in conflicting_records],
                        superseded_by_memory_id=record.memory_id,
                        superseded_by_normalized_value=normalized_value,
                    )

        records = list(dedup.values())
        for item in pending_archives.values():
            self._store.archive_records_by_memory_ids(
                scope=item.scope,
                agent_id=item.owner_agent_id,
                session_id=item.session_id,
                memory_ids=item.memory_ids,
                now=now,
                reason="superseded_by_canonical_key",
                superseded_by_memory_id=item.superseded_by_memory_id,
                superseded_by_normalized_value=item.superseded_by_normalized_value,
            )
        if records:
            self._store.write_records(records)
        archived_count = self._store.archive_pending_candidates([item.candidate_id for item in candidates], processed_at=now)
        return ConsolidateResult(
            consumed_candidates=archived_count,
            written_records=len(records),
            merged_records=merged_records,
            promoted_shared=promoted_shared,
            conflicts=conflicts,
            written_memory_ids=[item.memory_id for item in records],
        )

    def _resolve_scope(
        self,
        candidate: MemoryCandidate,
        content_hash: str,
        hash_repeat_count: dict[str, int],
        now: datetime,
    ) -> tuple[MemoryScope, bool]:
        """返回目标作用域，以及该候选是否被晋升到 shared 层。"""
        if candidate.scope_hint != MemoryScope.SHARED_LONG:
            if candidate.scope_hint == MemoryScope.AGENT_SHORT:
                repeated_in_batch = hash_repeat_count.get(content_hash, 0)
                repeated_in_agent_short = self._store.count_active_records_by_hash(
                    scope=MemoryScope.AGENT_SHORT,
                    agent_id=candidate.agent_id,
                    session_id=candidate.session_id,
                    content_hash=content_hash,
                    now=now,
                )
                repeated_in_agent_long = self._store.count_active_records_by_hash(
                    scope=MemoryScope.AGENT_LONG,
                    agent_id=candidate.agent_id,
                    session_id=None,
                    content_hash=content_hash,
                    now=now,
                )
                total_repeat = repeated_in_batch + repeated_in_agent_short + repeated_in_agent_long
                if _should_promote_short_to_long(candidate, total_repeat, self._policy):
                    return MemoryScope.AGENT_LONG, False
            return candidate.scope_hint, False
        repeated_in_batch = hash_repeat_count.get(content_hash, 0)
        repeated_in_shared = self._store.count_active_records_by_hash(
            scope=MemoryScope.SHARED_LONG,
            agent_id=None,
            session_id=None,
            content_hash=content_hash,
            now=now,
        )
        repeated_in_agent_long = self._store.count_active_records_by_hash(
            scope=MemoryScope.AGENT_LONG,
            agent_id=candidate.agent_id,
            session_id=None,
            content_hash=content_hash,
            now=now,
        )
        total_repeat = repeated_in_batch + repeated_in_shared + repeated_in_agent_long
        explicit_bypass = _is_explicit_rule_candidate(candidate)
        can_promote = (
            candidate.confidence >= self._policy.shared_promotion_min_confidence
            and (total_repeat >= self._policy.shared_promotion_min_repeat or explicit_bypass)
        )
        if can_promote:
            return MemoryScope.SHARED_LONG, True
        # shared 门槛未达成时降级到 agent_long，避免污染全局共享记忆。
        return MemoryScope.AGENT_LONG, False


def _build_hash_repeat_count(candidates: list[MemoryCandidate]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        content_hash = make_content_hash(candidate.content)
        counts[content_hash] = counts.get(content_hash, 0) + 1
    return counts


def _build_dedup_key(
    *,
    scope: MemoryScope,
    owner_agent_id: str | None,
    session_id: str | None,
    content_hash: str,
    candidate: MemoryCandidate,
) -> tuple[str, str, str, str]:
    canonical_key, normalized_value = _resolve_canonical_identity(candidate)
    if canonical_key is not None and normalized_value is not None:
        identity = f"canonical:{canonical_key}:{normalized_value}"
    else:
        identity = content_hash
    return (scope.value, owner_agent_id or "-", session_id or "-", identity)


def _resolve_canonical_identity(candidate: MemoryCandidate) -> tuple[str | None, str | None]:
    canonical_key = str(candidate.metadata.get("canonical_key", "")).strip()
    normalized_value = str(candidate.metadata.get("normalized_value", "")).strip()
    if not canonical_key or not normalized_value:
        return None, None
    return canonical_key, normalized_value


def _source_priority_for_candidate(candidate: MemoryCandidate) -> int:
    source_kind = str(candidate.metadata.get("source_kind", "")).strip().lower()
    return _SOURCE_PRIORITY.get(source_kind, 50)


def _source_priority_for_record(record: MemoryRecord) -> int:
    source_kind = str(record.metadata.get("source_kind", "")).strip().lower()
    return _SOURCE_PRIORITY.get(source_kind, 50)


def _can_supersede_existing_records(candidate: MemoryCandidate, records: list[MemoryRecord]) -> bool:
    candidate_priority = _source_priority_for_candidate(candidate)
    highest_existing_priority = max((_source_priority_for_record(item) for item in records), default=0)
    return candidate_priority >= highest_existing_priority


def _resolve_owner_and_session(scope: MemoryScope, candidate: MemoryCandidate) -> tuple[str | None, str | None]:
    if scope == MemoryScope.SHARED_LONG:
        return None, None
    if scope == MemoryScope.AGENT_LONG:
        return candidate.agent_id, None
    return candidate.agent_id, candidate.session_id


def _should_promote_short_to_long(
    candidate: MemoryCandidate,
    total_repeat: int,
    policy: MemoryPolicy,
) -> bool:
    if _is_explicit_rule_candidate(candidate):
        return True
    return (
        candidate.confidence >= policy.agent_long_promotion_min_confidence
        and total_repeat >= policy.agent_long_promotion_min_repeat
    )


def _is_explicit_rule_candidate(candidate: MemoryCandidate) -> bool:
    tags = {tag.strip().lower() for tag in candidate.tags if isinstance(tag, str) and tag.strip()}
    if tags.intersection(_EXPLICIT_RULE_TAGS):
        return True
    source = str(candidate.metadata.get("source", "")).strip().lower()
    source_kind = str(candidate.metadata.get("source_kind", "")).strip().lower()
    return source in _EXPLICIT_RULE_SOURCES or source_kind in _EXPLICIT_RULE_SOURCES
