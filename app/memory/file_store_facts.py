"""Fact JSONL operations for file-backed memory storage."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import ValidationError
from app.memory.file_models import MemoryFact, MemorySource, format_memory_time
from app.memory.file_store_common import require_non_empty
from app.memory.file_store_io import append_jsonl, read_jsonl_payloads, rewrite_jsonl
from app.memory.file_store_records import fact_row_canonical_key, is_long_term_fact_row
from app.memory.models import ForgetResult, make_content_hash

__all__ = [
    "append_fact_to_file",
    "archive_active_facts_by_canonical_key_in_file",
    "find_active_fact_by_canonical_key_in_file",
    "find_active_fact_by_content_in_file",
    "forget_facts_in_files",
    "has_active_fact_with_metadata_in_file",
    "has_archived_fact_by_content_in_file",
    "list_active_long_term_facts",
]

_logger = logging.getLogger(__name__)


def append_fact_to_file(
    *,
    path: Path,
    content: str,
    category: str,
    confidence: float,
    normalized_scope: str,
    normalized_owner: str | None,
    session_id: str | None,
    source_event_id: str | None,
    source_type: str,
    tags: list[str],
    inject_policy: str,
    metadata: dict[str, str],
    now: datetime,
) -> MemoryFact:
    fact = MemoryFact(
        id=f"fact_{uuid4().hex[:12]}",
        content=content,
        category=category,
        confidence=confidence,
        scope=normalized_scope,
        owner_agent_id=normalized_owner,
        visibility="shared" if normalized_scope == "shared" else "private",
        status="active",
        created_at=now,
        updated_at=now,
        source=MemorySource(
            type=source_type,
            session_id=session_id,
            event_ids=[source_event_id] if source_event_id else [],
        ),
        tags=tags,
        inject_policy=inject_policy,
        promote_state={
            "fromScope": None,
            "promotedBy": None,
            "promotedAt": None,
        },
        metadata=metadata,
    )
    append_jsonl(path, fact.to_payload())
    return fact


def has_active_fact_with_metadata_in_file(
    *,
    path: Path,
    normalized_scope: str,
    normalized_owner: str | None,
    metadata_key: str,
    metadata_value: str,
) -> bool:
    for row in read_jsonl_payloads(path):
        if str(row.get("status", "")).strip().lower() != "active":
            continue
        if str(row.get("scope", "")).strip().lower() != normalized_scope:
            continue
        if normalized_scope == "agent":
            owner = str(row.get("ownerAgentId", "")).strip()
            if owner != normalized_owner:
                continue
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            continue
        observed = metadata.get(metadata_key)
        if not isinstance(observed, str):
            continue
        if observed.strip() == metadata_value:
            return True
    return False


def find_active_fact_by_content_in_file(
    *,
    path: Path,
    normalized_scope: str,
    normalized_owner: str | None,
    content: str,
) -> MemoryFact | None:
    normalized_hash = make_content_hash(content)
    for row in read_jsonl_payloads(path):
        fact = _load_fact_or_skip(row=row, path=path, purpose="duplicate check")
        if fact is None or fact.status != "active":
            continue
        if not _fact_matches_scope(fact=fact, normalized_scope=normalized_scope, normalized_owner=normalized_owner):
            continue
        if make_content_hash(fact.content) == normalized_hash:
            return fact
    return None


def find_active_fact_by_canonical_key_in_file(
    *,
    path: Path,
    normalized_scope: str,
    normalized_owner: str | None,
    canonical_key: str,
) -> MemoryFact | None:
    for row in read_jsonl_payloads(path):
        fact = _load_fact_or_skip(row=row, path=path, purpose="canonical lookup")
        if fact is None or fact.status != "active":
            continue
        if not _fact_matches_scope(fact=fact, normalized_scope=normalized_scope, normalized_owner=normalized_owner):
            continue
        if fact_row_canonical_key(row) == canonical_key:
            return fact
    return None


def has_archived_fact_by_content_in_file(
    *,
    path: Path,
    normalized_scope: str,
    normalized_owner: str | None,
    content: str,
) -> bool:
    normalized_hash = make_content_hash(content)
    for row in read_jsonl_payloads(path):
        fact = _load_fact_or_skip(row=row, path=path, purpose="archive lookup")
        if fact is None or fact.status != "archived":
            continue
        if not _fact_matches_scope(fact=fact, normalized_scope=normalized_scope, normalized_owner=normalized_owner):
            continue
        if make_content_hash(fact.content) == normalized_hash:
            return True
    return False


def archive_active_facts_by_canonical_key_in_file(
    *,
    path: Path,
    normalized_scope: str,
    normalized_owner: str | None,
    canonical_key: str,
    reason: str,
    now: datetime,
) -> ForgetResult:
    rows = read_jsonl_payloads(path)
    rewritten: list[dict[str, Any]] = []
    changed = False
    touched = 0
    for row in rows:
        if not _active_row_matches_scope(row=row, normalized_scope=normalized_scope, normalized_owner=normalized_owner):
            rewritten.append(row)
            continue
        metadata = row.get("metadata")
        if not isinstance(metadata, dict) or fact_row_canonical_key(row) != canonical_key:
            rewritten.append(row)
            continue
        row["status"] = "archived"
        row["updatedAt"] = format_memory_time(now)
        metadata["archivedReason"] = reason
        rewritten.append(row)
        changed = True
        touched += 1
    if changed:
        rewrite_jsonl(path, rewritten)
    return ForgetResult(touched_records=touched, deleted_records=0, archived_records=touched)


def forget_facts_in_files(
    *,
    paths: list[Path],
    memory_ids: set[str],
    hard_delete: bool,
    reason: str | None,
    now: datetime,
) -> ForgetResult:
    touched = 0
    deleted = 0
    archived = 0
    for path in paths:
        rows = read_jsonl_payloads(path)
        rewritten: list[dict[str, Any]] = []
        changed = False
        for row in rows:
            memory_id = str(row.get("id", "")).strip()
            if memory_id not in memory_ids:
                rewritten.append(row)
                continue
            touched += 1
            changed = True
            if hard_delete:
                deleted += 1
                continue
            row["status"] = "archived"
            row["updatedAt"] = format_memory_time(now)
            row.setdefault("metadata", {})
            if isinstance(row["metadata"], dict):
                row["metadata"]["archivedReason"] = reason or "forget"
            rewritten.append(row)
            archived += 1
        if changed:
            rewrite_jsonl(path, rewritten)
    return ForgetResult(touched_records=touched, deleted_records=deleted, archived_records=archived)


def list_active_long_term_facts(
    *,
    path: Path,
    scope: str,
    owner_agent_id: str | None,
) -> list[MemoryFact]:
    output: list[MemoryFact] = []
    for row in read_jsonl_payloads(path):
        if not is_long_term_fact_row(row):
            continue
        fact = _load_fact_or_skip(row=row, path=path, purpose="summary refresh")
        if fact is None or fact.status != "active":
            continue
        if not _fact_matches_scope(fact=fact, normalized_scope=scope, normalized_owner=owner_agent_id):
            continue
        output.append(fact)
    return output


def _active_row_matches_scope(
    *,
    row: dict[str, Any],
    normalized_scope: str,
    normalized_owner: str | None,
) -> bool:
    if str(row.get("status", "")).strip().lower() != "active":
        return False
    if str(row.get("scope", "")).strip().lower() != normalized_scope:
        return False
    if normalized_scope == "agent":
        owner = str(row.get("ownerAgentId", "")).strip()
        return owner == normalized_owner
    return True


def _fact_matches_scope(*, fact: MemoryFact, normalized_scope: str, normalized_owner: str | None) -> bool:
    if fact.scope != normalized_scope:
        return False
    return not (normalized_scope == "agent" and fact.owner_agent_id != normalized_owner)


def _load_fact_or_skip(*, row: dict[str, Any], path: Path, purpose: str) -> MemoryFact | None:
    try:
        return MemoryFact.from_payload(row)
    except ValidationError as exc:
        _logger.warning("invalid memory fact skipped during %s: path=%s error=%s", purpose, path, exc)
        return None
