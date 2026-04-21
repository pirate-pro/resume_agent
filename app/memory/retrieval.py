"""Retrieval service for layered memory reads."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.memory.contracts import MemoryStore
from app.memory.models import MemoryReadBundle, MemoryReadRequest, MemoryRecord
from app.memory.policies import MemoryPolicy, default_memory_policy

__all__ = ["MemoryRetrievalService"]
_logger = logging.getLogger(__name__)


class MemoryRetrievalService:
    """Read memory records from layered scopes with budget-aware trimming."""

    def __init__(self, store: MemoryStore, policy: MemoryPolicy | None = None) -> None:
        self._store = store
        self._policy = policy or default_memory_policy()

    def read(self, request: MemoryReadRequest) -> MemoryReadBundle:
        now = datetime.now(UTC)
        scoped_limit = max(1, request.limit)
        collected: list[MemoryRecord] = []
        notes: list[str] = []
        total_scanned = 0

        for scope in request.include_scopes:
            limit = min(scoped_limit, self._policy.per_scope_limit.get(scope, scoped_limit))
            try:
                items = self._store.search_records(
                    scope=scope,
                    agent_id=request.agent_id,
                    session_id=request.session_id,
                    query=request.query,
                    limit=limit,
                    now=now,
                )
            except Exception as exc:  # noqa: BLE001
                _logger.exception(
                    "memory 分层检索失败: scope=%s agent_id=%s session_id=%s error=%s",
                    scope.value,
                    request.agent_id,
                    request.session_id,
                    exc,
                )
                notes.append(f"scope={scope.value} read_failed: {exc}")
                if not request.allow_fallback:
                    raise
                continue

            total_scanned += len(items)
            collected.extend(items)

        deduped = _dedupe_by_memory_id(collected)
        ranked = _rank_records(deduped)
        top_records = ranked[: request.limit]
        trimmed, truncated = _trim_by_token_budget(top_records, request.token_budget)
        return MemoryReadBundle(
            items=trimmed,
            searched_scopes=request.include_scopes,
            total_scanned=total_scanned,
            truncated=truncated,
            notes=notes,
        )


def _dedupe_by_memory_id(items: list[MemoryRecord]) -> list[MemoryRecord]:
    output: list[MemoryRecord] = []
    seen: set[str] = set()
    for item in items:
        if item.memory_id in seen:
            continue
        seen.add(item.memory_id)
        output.append(item)
    return output


def _rank_records(items: list[MemoryRecord]) -> list[MemoryRecord]:
    return sorted(
        items,
        key=lambda item: (item.confidence, item.importance, item.updated_at),
        reverse=True,
    )


def _trim_by_token_budget(items: list[MemoryRecord], token_budget: int) -> tuple[list[MemoryRecord], bool]:
    if token_budget <= 0:
        return [], bool(items)
    kept: list[MemoryRecord] = []
    consumed = 0
    for item in items:
        estimate = max(1, (len(item.content) + 3) // 4)
        if consumed + estimate > token_budget:
            return kept, True
        kept.append(item)
        consumed += estimate
    return kept, False

