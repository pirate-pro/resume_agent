"""Helper functions for built-in memory tools."""

from __future__ import annotations

from datetime import UTC
from typing import Any

from app.core.errors import ToolExecutionError
from app.memory.admission import evaluate_memory_admission
from app.memory.classification import classify_memory
from app.memory.models import MemoryRecord, MemoryScope
from app.memory.policies import memory_lane_for_metadata, normalize_memory_tags, source_priority_for_kind
from app.memory.write_plan import build_memory_write_plan, infer_write_scope_from_tags
from app.domain.models import RunContext

__all__ = [
    "build_ambiguous_update_payload",
    "build_explain_payload",
    "build_no_match_update_payload",
    "build_rejected_update_payload",
    "build_semantic_noop_update_payload",
    "build_source_priority_conflict_payload",
    "build_successful_update_payload",
    "dedupe_scopes",
    "parse_bool_argument",
    "parse_limit_argument",
    "resolve_update_tags",
    "serialize_memory_record",
    "update_allowed_by_source_priority",
]


def parse_limit_argument(
    arguments: dict[str, Any],
    *,
    field_name: str,
    default: int,
    max_value: int,
) -> int:
    raw_limit = arguments.get(field_name, default)
    if not isinstance(raw_limit, int) or raw_limit <= 0:
        raise ToolExecutionError(f"'{field_name}' must be a positive integer.")
    return min(raw_limit, max_value)


def parse_bool_argument(arguments: dict[str, Any], *, field_name: str, default: bool) -> bool:
    value = arguments.get(field_name, default)
    if not isinstance(value, bool):
        raise ToolExecutionError(f"'{field_name}' must be boolean.")
    return value


def build_explain_payload(
    *,
    context: RunContext,
    content: str,
    tags: list[str],
    source: str,
) -> dict[str, Any]:
    normalized_tags = normalize_memory_tags(tags)
    admission = evaluate_memory_admission(content, normalized_tags)
    plan = build_memory_write_plan(
        agent_id=context.agent_id,
        session_id=context.session_id,
        content=content,
        tags=normalized_tags,
        source_event_id=None,
        source=source,
    )
    lane = memory_lane_for_metadata(plan.canonical_key, plan.kind)
    return {
        "content": content,
        "tags": normalized_tags,
        "source": source,
        "admission": {
            "accepted": admission.accepted,
            "decision": admission.decision.value,
            "reason": admission.reason,
        },
        "write_plan": {
            "scope": plan.scope.value,
            "memory_type": plan.memory_type.value,
            "category": plan.category,
            "confidence": plan.confidence,
            "inject_policy": plan.inject_policy,
        },
        "classification": {
            "kind": plan.kind,
            "source_kind": plan.source_kind,
            "canonical_key": plan.canonical_key,
            "normalized_value": plan.normalized_value,
            "subject_kind": plan.subject_kind,
            "classification_version": plan.classification_version,
        },
        "lane": lane,
        "dry_run": True,
    }


def dedupe_scopes(scopes: list[MemoryScope]) -> list[MemoryScope]:
    output: list[MemoryScope] = []
    seen: set[MemoryScope] = set()
    for item in scopes:
        if not isinstance(item, MemoryScope):
            continue
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def resolve_update_tags(
    *,
    new_tags: list[str],
    target_scope: MemoryScope,
    target_tags: list[str],
) -> list[str]:
    tags = list(new_tags) if new_tags else [tag.strip() for tag in target_tags if isinstance(tag, str) and tag.strip()]
    if not tags:
        tags = []

    write_scope = infer_write_scope_from_tags(tags)
    if target_scope == MemoryScope.SHARED_LONG and write_scope != MemoryScope.SHARED_LONG:
        if "shared" not in tags:
            tags.append("shared")
    if target_scope == MemoryScope.AGENT_LONG and write_scope == MemoryScope.AGENT_SHORT:
        if "long_term" not in tags:
            tags.append("long_term")
    return tags


