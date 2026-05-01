"""MemoryRecord conversion, matching, and ranking helpers for file-backed storage."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.memory.classification import classify_memory
from app.memory.file_models import MemoryFact, format_memory_time
from app.memory.file_store_common import SCHEMA_VERSION
from app.memory.models import MemoryRecord, MemoryScope, MemoryStatus, MemoryType, make_content_hash
from app.memory.policies import TEXT_SEARCH_NAME_EXPANSIONS, should_expand_name_query


def is_long_term_fact_row(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return False
    raw_scope = metadata.get("memory_scope")
    if not isinstance(raw_scope, str):
        return False
    normalized = raw_scope.strip().lower()
    return normalized in {MemoryScope.AGENT_LONG.value, MemoryScope.SHARED_LONG.value}


def fact_row_canonical_key(row: dict[str, Any]) -> str | None:
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        raw_key = metadata.get("canonical_key")
        if isinstance(raw_key, str) and raw_key.strip():
            return raw_key.strip()
    content = str(row.get("content", "")).strip()
    if not content:
        return None
    raw_tags = row.get("tags")
    tags = [tag for tag in raw_tags if isinstance(tag, str)] if isinstance(raw_tags, list) else []
    source = "memory_store"
    if isinstance(metadata, dict):
        raw_source = metadata.get("source")
        if isinstance(raw_source, str) and raw_source.strip():
            source = raw_source.strip()
    try:
        return classify_memory(content=content, tags=tags, source=source).canonical_key
    except Exception:  # noqa: BLE001
        return None


def fact_to_record(*, fact: MemoryFact, now: datetime) -> MemoryRecord:
    scope = record_scope_for_fact(fact)
    kind = fact.metadata.get("kind", kind_for_category(fact.category))
    source_kind = fact.metadata.get("source_kind", fact.source.type)
    source_event_id = fact.source.event_ids[0] if fact.source.event_ids else None
    importance = 0.9 if fact.inject_policy == "always" else 0.65
    metadata = dict(fact.metadata)
    metadata.update(
        {
            "memory_layer": "facts",
            "storage_scope": fact.scope,
            "category": fact.category,
            "visibility": fact.visibility,
            "inject_policy": fact.inject_policy,
            "source_type": fact.source.type,
            "read_at": format_memory_time(now),
        }
    )
    return make_memory_record(
        memory_id=fact.id,
        scope=scope,
        owner_agent_id=None if fact.scope == "shared" else fact.owner_agent_id,
        session_id=fact.source.session_id,
        memory_type=memory_type_for_category(fact.category),
        content=fact.content,
        tags=fact.tags + [fact.category],
        importance=importance,
        confidence=fact.confidence,
        kind=kind,
        source_kind=source_kind,
        canonical_key=fact.metadata.get("canonical_key"),
        normalized_value=fact.metadata.get("normalized_value"),
        subject_kind=fact.metadata.get("subject_kind", "user"),
        classification_version=fact.metadata.get("classification_version", SCHEMA_VERSION),
        created_at=fact.created_at,
        updated_at=fact.updated_at,
        source_event_id=source_event_id,
        source_agent_id=fact.metadata.get("source_agent_id"),
        metadata=metadata,
    )


def make_memory_record(
    *,
    memory_id: str,
    scope: MemoryScope,
    owner_agent_id: str | None,
    session_id: str | None,
    memory_type: MemoryType,
    content: str,
    tags: list[str],
    importance: float,
    confidence: float,
    kind: str,
    source_kind: str,
    canonical_key: str | None,
    normalized_value: str | None,
    subject_kind: str,
    created_at: datetime,
    updated_at: datetime,
    metadata: dict[str, str],
    classification_version: str = SCHEMA_VERSION,
    source_event_id: str | None = None,
    source_agent_id: str | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        scope=scope,
        owner_agent_id=owner_agent_id,
        session_id=session_id,
        memory_type=memory_type,
        content=content,
        tags=tags,
        importance=importance,
        confidence=confidence,
        status=MemoryStatus.ACTIVE,
        kind=kind,
        source_kind=source_kind,
        canonical_key=canonical_key,
        normalized_value=normalized_value,
        subject_kind=subject_kind,
        classification_version=classification_version,
        created_at=created_at,
        updated_at=updated_at,
        source_event_id=source_event_id,
        source_agent_id=source_agent_id,
        content_hash=make_content_hash(content),
        metadata=metadata,
    )


def fact_scope_visible(*, record_scope: MemoryScope, include_scopes: list[MemoryScope]) -> bool:
    return record_scope in include_scopes


def record_scope_for_fact(fact: MemoryFact) -> MemoryScope:
    if fact.scope == "shared":
        return MemoryScope.SHARED_LONG
    memory_scope = fact.metadata.get("memory_scope", "").strip()
    if memory_scope == MemoryScope.AGENT_SHORT.value:
        return MemoryScope.AGENT_SHORT
    return MemoryScope.AGENT_LONG


def rank_records(records: list[MemoryRecord], query: str) -> list[MemoryRecord]:
    return sorted(
        records,
        key=lambda record: (
            match_score(content=record.content, tags=record.tags, query=query),
            _inject_policy_rank(record.metadata.get("inject_policy")),
            record.confidence,
            record.importance,
            record.updated_at,
        ),
        reverse=True,
    )


def matches_query(*, content: str, tags: list[str], query: str) -> bool:
    if query.strip() == "*":
        return True
    return match_score(content=content, tags=tags, query=query) > 0


def match_score(*, content: str, tags: list[str], query: str) -> int:
    normalized_query = query.strip().casefold()
    if normalized_query == "*":
        return 1
    haystack = (content + " " + " ".join(tags)).casefold()
    terms = _query_terms(normalized_query)
    return sum(1 for term in terms if term and term in haystack)


def dedupe_by_id(records: list[MemoryRecord]) -> list[MemoryRecord]:
    output: list[MemoryRecord] = []
    seen: set[str] = set()
    for record in records:
        if record.memory_id in seen:
            continue
        seen.add(record.memory_id)
        output.append(record)
    return output


def memory_type_for_category(category: str) -> MemoryType:
    normalized = category.strip().lower()
    if normalized == "preference":
        return MemoryType.PREFERENCE
    if normalized in {"correction", "constraint"}:
        return MemoryType.CONSTRAINT
    if normalized == "goal":
        return MemoryType.PLAN
    return MemoryType.FACT


def kind_for_category(category: str) -> str:
    normalized = category.strip().lower()
    if normalized == "preference":
        return "user_preference"
    if normalized == "behavior":
        return "interaction_pattern"
    return "user_fact"


def _query_terms(query: str) -> list[str]:
    terms: list[str] = [query]
    terms.extend(item for item in re.split(r"\s+", query) if item)
    terms.extend(_cjk_ngrams(query, min_size=2, max_size=3))
    if should_expand_name_query(query):
        terms.extend(TEXT_SEARCH_NAME_EXPANSIONS)
    output: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip().casefold()
        if not normalized or normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output


def _cjk_ngrams(value: str, *, min_size: int, max_size: int) -> list[str]:
    chars = [char for char in value if _is_cjk(char)]
    output: list[str] = []
    for size in range(min_size, max_size + 1):
        if len(chars) < size:
            continue
        output.extend("".join(chars[index : index + size]) for index in range(0, len(chars) - size + 1))
    return output


def _is_cjk(value: str) -> bool:
    if len(value) != 1:
        return False
    codepoint = ord(value)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )


def _inject_policy_rank(value: str | None) -> int:
    if value == "always":
        return 3
    if value == "on_task":
        return 2
    if value == "retrieval":
        return 1
    return 0
