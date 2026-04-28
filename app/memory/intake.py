"""Input normalization for memory write requests."""

from __future__ import annotations

from hashlib import sha256

from app.memory.classification import classify_memory
from app.memory.models import MemoryScope, MemoryWriteCandidateRequest
from app.memory.policies import (
    infer_confidence_from_tags,
    infer_memory_type_from_tags,
    infer_scope_from_tags,
    normalize_memory_tags,
)

__all__ = ["build_candidate_request", "infer_scope_hint_from_tags"]


def build_candidate_request(
    *,
    agent_id: str,
    session_id: str | None,
    content: str,
    tags: list[str],
    source_event_id: str | None,
    source: str,
) -> MemoryWriteCandidateRequest:
    normalized_tags = normalize_memory_tags(tags)
    memory_type = infer_memory_type_from_tags(normalized_tags)
    scope_hint = infer_scope_hint_from_tags(normalized_tags)
    confidence = infer_confidence_from_tags(normalized_tags)
    classification = classify_memory(content=content, tags=normalized_tags, source=source)
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
        metadata={
            "source": source,
            **classification.to_metadata(),
        },
    )


def infer_scope_hint_from_tags(tags: list[str]) -> MemoryScope:
    return infer_scope_from_tags(tags)


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
