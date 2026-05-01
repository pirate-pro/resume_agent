"""File-backed memory store.

The memory layout keeps durable memory human-readable and agent-isolated:

data/memory/
  shared/{long_term.json,facts.jsonl,pending_promotions.jsonl,mid_term/...}
  agents/<agent_id>/{long_term_overlay.json,facts.jsonl,mid_term/...}
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from app.core.errors import StorageError, ValidationError
from app.memory.file_models import MemoryFact, format_memory_time
from app.memory.file_store_facts import (
    append_fact_to_file,
    archive_active_facts_by_canonical_key_in_file,
    find_active_fact_by_canonical_key_in_file,
    find_active_fact_by_content_in_file,
    forget_facts_in_files,
    has_active_fact_with_metadata_in_file,
    has_archived_fact_by_content_in_file,
    list_active_long_term_facts,
)
from app.memory.file_store_layout import MemoryFileLayout
from app.memory.file_store_common import (
    LONG_TERM_SECTIONS,
    MID_TERM_DAILY_LIMIT,
    MID_TERM_MAX_CHARS,
    clip_text,
    long_term_record_id,
    mid_term_record_id,
    normalize_datetime,
    normalize_limit,
    normalize_memory_ids,
    parse_optional_time,
    require_non_empty,
    set_long_term_section,
    to_memory_scope,
)
from app.memory.file_store_io import (
    read_json_payload,
    read_jsonl_payloads,
    write_json_payload,
)
from app.memory.file_store_records import (
    dedupe_by_id,
    fact_scope_visible,
    fact_to_record,
    make_memory_record,
    matches_query,
    rank_records,
    record_scope_for_fact,
)
from app.memory.file_store_summary import build_long_term_summaries_from_facts
from app.memory.models import (
    ForgetResult,
    MemoryReadBundle,
    MemoryRecord,
    MemoryScope,
    MemoryType,
)

__all__ = ["FileMemoryStore"]

_logger = logging.getLogger(__name__)


class FileMemoryStore:
    """Read and write memory files without a derived database index."""

    def __init__(self, root_dir: Path) -> None:
        if not isinstance(root_dir, Path):
            raise ValidationError("root_dir must be pathlib.Path.")
        self._root_dir = root_dir
        self._layout = MemoryFileLayout(root_dir)
        self._layout.ensure_shared_layout()

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
    ) -> MemoryFact:
        normalized_now = normalize_datetime(now or datetime.now(UTC))
        normalized_scope, normalized_owner = to_memory_scope(scope=scope, owner_agent_id=owner_agent_id)
        path = self._layout.facts_path(scope=normalized_scope, agent_id=normalized_owner)
        return append_fact_to_file(
            path=path,
            content=content,
            category=category,
            confidence=confidence,
            normalized_scope=normalized_scope,
            normalized_owner=normalized_owner,
            session_id=session_id,
            source_event_id=source_event_id,
            source_type=source_type,
            tags=tags,
            inject_policy=inject_policy,
            metadata=metadata,
            now=normalized_now,
        )

    def refresh_long_term_summary_from_facts(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        now: datetime | None = None,
    ) -> dict[str, str]:
        if scope not in {MemoryScope.SHARED_LONG, MemoryScope.AGENT_LONG}:
            raise ValidationError("long-term summary refresh only supports shared_long/agent_long.")
        normalized_now = normalize_datetime(now or datetime.now(UTC))
        normalized_scope, normalized_owner = to_memory_scope(scope=scope, owner_agent_id=agent_id)
        long_term_path = self._layout.long_term_path(scope=normalized_scope, agent_id=normalized_owner)
        facts_path = self._layout.facts_path(scope=normalized_scope, agent_id=normalized_owner)
        payload = read_json_payload(long_term_path)
        facts = list_active_long_term_facts(
            path=facts_path,
            scope=normalized_scope,
            owner_agent_id=normalized_owner,
        )
        summaries = build_long_term_summaries_from_facts(facts)
        refreshed_at = format_memory_time(normalized_now)
        set_long_term_section(payload, group="user", key="workContext", summary=summaries["user.workContext"], refreshed_at=refreshed_at)
        set_long_term_section(
            payload,
            group="user",
            key="personalContext",
            summary=summaries["user.personalContext"],
            refreshed_at=refreshed_at,
        )
        set_long_term_section(payload, group="user", key="topOfMind", summary=summaries["user.topOfMind"], refreshed_at=refreshed_at)
        set_long_term_section(
            payload,
            group="history",
            key="recentMonths",
            summary=summaries["history.recentMonths"],
            refreshed_at=refreshed_at,
        )
        set_long_term_section(
            payload,
            group="history",
            key="earlierContext",
            summary=summaries["history.earlierContext"],
            refreshed_at=refreshed_at,
        )
        set_long_term_section(
            payload,
            group="history",
            key="longTermBackground",
            summary=summaries["history.longTermBackground"],
            refreshed_at=refreshed_at,
        )
        payload["lastUpdated"] = refreshed_at
        write_json_payload(long_term_path, payload)
        return summaries

    def has_active_fact_with_metadata(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        metadata_key: str,
        metadata_value: str,
    ) -> bool:
        normalized_key = require_non_empty("metadata_key", metadata_key)
        normalized_value = require_non_empty("metadata_value", metadata_value)
        normalized_scope, normalized_owner = to_memory_scope(scope=scope, owner_agent_id=agent_id)
        path = self._layout.facts_path(scope=normalized_scope, agent_id=normalized_owner)
        return has_active_fact_with_metadata_in_file(
            path=path,
            normalized_scope=normalized_scope,
            normalized_owner=normalized_owner,
            metadata_key=normalized_key,
            metadata_value=normalized_value,
        )

    def find_active_fact_by_content(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        content: str,
    ) -> MemoryFact | None:
        normalized_content = require_non_empty("content", content)
        normalized_scope, normalized_owner = to_memory_scope(scope=scope, owner_agent_id=agent_id)
        path = self._layout.facts_path(scope=normalized_scope, agent_id=normalized_owner)
        return find_active_fact_by_content_in_file(
            path=path,
            normalized_scope=normalized_scope,
            normalized_owner=normalized_owner,
            content=normalized_content,
        )

    def find_active_fact_by_canonical_key(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        canonical_key: str,
    ) -> MemoryFact | None:
        normalized_key = require_non_empty("canonical_key", canonical_key)
        normalized_scope, normalized_owner = to_memory_scope(scope=scope, owner_agent_id=agent_id)
        path = self._layout.facts_path(scope=normalized_scope, agent_id=normalized_owner)
        return find_active_fact_by_canonical_key_in_file(
            path=path,
            normalized_scope=normalized_scope,
            normalized_owner=normalized_owner,
            canonical_key=normalized_key,
        )

    def has_archived_fact_by_content(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        content: str,
    ) -> bool:
        normalized_content = require_non_empty("content", content)
        normalized_scope, normalized_owner = to_memory_scope(scope=scope, owner_agent_id=agent_id)
        path = self._layout.facts_path(scope=normalized_scope, agent_id=normalized_owner)
        return has_archived_fact_by_content_in_file(
            path=path,
            normalized_scope=normalized_scope,
            normalized_owner=normalized_owner,
            content=normalized_content,
        )

    def archive_active_facts_by_canonical_key(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        canonical_key: str,
        reason: str,
        now: datetime | None = None,
    ) -> ForgetResult:
        normalized_key = require_non_empty("canonical_key", canonical_key)
        normalized_reason = require_non_empty("reason", reason)
        normalized_now = normalize_datetime(now or datetime.now(UTC))
        normalized_scope, normalized_owner = to_memory_scope(scope=scope, owner_agent_id=agent_id)
        path = self._layout.facts_path(scope=normalized_scope, agent_id=normalized_owner)
        return archive_active_facts_by_canonical_key_in_file(
            path=path,
            normalized_scope=normalized_scope,
            normalized_owner=normalized_owner,
            canonical_key=normalized_key,
            reason=normalized_reason,
            now=normalized_now,
        )

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
        normalized_agent_id = require_non_empty("agent_id", agent_id)
        normalized_query = require_non_empty("query", query)
        normalized_limit = normalize_limit(limit)
        normalized_now = normalize_datetime(now or datetime.now(UTC))
        include_shared = MemoryScope.SHARED_LONG in include_scopes
        include_agent = MemoryScope.AGENT_LONG in include_scopes or MemoryScope.AGENT_SHORT in include_scopes
        if include_agent:
            self._layout.ensure_agent_layout(normalized_agent_id)

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
        except (OSError, StorageError, ValidationError) as exc:
            _logger.exception(
                "memory read failed: agent_id=%s query=%s error=%s",
                normalized_agent_id,
                normalized_query,
                exc,
            )
            notes.append(f"memory read_failed: {exc}")

        ranked = rank_records(dedupe_by_id(collected), normalized_query)
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
        normalized_agent_id = require_non_empty("agent_id", agent_id)
        normalized_ids = normalize_memory_ids(memory_ids)
        normalized_now = normalize_datetime(now or datetime.now(UTC))
        include_shared = MemoryScope.SHARED_LONG in scopes
        include_agent = MemoryScope.AGENT_LONG in scopes or MemoryScope.AGENT_SHORT in scopes

        paths: list[Path] = []
        if include_shared:
            paths.append(self._layout.facts_path(scope="shared", agent_id=None))
        if include_agent:
            self._layout.ensure_agent_layout(normalized_agent_id)
            paths.append(self._layout.facts_path(scope="agent", agent_id=normalized_agent_id))

        return forget_facts_in_files(
            paths=paths,
            memory_ids=normalized_ids,
            hard_delete=hard_delete,
            reason=reason,
            now=normalized_now,
        )

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
        path = self._layout.long_term_path(scope=scope, agent_id=agent_id)
        payload = read_json_payload(path)
        output: list[MemoryRecord] = []
        for group, key, label in LONG_TERM_SECTIONS:
            raw_section = payload.get(group, {}).get(key, {})
            if not isinstance(raw_section, dict):
                continue
            summary = str(raw_section.get("summary", "")).strip()
            if not summary:
                continue
            content = f"{label}: {summary}"
            if not matches_query(content=content, tags=["long_term", group, key], query=query):
                continue
            updated_at = parse_optional_time(raw_section.get("updatedAt")) or now
            record_id = long_term_record_id(scope=scope, agent_id=agent_id, group=group, key=key)
            output.append(
                make_memory_record(
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
                        "storage_scope": scope,
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
        path = self._layout.facts_path(scope=scope, agent_id=agent_id)
        for row in read_jsonl_payloads(path):
            try:
                fact = MemoryFact.from_payload(row)
            except ValidationError as exc:
                _logger.warning("invalid memory fact skipped: path=%s error=%s row=%s", path, exc, row)
                continue
            if fact.status != "active":
                continue
            if standing_only and fact.inject_policy != "always":
                continue
            if fact.scope != scope:
                continue
            if scope == "agent" and fact.owner_agent_id != agent_id:
                continue
            record_scope = record_scope_for_fact(fact)
            if not fact_scope_visible(record_scope=record_scope, include_scopes=include_scopes):
                continue
            if record_scope == MemoryScope.AGENT_SHORT and short_session_id and fact.source.session_id != short_session_id:
                continue
            if not matches_query(content=fact.content, tags=fact.tags + [fact.category], query=query):
                continue
            output.append(fact_to_record(fact=fact, now=now))
        return output

    def _read_mid_term_records(
        self,
        *,
        scope: str,
        agent_id: str | None,
        query: str,
        now: datetime,
    ) -> list[MemoryRecord]:
        base_dir = self._layout.mid_term_dir(scope=scope, agent_id=agent_id)
        candidates = [base_dir / "rolling.md"]
        daily_dir = base_dir / "daily"
        if daily_dir.exists():
            candidates.extend(sorted(daily_dir.glob("*.md"), reverse=True)[:MID_TERM_DAILY_LIMIT])

        output: list[MemoryRecord] = []
        for path in candidates:
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise StorageError(f"Failed to read memory mid_term file '{path}': {exc}") from exc
            if not content:
                continue
            if content.strip() == "# Rolling Context":
                continue
            tags = ["mid_term", "rolling" if path.name == "rolling.md" else "daily"]
            if not matches_query(content=content, tags=tags, query=query):
                continue
            clipped = clip_text(content, max_chars=MID_TERM_MAX_CHARS)
            stat = path.stat()
            updated_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            memory_id = mid_term_record_id(scope=scope, agent_id=agent_id, path=path)
            output.append(
                make_memory_record(
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
                        "storage_scope": scope,
                        "path": str(path.relative_to(self._root_dir)),
                        "inject_policy": "retrieval",
                    },
                )
            )
        return output
