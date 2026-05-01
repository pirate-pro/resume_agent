"""Input normalization helpers for runtime memory operations."""

from __future__ import annotations

from app.core.errors import ValidationError
from app.domain.models import RunContext
from app.memory.models import MemoryScope


def normalize_context(context: RunContext) -> RunContext:
    if not isinstance(context, RunContext):
        raise ValidationError("context must be RunContext.")
    return context


def normalize_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValidationError("query must be a non-empty string.")
    return query.strip()


def normalize_limit(limit: int) -> int:
    if limit <= 0:
        raise ValidationError("limit must be positive.")
    return limit


def normalize_agent_id(agent_id: str) -> str:
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValidationError("agent_id must be a non-empty string.")
    return agent_id.strip()


def normalize_memory_ids(memory_ids: list[str]) -> list[str]:
    if not isinstance(memory_ids, list) or not memory_ids:
        raise ValidationError("memory_ids must be a non-empty list.")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in memory_ids:
        if not isinstance(raw, str) or not raw.strip():
            raise ValidationError("memory_ids entries must be non-empty strings.")
        item = raw.strip()
        if item in seen:
            continue
        normalized.append(item)
        seen.add(item)
    if not normalized:
        raise ValidationError("memory_ids must contain at least one valid id.")
    return normalized


def normalize_scopes(scopes: list[MemoryScope]) -> list[MemoryScope]:
    if not isinstance(scopes, list) or not scopes:
        raise ValidationError("scopes must be a non-empty list.")
    output: list[MemoryScope] = []
    seen: set[MemoryScope] = set()
    for raw in scopes:
        if isinstance(raw, MemoryScope):
            scope = raw
        elif isinstance(raw, str) and raw.strip():
            try:
                scope = MemoryScope(raw.strip())
            except ValueError as exc:
                raise ValidationError(f"Unsupported memory scope: {raw}") from exc
        else:
            raise ValidationError("scopes entries must be MemoryScope or non-empty string.")
        if scope in seen:
            continue
        output.append(scope)
        seen.add(scope)
    if not output:
        raise ValidationError("scopes cannot be empty after normalization.")
    return output
