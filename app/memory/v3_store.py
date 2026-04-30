"""File-backed v3 memory store.

The v3 layout keeps durable memory human-readable and agent-isolated:

data/memory_v3/
  shared/{long_term.json,facts.jsonl,pending_promotions.jsonl,mid_term/...}
  agents/<agent_id>/{long_term_overlay.json,facts.jsonl,mid_term/...}
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import StorageError, ValidationError
from app.memory.classification import classify_memory
from app.memory.models import (
    ForgetResult,
    MemoryReadBundle,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    make_content_hash,
)
from app.memory.policies import TEXT_SEARCH_NAME_EXPANSIONS, should_expand_name_query
from app.memory.v3_models import MemoryV3Fact, MemoryV3Source, format_memory_v3_time

__all__ = ["FileMemoryV3Store"]

_logger = logging.getLogger(__name__)
_SCHEMA_VERSION = "3.0"
_MID_TERM_DAILY_LIMIT = 6
_MID_TERM_MAX_CHARS = 2400

_LONG_TERM_SECTIONS = (
    ("user", "workContext", "User work context"),
    ("user", "personalContext", "User personal context"),
    ("user", "topOfMind", "User top of mind"),
    ("history", "recentMonths", "Recent months"),
    ("history", "earlierContext", "Earlier context"),
    ("history", "longTermBackground", "Long-term background"),
)


class FileMemoryV3Store:
    """Read and write memory_v3 files without a derived database index."""

    def __init__(self, root_dir: Path) -> None:
        if not isinstance(root_dir, Path):
            raise ValidationError("root_dir must be pathlib.Path.")
        self._root_dir = root_dir
        self._ensure_shared_layout()

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def append_fact(
        self,
        *,
        content: str,
        category: str,
        confidence: float,
        scope: MemoryScope,
        owner_agent_id: str | None,
        session_id: str | None,
        source_event_id: str | None,
        source_type: str,
        tags: list[str],
        inject_policy: str,
        metadata: dict[str, str],
        now: datetime | None = None,
    ) -> MemoryV3Fact:
        normalized_now = _normalize_datetime(now or datetime.now(UTC))
        normalized_scope, normalized_owner = _to_v3_scope(scope=scope, owner_agent_id=owner_agent_id)
        fact = MemoryV3Fact(
            id=f"fact_{uuid4().hex[:12]}",
            content=content,
            category=category,
            confidence=confidence,
            scope=normalized_scope,
            owner_agent_id=normalized_owner,
            visibility="shared" if normalized_scope == "shared" else "private",
            status="active",
            created_at=normalized_now,
            updated_at=normalized_now,
            source=MemoryV3Source(
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
        path = self._facts_path(scope=fact.scope, agent_id=fact.owner_agent_id)
        self._append_jsonl(path, fact.to_payload())
        return fact

    def refresh_long_term_summary_from_facts(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        now: datetime | None = None,
    ) -> dict[str, str]:
        if scope not in {MemoryScope.SHARED_LONG, MemoryScope.AGENT_LONG}:
            raise ValidationError("long-term summary refresh only supports shared_long/agent_long.")
        normalized_now = _normalize_datetime(now or datetime.now(UTC))
        normalized_scope, normalized_owner = _to_v3_scope(scope=scope, owner_agent_id=agent_id)
        long_term_path = self._long_term_path(scope=normalized_scope, agent_id=normalized_owner)
        facts_path = self._facts_path(scope=normalized_scope, agent_id=normalized_owner)
        payload = self._read_json_payload(long_term_path)
        facts = self._list_active_facts(scope=normalized_scope, owner_agent_id=normalized_owner, path=facts_path)
        summaries = _build_long_term_summaries_from_facts(facts)
        refreshed_at = format_memory_v3_time(normalized_now)
        _set_long_term_section(payload, group="user", key="workContext", summary=summaries["user.workContext"], refreshed_at=refreshed_at)
        _set_long_term_section(
            payload,
            group="user",
            key="personalContext",
            summary=summaries["user.personalContext"],
            refreshed_at=refreshed_at,
        )
        _set_long_term_section(payload, group="user", key="topOfMind", summary=summaries["user.topOfMind"], refreshed_at=refreshed_at)
        _set_long_term_section(
            payload,
            group="history",
            key="recentMonths",
            summary=summaries["history.recentMonths"],
            refreshed_at=refreshed_at,
        )
        _set_long_term_section(
            payload,
            group="history",
            key="earlierContext",
            summary=summaries["history.earlierContext"],
            refreshed_at=refreshed_at,
        )
        _set_long_term_section(
            payload,
            group="history",
            key="longTermBackground",
            summary=summaries["history.longTermBackground"],
            refreshed_at=refreshed_at,
        )
        payload["lastUpdated"] = refreshed_at
        self._write_json_payload(long_term_path, payload)
        return summaries

    def has_active_fact_with_metadata(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        metadata_key: str,
        metadata_value: str,
    ) -> bool:
        normalized_key = _require_non_empty("metadata_key", metadata_key)
        normalized_value = _require_non_empty("metadata_value", metadata_value)
        normalized_scope, normalized_owner = _to_v3_scope(scope=scope, owner_agent_id=agent_id)
        path = self._facts_path(scope=normalized_scope, agent_id=normalized_owner)
        for row in self._read_jsonl_payloads(path):
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
            observed = metadata.get(normalized_key)
            if not isinstance(observed, str):
                continue
            if observed.strip() == normalized_value:
                return True
        return False

    def find_active_fact_by_content(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        content: str,
    ) -> MemoryV3Fact | None:
        normalized_content = _require_non_empty("content", content)
        normalized_hash = make_content_hash(normalized_content)
        normalized_scope, normalized_owner = _to_v3_scope(scope=scope, owner_agent_id=agent_id)
        path = self._facts_path(scope=normalized_scope, agent_id=normalized_owner)
        for row in self._read_jsonl_payloads(path):
            try:
                fact = MemoryV3Fact.from_payload(row)
            except ValidationError as exc:
                _logger.warning("invalid memory_v3 fact skipped during duplicate check: path=%s error=%s", path, exc)
                continue
            if fact.status != "active":
                continue
            if fact.scope != normalized_scope:
                continue
            if normalized_scope == "agent" and fact.owner_agent_id != normalized_owner:
                continue
            if make_content_hash(fact.content) == normalized_hash:
                return fact
        return None

    def find_active_fact_by_canonical_key(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        canonical_key: str,
    ) -> MemoryV3Fact | None:
        normalized_key = _require_non_empty("canonical_key", canonical_key)
        normalized_scope, normalized_owner = _to_v3_scope(scope=scope, owner_agent_id=agent_id)
        path = self._facts_path(scope=normalized_scope, agent_id=normalized_owner)
        for row in self._read_jsonl_payloads(path):
            try:
                fact = MemoryV3Fact.from_payload(row)
            except ValidationError as exc:
                _logger.warning("invalid memory_v3 fact skipped during canonical lookup: path=%s error=%s", path, exc)
                continue
            if fact.status != "active":
                continue
            if fact.scope != normalized_scope:
                continue
            if normalized_scope == "agent" and fact.owner_agent_id != normalized_owner:
                continue
            if _fact_row_canonical_key(row) == normalized_key:
                return fact
        return None

    def has_archived_fact_by_content(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        content: str,
    ) -> bool:
        normalized_content = _require_non_empty("content", content)
        normalized_hash = make_content_hash(normalized_content)
        normalized_scope, normalized_owner = _to_v3_scope(scope=scope, owner_agent_id=agent_id)
        path = self._facts_path(scope=normalized_scope, agent_id=normalized_owner)
        for row in self._read_jsonl_payloads(path):
            try:
                fact = MemoryV3Fact.from_payload(row)
            except ValidationError as exc:
                _logger.warning("invalid memory_v3 fact skipped during archive lookup: path=%s error=%s", path, exc)
                continue
            if fact.status != "archived":
                continue
            if fact.scope != normalized_scope:
                continue
            if normalized_scope == "agent" and fact.owner_agent_id != normalized_owner:
                continue
            if make_content_hash(fact.content) == normalized_hash:
                return True
        return False

    def archive_active_facts_by_canonical_key(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        canonical_key: str,
        reason: str,
        now: datetime | None = None,
    ) -> ForgetResult:
        normalized_key = _require_non_empty("canonical_key", canonical_key)
        normalized_reason = _require_non_empty("reason", reason)
        normalized_now = _normalize_datetime(now or datetime.now(UTC))
        normalized_scope, normalized_owner = _to_v3_scope(scope=scope, owner_agent_id=agent_id)
        path = self._facts_path(scope=normalized_scope, agent_id=normalized_owner)
        rows = self._read_jsonl_payloads(path)
        rewritten: list[dict[str, Any]] = []
        changed = False
        touched = 0
        for row in rows:
            if str(row.get("status", "")).strip().lower() != "active":
                rewritten.append(row)
                continue
            if str(row.get("scope", "")).strip().lower() != normalized_scope:
                rewritten.append(row)
                continue
            if normalized_scope == "agent":
                owner = str(row.get("ownerAgentId", "")).strip()
                if owner != normalized_owner:
                    rewritten.append(row)
                    continue
            metadata = row.get("metadata")
            if not isinstance(metadata, dict) or _fact_row_canonical_key(row) != normalized_key:
                rewritten.append(row)
                continue
            row["status"] = "archived"
            row["updatedAt"] = format_memory_v3_time(normalized_now)
            metadata["archivedReason"] = normalized_reason
            rewritten.append(row)
            changed = True
            touched += 1
        if changed:
            self._rewrite_jsonl(path, rewritten)
        return ForgetResult(touched_records=touched, deleted_records=0, archived_records=touched)

    def read_bundle(
        self,
        *,
        agent_id: str,
        query: str,
        limit: int,
        include_scopes: list[MemoryScope],
        short_session_id: str | None = None,
        standing_only: bool = False,
        include_long_term_summaries: bool = False,
        now: datetime | None = None,
    ) -> MemoryReadBundle:
        normalized_agent_id = _require_non_empty("agent_id", agent_id)
        normalized_query = _require_non_empty("query", query)
        normalized_limit = _normalize_limit(limit)
        normalized_now = _normalize_datetime(now or datetime.now(UTC))
        include_shared = MemoryScope.SHARED_LONG in include_scopes
        include_agent = MemoryScope.AGENT_LONG in include_scopes or MemoryScope.AGENT_SHORT in include_scopes
        if include_agent:
            self._ensure_agent_layout(normalized_agent_id)

        collected: list[MemoryRecord] = []
        scanned = 0
        notes: list[str] = []
        try:
            if include_shared:
                shared_records = self._read_scope_records(
                    scope="shared",
                    agent_id=None,
                    query=normalized_query,
                    now=normalized_now,
                    standing_only=standing_only,
                    include_long_term_summaries=include_long_term_summaries,
                    include_scopes=include_scopes,
                    short_session_id=short_session_id,
                )
                scanned += len(shared_records)
                collected.extend(shared_records)
            if include_agent:
                agent_records = self._read_scope_records(
                    scope="agent",
                    agent_id=normalized_agent_id,
                    query=normalized_query,
                    now=normalized_now,
                    standing_only=standing_only,
                    include_long_term_summaries=include_long_term_summaries,
                    include_scopes=include_scopes,
                    short_session_id=short_session_id,
                )
                scanned += len(agent_records)
                collected.extend(agent_records)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            _logger.exception(
                "memory_v3 read failed: agent_id=%s query=%s error=%s",
                normalized_agent_id,
                normalized_query,
                exc,
            )
            notes.append(f"memory_v3 read_failed: {exc}")

        ranked = _rank_records(_dedupe_by_id(collected), normalized_query)
        return MemoryReadBundle(
            items=ranked[:normalized_limit],
            searched_scopes=list(include_scopes),
            total_scanned=scanned,
            truncated=len(ranked) > normalized_limit,
            notes=notes,
        )

    def forget(
        self,
        *,
        agent_id: str,
        memory_ids: list[str],
        scopes: list[MemoryScope],
        hard_delete: bool,
        reason: str | None,
        now: datetime | None = None,
    ) -> ForgetResult:
        normalized_agent_id = _require_non_empty("agent_id", agent_id)
        normalized_ids = _normalize_memory_ids(memory_ids)
        normalized_now = _normalize_datetime(now or datetime.now(UTC))
        include_shared = MemoryScope.SHARED_LONG in scopes
        include_agent = MemoryScope.AGENT_LONG in scopes or MemoryScope.AGENT_SHORT in scopes
        touched = 0
        deleted = 0
        archived = 0

        paths: list[Path] = []
        if include_shared:
            paths.append(self._facts_path(scope="shared", agent_id=None))
        if include_agent:
            self._ensure_agent_layout(normalized_agent_id)
            paths.append(self._facts_path(scope="agent", agent_id=normalized_agent_id))

        for path in paths:
            rows = self._read_jsonl_payloads(path)
            rewritten: list[dict[str, Any]] = []
            changed = False
            for row in rows:
                memory_id = str(row.get("id", "")).strip()
                if memory_id not in normalized_ids:
                    rewritten.append(row)
                    continue
                touched += 1
                changed = True
                if hard_delete:
                    deleted += 1
                    continue
                row["status"] = "archived"
                row["updatedAt"] = format_memory_v3_time(normalized_now)
                row.setdefault("metadata", {})
                if isinstance(row["metadata"], dict):
                    row["metadata"]["archivedReason"] = reason or "forget"
                rewritten.append(row)
                archived += 1
            if changed:
                self._rewrite_jsonl(path, rewritten)
        return ForgetResult(touched_records=touched, deleted_records=deleted, archived_records=archived)

    def _read_scope_records(
        self,
        *,
        scope: str,
        agent_id: str | None,
        query: str,
        now: datetime,
        standing_only: bool,
        include_long_term_summaries: bool,
        include_scopes: list[MemoryScope],
        short_session_id: str | None,
    ) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        if include_long_term_summaries:
            records.extend(self._read_long_term_records(scope=scope, agent_id=agent_id, query=query, now=now))
        records.extend(
            self._read_fact_records(
                scope=scope,
                agent_id=agent_id,
                query=query,
                now=now,
                standing_only=standing_only,
                include_scopes=include_scopes,
                short_session_id=short_session_id,
            )
        )
        if not standing_only:
            records.extend(self._read_mid_term_records(scope=scope, agent_id=agent_id, query=query, now=now))
        return records

    def _list_active_facts(
        self,
        *,
        scope: str,
        owner_agent_id: str | None,
        path: Path,
    ) -> list[MemoryV3Fact]:
        output: list[MemoryV3Fact] = []
        for row in self._read_jsonl_payloads(path):
            if not _is_long_term_fact_row(row):
                continue
            try:
                fact = MemoryV3Fact.from_payload(row)
            except ValidationError as exc:
                _logger.warning("invalid memory_v3 fact skipped during summary refresh: path=%s error=%s", path, exc)
                continue
            if fact.status != "active":
                continue
            if fact.scope != scope:
                continue
            if scope == "agent" and fact.owner_agent_id != owner_agent_id:
                continue
            output.append(fact)
        return output

    def _read_long_term_records(
        self,
        *,
        scope: str,
        agent_id: str | None,
        query: str,
        now: datetime,
    ) -> list[MemoryRecord]:
        if query.strip() != "*":
            # long-term summaries are for standing/context injection; exclude from regular search/update matching.
            return []
        path = self._long_term_path(scope=scope, agent_id=agent_id)
        payload = self._read_json_payload(path)
        output: list[MemoryRecord] = []
        for group, key, label in _LONG_TERM_SECTIONS:
            raw_section = payload.get(group, {}).get(key, {})
            if not isinstance(raw_section, dict):
                continue
            summary = str(raw_section.get("summary", "")).strip()
            if not summary:
                continue
            content = f"{label}: {summary}"
            if not _matches_query(content=content, tags=["long_term", group, key], query=query):
                continue
            updated_at = _parse_optional_time(raw_section.get("updatedAt")) or now
            record_id = _long_term_record_id(scope=scope, agent_id=agent_id, group=group, key=key)
            output.append(
                _make_memory_record(
                    memory_id=record_id,
                    scope=MemoryScope.SHARED_LONG if scope == "shared" else MemoryScope.AGENT_LONG,
                    owner_agent_id=None if scope == "shared" else agent_id,
                    session_id=None,
                    memory_type=MemoryType.FACT,
                    content=content,
                    tags=["long_term", group, key],
                    importance=0.85,
                    confidence=0.9,
                    kind="user_fact",
                    source_kind="long_term_summary",
                    canonical_key=None,
                    normalized_value=None,
                    subject_kind="user",
                    created_at=updated_at,
                    updated_at=updated_at,
                    metadata={
                        "memory_layer": "long_term",
                        "v3_scope": scope,
                        "section": f"{group}.{key}",
                        "inject_policy": "always",
                    },
                )
            )
        return output

    def _read_fact_records(
        self,
        *,
        scope: str,
        agent_id: str | None,
        query: str,
        now: datetime,
        standing_only: bool,
        include_scopes: list[MemoryScope],
        short_session_id: str | None,
    ) -> list[MemoryRecord]:
        output: list[MemoryRecord] = []
        path = self._facts_path(scope=scope, agent_id=agent_id)
        for row in self._read_jsonl_payloads(path):
            try:
                fact = MemoryV3Fact.from_payload(row)
            except ValidationError as exc:
                _logger.warning("invalid memory_v3 fact skipped: path=%s error=%s row=%s", path, exc, row)
                continue
            if fact.status != "active":
                continue
            if standing_only and fact.inject_policy != "always":
                continue
            if fact.scope != scope:
                continue
            if scope == "agent" and fact.owner_agent_id != agent_id:
                continue
            record_scope = _record_scope_for_fact(fact)
            if not _fact_scope_visible(record_scope=record_scope, include_scopes=include_scopes):
                continue
            if record_scope == MemoryScope.AGENT_SHORT and short_session_id and fact.source.session_id != short_session_id:
                continue
            if not _matches_query(content=fact.content, tags=fact.tags + [fact.category], query=query):
                continue
            output.append(_fact_to_record(fact=fact, now=now))
        return output

    def _read_mid_term_records(
        self,
        *,
        scope: str,
        agent_id: str | None,
        query: str,
        now: datetime,
    ) -> list[MemoryRecord]:
        base_dir = self._mid_term_dir(scope=scope, agent_id=agent_id)
        candidates = [base_dir / "rolling.md"]
        daily_dir = base_dir / "daily"
        if daily_dir.exists():
            candidates.extend(sorted(daily_dir.glob("*.md"), reverse=True)[:_MID_TERM_DAILY_LIMIT])

        output: list[MemoryRecord] = []
        for path in candidates:
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise StorageError(f"Failed to read memory_v3 mid_term file '{path}': {exc}") from exc
            if not content:
                continue
            if content.strip() == "# Rolling Context":
                continue
            tags = ["mid_term", "rolling" if path.name == "rolling.md" else "daily"]
            if not _matches_query(content=content, tags=tags, query=query):
                continue
            clipped = _clip_text(content, max_chars=_MID_TERM_MAX_CHARS)
            stat = path.stat()
            updated_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            memory_id = _mid_term_record_id(scope=scope, agent_id=agent_id, path=path)
            output.append(
                _make_memory_record(
                    memory_id=memory_id,
                    scope=MemoryScope.SHARED_LONG if scope == "shared" else MemoryScope.AGENT_LONG,
                    owner_agent_id=None if scope == "shared" else agent_id,
                    session_id=None,
                    memory_type=MemoryType.FACT,
                    content=f"Mid-term context from {path.name}: {clipped}",
                    tags=tags,
                    importance=0.45,
                    confidence=0.6,
                    kind="mid_term_context",
                    source_kind="mid_term_note",
                    canonical_key=None,
                    normalized_value=None,
                    subject_kind="context",
                    created_at=updated_at,
                    updated_at=updated_at,
                    metadata={
                        "memory_layer": "mid_term",
                        "v3_scope": scope,
                        "path": str(path.relative_to(self._root_dir)),
                        "inject_policy": "retrieval",
                    },
                )
            )
        return output

    def _ensure_shared_layout(self) -> None:
        (self._root_dir / "shared" / "mid_term" / "daily").mkdir(parents=True, exist_ok=True)
        self._ensure_file(self._root_dir / "shared" / "facts.jsonl")
        self._ensure_file(self._root_dir / "shared" / "pending_promotions.jsonl")
        self._ensure_file(self._root_dir / "shared" / "mid_term" / "rolling.md", "# Rolling Context\n")
        self._ensure_long_term_file(self._root_dir / "shared" / "long_term.json", scope="shared", agent_id=None)

    def _ensure_agent_layout(self, agent_id: str) -> None:
        normalized = _require_non_empty("agent_id", agent_id)
        agent_dir = self._root_dir / "agents" / normalized
        (agent_dir / "mid_term" / "daily").mkdir(parents=True, exist_ok=True)
        self._ensure_file(agent_dir / "facts.jsonl")
        self._ensure_file(agent_dir / "mid_term" / "rolling.md", "# Rolling Context\n")
        self._ensure_long_term_file(agent_dir / "long_term_overlay.json", scope="agent", agent_id=normalized)

    def _long_term_path(self, *, scope: str, agent_id: str | None) -> Path:
        if scope == "shared":
            self._ensure_shared_layout()
            return self._root_dir / "shared" / "long_term.json"
        if scope == "agent" and agent_id:
            self._ensure_agent_layout(agent_id)
            return self._root_dir / "agents" / agent_id / "long_term_overlay.json"
        raise ValidationError("invalid long_term path scope.")

    def _facts_path(self, *, scope: str, agent_id: str | None) -> Path:
        if scope == "shared":
            self._ensure_shared_layout()
            return self._root_dir / "shared" / "facts.jsonl"
        if scope == "agent" and agent_id:
            self._ensure_agent_layout(agent_id)
            return self._root_dir / "agents" / agent_id / "facts.jsonl"
        raise ValidationError("invalid facts path scope.")

    def _mid_term_dir(self, *, scope: str, agent_id: str | None) -> Path:
        if scope == "shared":
            self._ensure_shared_layout()
            return self._root_dir / "shared" / "mid_term"
        if scope == "agent" and agent_id:
            self._ensure_agent_layout(agent_id)
            return self._root_dir / "agents" / agent_id / "mid_term"
        raise ValidationError("invalid mid_term path scope.")

    def _ensure_file(self, path: Path, initial_content: str = "") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return
        try:
            path.write_text(initial_content, encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"Failed to initialize memory_v3 file '{path}': {exc}") from exc

    def _ensure_long_term_file(self, path: Path, *, scope: str, agent_id: str | None) -> None:
        if path.exists():
            return
        now = format_memory_v3_time(datetime.now(UTC))
        payload = _empty_long_term_payload(scope=scope, agent_id=agent_id, now=now)
        self._write_json_payload(path, payload)

    def _read_json_payload(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise StorageError(f"Failed to read memory_v3 JSON file '{path}': {exc}") from exc
        except json.JSONDecodeError as exc:
            raise StorageError(f"Invalid memory_v3 JSON file '{path}': {exc}") from exc
        if not isinstance(payload, dict):
            raise StorageError(f"Invalid memory_v3 JSON object '{path}'.")
        return {str(key): value for key, value in payload.items()}

    def _write_json_payload(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp_path.replace(path)
        except OSError as exc:
            raise StorageError(f"Failed to write memory_v3 JSON file '{path}': {exc}") from exc

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError as exc:
            raise StorageError(f"Failed to append memory_v3 JSONL file '{path}': {exc}") from exc

    def _read_jsonl_payloads(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        output: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    raw = line.strip()
                    if not raw:
                        continue
                    payload = json.loads(raw)
                    if isinstance(payload, dict):
                        output.append(payload)
        except OSError as exc:
            raise StorageError(f"Failed to read memory_v3 JSONL file '{path}': {exc}") from exc
        except json.JSONDecodeError as exc:
            raise StorageError(f"Invalid memory_v3 JSONL file '{path}': {exc}") from exc
        return output

    def _rewrite_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            tmp_path.replace(path)
        except OSError as exc:
            raise StorageError(f"Failed to rewrite memory_v3 JSONL file '{path}': {exc}") from exc


def _empty_long_term_payload(*, scope: str, agent_id: str | None, now: str) -> dict[str, Any]:
    def section() -> dict[str, Any]:
        return {"summary": "", "updatedAt": None}

    return {
        "version": _SCHEMA_VERSION,
        "scope": scope,
        "ownerAgentId": agent_id,
        "lastUpdated": now,
        "user": {
            "workContext": section(),
            "personalContext": section(),
            "topOfMind": section(),
        },
        "history": {
            "recentMonths": section(),
            "earlierContext": section(),
            "longTermBackground": section(),
        },
    }


def _set_long_term_section(
    payload: dict[str, Any],
    *,
    group: str,
    key: str,
    summary: str,
    refreshed_at: str,
) -> None:
    group_obj = payload.get(group)
    if not isinstance(group_obj, dict):
        group_obj = {}
        payload[group] = group_obj
    section_obj = group_obj.get(key)
    if not isinstance(section_obj, dict):
        section_obj = {}
        group_obj[key] = section_obj
    section_obj["summary"] = summary
    section_obj["updatedAt"] = refreshed_at


def _build_long_term_summaries_from_facts(facts: list[MemoryV3Fact]) -> dict[str, str]:
    sorted_facts = sorted([fact for fact in facts if _is_standing_summary_fact(fact)], key=lambda item: item.updated_at, reverse=True)
    preference_facts = [
        item
        for item in sorted_facts
        if item.category in {"preference", "behavior", "correction"}
        or _has_any_tag(item.tags, {"preference", "response_style", "constraint", "rule", "policy"})
    ]
    work_context_facts = [
        item
        for item in sorted_facts
        if item.category in {"goal", "knowledge", "context"}
        or _has_any_tag(item.tags, {"goal", "knowledge", "stack", "project", "architecture", "tooling"})
    ]
    stable_background_facts = [
        item
        for item in sorted_facts
        if item.confidence >= 0.8
        or item.inject_policy == "always"
        or _has_any_tag(item.tags, {"long_term", "profile", "background"})
    ]
    recent_months_facts = sorted_facts[:8]
    earlier_context_facts = sorted(sorted_facts, key=lambda item: item.updated_at)[:6]
    top_of_mind_facts = sorted_facts[:6]
    return {
        "user.workContext": _compose_fact_bullets(work_context_facts, max_items=6),
        "user.personalContext": _compose_fact_bullets(preference_facts, max_items=6),
        "user.topOfMind": _compose_fact_bullets(top_of_mind_facts, max_items=6),
        "history.recentMonths": _compose_fact_bullets(recent_months_facts, max_items=8),
        "history.earlierContext": _compose_fact_bullets(earlier_context_facts, max_items=6),
        "history.longTermBackground": _compose_fact_bullets(stable_background_facts, max_items=6),
    }


def _is_standing_summary_fact(fact: MemoryV3Fact) -> bool:
    return fact.inject_policy == "always"


def _compose_fact_bullets(facts: list[MemoryV3Fact], *, max_items: int) -> str:
    if not facts or max_items <= 0:
        return ""
    lines: list[str] = []
    seen: set[str] = set()
    for fact in facts:
        content = _normalize_summary_line(fact.content)
        if not content:
            continue
        fingerprint = content.casefold()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        lines.append(f"- {content}")
        if len(lines) >= max_items:
            break
    return "\n".join(lines)


def _normalize_summary_line(content: str) -> str:
    normalized = " ".join(content.strip().split())
    if not normalized:
        return ""
    if len(normalized) <= 140:
        return normalized
    return normalized[:137].rstrip() + "..."


def _has_any_tag(tags: list[str], expected: set[str]) -> bool:
    normalized = {tag.strip().lower() for tag in tags if isinstance(tag, str) and tag.strip()}
    return bool(normalized.intersection(expected))


def _is_long_term_fact_row(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return False
    raw_scope = metadata.get("memory_scope")
    if not isinstance(raw_scope, str):
        return False
    normalized = raw_scope.strip().lower()
    return normalized in {MemoryScope.AGENT_LONG.value, MemoryScope.SHARED_LONG.value}


def _fact_row_canonical_key(row: dict[str, Any]) -> str | None:
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
    source = "memory_v3_store"
    if isinstance(metadata, dict):
        raw_source = metadata.get("source")
        if isinstance(raw_source, str) and raw_source.strip():
            source = raw_source.strip()
    try:
        return classify_memory(content=content, tags=tags, source=source).canonical_key
    except Exception:  # noqa: BLE001
        return None


def _fact_to_record(*, fact: MemoryV3Fact, now: datetime) -> MemoryRecord:
    scope = _record_scope_for_fact(fact)
    kind = fact.metadata.get("kind", _kind_for_category(fact.category))
    source_kind = fact.metadata.get("source_kind", fact.source.type)
    source_event_id = fact.source.event_ids[0] if fact.source.event_ids else None
    importance = 0.9 if fact.inject_policy == "always" else 0.65
    metadata = dict(fact.metadata)
    metadata.update(
        {
            "memory_layer": "facts",
            "v3_scope": fact.scope,
            "category": fact.category,
            "visibility": fact.visibility,
            "inject_policy": fact.inject_policy,
            "source_type": fact.source.type,
            "read_at": format_memory_v3_time(now),
        }
    )
    return _make_memory_record(
        memory_id=fact.id,
        scope=scope,
        owner_agent_id=None if fact.scope == "shared" else fact.owner_agent_id,
        session_id=fact.source.session_id,
        memory_type=_memory_type_for_category(fact.category),
        content=fact.content,
        tags=fact.tags + [fact.category],
        importance=importance,
        confidence=fact.confidence,
        kind=kind,
        source_kind=source_kind,
        canonical_key=fact.metadata.get("canonical_key"),
        normalized_value=fact.metadata.get("normalized_value"),
        subject_kind=fact.metadata.get("subject_kind", "user"),
        classification_version=fact.metadata.get("classification_version", _SCHEMA_VERSION),
        created_at=fact.created_at,
        updated_at=fact.updated_at,
        source_event_id=source_event_id,
        source_agent_id=fact.metadata.get("source_agent_id"),
        metadata=metadata,
    )


def _make_memory_record(
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
    classification_version: str = _SCHEMA_VERSION,
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


def _fact_scope_visible(*, record_scope: MemoryScope, include_scopes: list[MemoryScope]) -> bool:
    return record_scope in include_scopes


def _record_scope_for_fact(fact: MemoryV3Fact) -> MemoryScope:
    if fact.scope == "shared":
        return MemoryScope.SHARED_LONG
    memory_scope = fact.metadata.get("memory_scope", "").strip()
    if memory_scope == MemoryScope.AGENT_SHORT.value:
        return MemoryScope.AGENT_SHORT
    return MemoryScope.AGENT_LONG


def _rank_records(records: list[MemoryRecord], query: str) -> list[MemoryRecord]:
    return sorted(
        records,
        key=lambda record: (
            _match_score(content=record.content, tags=record.tags, query=query),
            _inject_policy_rank(record.metadata.get("inject_policy")),
            record.confidence,
            record.importance,
            record.updated_at,
        ),
        reverse=True,
    )


def _matches_query(*, content: str, tags: list[str], query: str) -> bool:
    if query.strip() == "*":
        return True
    return _match_score(content=content, tags=tags, query=query) > 0


def _match_score(*, content: str, tags: list[str], query: str) -> int:
    normalized_query = query.strip().casefold()
    if normalized_query == "*":
        return 1
    haystack = (content + " " + " ".join(tags)).casefold()
    terms = _query_terms(normalized_query)
    return sum(1 for term in terms if term and term in haystack)


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


def _dedupe_by_id(records: list[MemoryRecord]) -> list[MemoryRecord]:
    output: list[MemoryRecord] = []
    seen: set[str] = set()
    for record in records:
        if record.memory_id in seen:
            continue
        seen.add(record.memory_id)
        output.append(record)
    return output


def _to_v3_scope(*, scope: MemoryScope, owner_agent_id: str | None) -> tuple[str, str | None]:
    if scope == MemoryScope.SHARED_LONG:
        return "shared", None
    if scope in {MemoryScope.AGENT_LONG, MemoryScope.AGENT_SHORT}:
        return "agent", _require_non_empty("owner_agent_id", owner_agent_id or "")
    raise ValidationError(f"Unsupported memory scope: {scope.value}")


def _memory_type_for_category(category: str) -> MemoryType:
    normalized = category.strip().lower()
    if normalized == "preference":
        return MemoryType.PREFERENCE
    if normalized in {"correction", "constraint"}:
        return MemoryType.CONSTRAINT
    if normalized == "goal":
        return MemoryType.PLAN
    return MemoryType.FACT


def _kind_for_category(category: str) -> str:
    normalized = category.strip().lower()
    if normalized == "preference":
        return "user_preference"
    if normalized == "behavior":
        return "interaction_pattern"
    return "user_fact"


def _long_term_record_id(*, scope: str, agent_id: str | None, group: str, key: str) -> str:
    base = f"{scope}_{agent_id or 'shared'}_{group}_{key}"
    return "long_" + _stable_id(base)


def _mid_term_record_id(*, scope: str, agent_id: str | None, path: Path) -> str:
    base = f"{scope}_{agent_id or 'shared'}_{path.as_posix()}"
    return "mid_" + _stable_id(base)


def _stable_id(value: str) -> str:
    digest = sha256(value.encode("utf-8")).hexdigest()[:16]
    return digest


def _clip_text(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 24].rstrip() + "\n...[truncated]"


def _parse_optional_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return _normalize_datetime(parsed)


def _normalize_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationError("datetime value must be datetime.")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _normalize_limit(limit: int) -> int:
    if not isinstance(limit, int) or limit <= 0:
        raise ValidationError("limit must be positive integer.")
    return limit


def _normalize_memory_ids(memory_ids: list[str]) -> set[str]:
    if not isinstance(memory_ids, list) or not memory_ids:
        raise ValidationError("memory_ids must be non-empty list.")
    output: set[str] = set()
    for raw in memory_ids:
        if not isinstance(raw, str) or not raw.strip():
            raise ValidationError("memory_ids entries must be non-empty strings.")
        output.add(raw.strip())
    return output
