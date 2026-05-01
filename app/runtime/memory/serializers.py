"""Serialization helpers for runtime memory operations."""

from __future__ import annotations

from typing import Any

from app.domain.models import MemoryItem
from app.memory.file_models import MemoryFact
from app.memory.models import MemoryReadBundle, MemoryRecord, MemoryScope
from app.memory.write_plan import MemoryWritePlan


def build_search_summary(
    *,
    query: str,
    agent_id: str,
    session_id: str,
    bundle: MemoryReadBundle,
    hit_count: int,
) -> dict[str, Any]:
    return {
        "query": query,
        "agent_id": agent_id,
        "session_id": session_id,
        "hit_count": hit_count,
        "searched_scopes": [scope.value for scope in bundle.searched_scopes],
        "total_scanned": bundle.total_scanned,
        "truncated": bundle.truncated,
        "notes": bundle.notes,
    }


def memory_metadata_from_plan(
    *,
    plan: MemoryWritePlan,
    source_agent_id: str,
    target_agent_id: str,
) -> dict[str, str]:
    metadata: dict[str, str] = {
        "source_agent_id": source_agent_id,
        "target_agent_id": target_agent_id,
        "memory_type": plan.memory_type.value,
        "memory_scope": plan.scope.value,
        "kind": plan.kind,
        "source_kind": plan.source_kind,
        "subject_kind": plan.subject_kind,
        "classification_version": plan.classification_version,
        "write_key": plan.write_key,
    }
    if plan.canonical_key:
        metadata["canonical_key"] = plan.canonical_key
    if plan.normalized_value:
        metadata["normalized_value"] = plan.normalized_value
    raw_source = plan.metadata.get("source") if isinstance(plan.metadata, dict) else None
    if isinstance(raw_source, str) and raw_source.strip():
        metadata["source"] = raw_source.strip()
    return metadata


def to_memory_item(record: MemoryRecord) -> MemoryItem:
    raw_scope = getattr(record, "scope", None)
    if isinstance(raw_scope, MemoryScope):
        scope = raw_scope.value
    elif raw_scope is None:
        scope = None
    else:
        scope = str(raw_scope)
    metadata = getattr(record, "metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    memory_layer = metadata.get("memory_layer")
    source_kind = getattr(record, "source_kind", None)
    return MemoryItem(
        memory_id=record.memory_id,
        session_id=record.session_id,
        content=record.content,
        tags=record.tags,
        created_at=record.created_at,
        source_event_id=record.source_event_id,
        scope=scope,
        memory_layer=str(memory_layer) if memory_layer else None,
        source_kind=str(source_kind) if source_kind else None,
        metadata={str(key): str(value) for key, value in metadata.items()},
    )


def memory_item_from_fact(
    *,
    fact: MemoryFact,
    session_id: str,
    scope: MemoryScope,
    source_kind: str,
) -> MemoryItem:
    metadata = dict(fact.metadata)
    metadata.update(
        {
            "memory_layer": "facts",
            "storage_scope": fact.scope,
            "category": fact.category,
            "visibility": fact.visibility,
            "inject_policy": fact.inject_policy,
            "duplicate_write": "true",
        }
    )
    source_event_id = fact.source.event_ids[0] if fact.source.event_ids else None
    return MemoryItem(
        memory_id=fact.id,
        session_id=session_id,
        content=fact.content,
        tags=fact.tags,
        created_at=fact.created_at,
        source_event_id=source_event_id,
        scope=scope.value,
        memory_layer="facts",
        source_kind=source_kind,
        metadata={str(key): str(value) for key, value in metadata.items()},
    )