def update_allowed_by_source_priority(*, new_content: str, tags: list[str], target: MemoryRecord) -> bool:
    update_classification = classify_memory(
        content=new_content,
        tags=tags,
        source="memory_update_tool",
    )
    return source_priority_for_kind(update_classification.source_kind) >= source_priority_for_kind(target.source_kind)


def build_no_match_update_payload(*, query: str, match_strategy: str) -> dict[str, Any]:
    return {
        "updated": False,
        "reason": "no_match",
        "query": query,
        "match_strategy": match_strategy,
    }


def build_ambiguous_update_payload(
    *,
    query: str,
    match_strategy: str,
    candidates: list[MemoryRecord],
) -> dict[str, Any]:
    return {
        "updated": False,
        "reason": "ambiguous_match",
        "query": query,
        "match_strategy": match_strategy,
        "candidates": [
            {
                "memory_id": item.memory_id,
                "scope": item.scope.value,
                "content": item.content,
                "tags": item.tags,
                "confidence": item.confidence,
            }
            for item in candidates
        ],
    }


def build_rejected_update_payload(
    *,
    reason: str,
    query: str,
    match_strategy: str,
    target: MemoryRecord,
    resolved_tags: list[str],
) -> dict[str, Any]:
    return {
        "updated": False,
        "reason": reason,
        "query": query,
        "match_strategy": match_strategy,
        "update_mode": "archive_then_write",
        "old_memory_id": target.memory_id,
        "old_scope": target.scope.value,
        "new_tags": resolved_tags,
    }


def build_source_priority_conflict_payload(
    *,
    query: str,
    match_strategy: str,
    target: MemoryRecord,
    resolved_tags: list[str],
) -> dict[str, Any]:
    return build_rejected_update_payload(
        reason="source_priority_conflict",
        query=query,
        match_strategy=match_strategy,
        target=target,
        resolved_tags=resolved_tags,
    )


def build_semantic_noop_update_payload(
    *,
    query: str,
    match_strategy: str,
    target: MemoryRecord,
    resolved_tags: list[str],
    forget_result: Any,
) -> dict[str, Any]:
    payload = build_rejected_update_payload(
        reason="semantic_noop",
        query=query,
        match_strategy=match_strategy,
        target=target,
        resolved_tags=resolved_tags,
    )
    payload["forget_result"] = _forget_result_payload(forget_result)
    return payload


def build_successful_update_payload(
    *,
    match_strategy: str,
    target: MemoryRecord,
    new_memory_id: str,
    resolved_tags: list[str],
    forget_result: Any,
) -> dict[str, Any]:
    return {
        "updated": True,
        "match_strategy": match_strategy,
        "update_mode": "archive_then_write",
        "old_memory_id": target.memory_id,
        "new_memory_id": new_memory_id,
        "new_tags": resolved_tags,
        "old_scope": target.scope.value,
        "forget_result": _forget_result_payload(forget_result),
    }


def serialize_memory_record(record: MemoryRecord, *, include_metadata: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "memory_id": record.memory_id,
        "scope": record.scope.value,
        "owner_agent_id": record.owner_agent_id,
        "session_id": record.session_id,
        "status": record.status.value,
        "memory_type": record.memory_type.value,
        "content": record.content,
        "tags": record.tags,
        "importance": record.importance,
        "confidence": record.confidence,
        "canonical_key": record.canonical_key,
        "normalized_value": record.normalized_value,
        "kind": record.kind,
        "source_kind": record.source_kind,
        "subject_kind": record.subject_kind,
        "classification_version": record.classification_version,
        "lane": memory_lane_for_metadata(record.canonical_key, record.kind),
        "created_at": record.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "updated_at": record.updated_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "expires_at": None
        if record.expires_at is None
        else record.expires_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "source_event_id": record.source_event_id,
        "source_agent_id": record.source_agent_id,
        "version": record.version,
        "parent_memory_id": record.parent_memory_id,
        "content_hash": record.content_hash,
    }
    if include_metadata:
        payload["metadata"] = record.metadata
    return payload


def _forget_result_payload(forget_result: Any) -> dict[str, int]:
    return {
        "touched": int(forget_result.touched_records),
        "deleted": int(forget_result.deleted_records),
        "archived": int(forget_result.archived_records),
    }
