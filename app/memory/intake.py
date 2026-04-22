"""Input normalization for memory write requests."""

from __future__ import annotations

from hashlib import sha256

from app.memory.models import MemoryScope, MemoryType, MemoryWriteCandidateRequest

__all__ = ["build_candidate_request"]

_SHARED_SCOPE_TAGS = {"shared", "global", "cross_agent"}
_LONG_SCOPE_TAGS = {"long", "long_term", "preference", "constraint", "policy", "profile", "memory"}

_PREFERENCE_TAGS = {"preference", "style", "habit"}
_CONSTRAINT_TAGS = {"constraint", "rule", "policy", "limit"}
_PLAN_TAGS = {"plan", "todo", "next_step"}
_SCRATCH_TAGS = {"scratch", "temp", "ephemeral"}

_HIGH_CONFIDENCE_TAGS = {"verified", "tool_verified", "user_confirmed"}


def build_candidate_request(
    *,
    agent_id: str,
    session_id: str | None,
    content: str,
    tags: list[str],
    source_event_id: str | None,
    source: str,
) -> MemoryWriteCandidateRequest:
    normalized_tags = _normalize_tags(tags)
    memory_type = _infer_memory_type(normalized_tags)
    scope_hint = _infer_scope_hint(normalized_tags)
    confidence = _infer_confidence(normalized_tags)
    idempotency_key = _build_idempotency_key(
        agent_id=agent_id,
        session_id=session_id,
        source_event_id=source_event_id,
        content=content,
        tags=normalized_tags,
        source=source,
    )
    return MemoryWriteCandidateRequest(
        agent_id=agent_id,
        session_id=session_id,
        content=content.strip(),
        tags=normalized_tags,
        memory_type=memory_type,
        scope_hint=scope_hint,
        confidence=confidence,
        source_event_id=source_event_id,
        idempotency_key=idempotency_key,
        metadata={"source": source},
    )


def _normalize_tags(tags: list[str]) -> list[str]:
    dedup: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        if not isinstance(raw, str):
            continue
        tag = raw.strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        dedup.append(tag)
    return dedup


def _infer_scope_hint(tags: list[str]) -> MemoryScope:
    values = set(tags)
    if values.intersection(_SHARED_SCOPE_TAGS):
        return MemoryScope.SHARED_LONG
    if values.intersection(_LONG_SCOPE_TAGS):
        return MemoryScope.AGENT_LONG
    return MemoryScope.AGENT_SHORT


def _infer_memory_type(tags: list[str]) -> MemoryType:
    values = set(tags)
    if values.intersection(_PREFERENCE_TAGS):
        return MemoryType.PREFERENCE
    if values.intersection(_CONSTRAINT_TAGS):
        return MemoryType.CONSTRAINT
    if values.intersection(_PLAN_TAGS):
        return MemoryType.PLAN
    if values.intersection(_SCRATCH_TAGS):
        return MemoryType.SCRATCH
    return MemoryType.FACT


def _infer_confidence(tags: list[str]) -> float:
    values = set(tags)
    if values.intersection(_HIGH_CONFIDENCE_TAGS):
        return 0.9
    if "guess" in values or "draft" in values:
        return 0.5
    return 0.7


def _build_idempotency_key(
    *,
    agent_id: str,
    session_id: str | None,
    source_event_id: str | None,
    content: str,
    tags: list[str],
    source: str,
) -> str:
    base = "|".join(
        [
            agent_id.strip(),
            (session_id or "-").strip(),
            (source_event_id or "-").strip(),
            content.strip(),
            ",".join(tags),
            source.strip(),
        ]
    )
    digest = sha256(base.encode("utf-8")).hexdigest()
    return f"write:{digest}"
