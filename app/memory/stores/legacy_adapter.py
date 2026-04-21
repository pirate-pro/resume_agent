"""Adapter that bridges new memory interfaces to legacy repository."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.errors import StorageError, ValidationError
from app.domain.models import MemoryItem
from app.domain.protocols import MemoryRepository
from app.memory.models import (
    ForgetResult,
    MemoryCandidate,
    MemoryForgetRequest,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)

__all__ = ["LegacyMemoryStoreAdapter"]


class LegacyMemoryStoreAdapter:
    """Best-effort adapter for phased migration from old memory repository."""

    def __init__(self, memory_repository: MemoryRepository, staging_dir: Path) -> None:
        if not isinstance(staging_dir, Path):
            raise ValidationError("staging_dir must be pathlib.Path.")
        self._memory_repository = memory_repository
        self._staging_dir = staging_dir
        self._pending_file = self._staging_dir / "legacy_pending_candidates.jsonl"
        self._processed_dir = self._staging_dir / "processed"
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        self._processed_dir.mkdir(parents=True, exist_ok=True)
        self._pending_file.touch(exist_ok=True)

    def add_candidate(self, candidate: MemoryCandidate) -> None:
        payload = {
            "candidate_id": candidate.candidate_id,
            "agent_id": candidate.agent_id,
            "session_id": candidate.session_id,
            "scope_hint": candidate.scope_hint.value,
            "memory_type": candidate.memory_type.value,
            "content": candidate.content,
            "tags": candidate.tags,
            "confidence": candidate.confidence,
            "source_event_id": candidate.source_event_id,
            "idempotency_key": candidate.idempotency_key,
            "created_at": _to_iso(candidate.created_at),
            "metadata": candidate.metadata,
        }
        _append_jsonl_rows(self._pending_file, [payload])

    def list_pending_candidates(self, limit: int) -> list[MemoryCandidate]:
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        output: list[MemoryCandidate] = []
        for row in _read_jsonl_rows(self._pending_file):
            output.append(
                MemoryCandidate(
                    candidate_id=str(row["candidate_id"]),
                    agent_id=str(row["agent_id"]),
                    session_id=None if row.get("session_id") is None else str(row["session_id"]),
                    scope_hint=MemoryScope(str(row["scope_hint"])),
                    memory_type=MemoryType(str(row["memory_type"])),
                    content=str(row["content"]),
                    tags=[str(item) for item in row.get("tags", [])],
                    confidence=float(row.get("confidence", 0.5)),
                    source_event_id=None if row.get("source_event_id") is None else str(row["source_event_id"]),
                    idempotency_key=str(row["idempotency_key"]),
                    created_at=_from_iso(str(row["created_at"])),
                    metadata={str(key): str(value) for key, value in dict(row.get("metadata", {})).items()},
                )
            )
            if len(output) >= limit:
                break
        return output

    def archive_pending_candidates(self, candidate_ids: list[str], processed_at: datetime) -> int:
        if not candidate_ids:
            return 0
        wanted = {item.strip() for item in candidate_ids if isinstance(item, str) and item.strip()}
        rows = _read_jsonl_rows(self._pending_file)
        selected: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []
        for row in rows:
            candidate_id = str(row.get("candidate_id", "")).strip()
            if candidate_id in wanted:
                enriched = dict(row)
                enriched["processed_at"] = _to_iso(processed_at.astimezone(UTC))
                selected.append(enriched)
            else:
                remaining.append(row)
        _write_jsonl_rows(self._pending_file, remaining)
        if selected:
            file_path = self._processed_dir / f"{processed_at.date().isoformat()}.jsonl"
            _append_jsonl_rows(file_path, selected)
        return len(selected)

    def write_records(self, records: list[MemoryRecord]) -> None:
        for record in records:
            if record.status != MemoryStatus.ACTIVE:
                continue
            item = MemoryItem(
                memory_id=record.memory_id,
                session_id=record.session_id,
                content=record.content,
                tags=record.tags,
                created_at=record.created_at,
                source_event_id=record.source_event_id,
            )
            self._memory_repository.add_memory(item)

    def search_records(
        self,
        *,
        scope: MemoryScope,
        agent_id: str,
        session_id: str | None,
        query: str,
        limit: int,
        now: datetime,
    ) -> list[MemoryRecord]:
        _ = (agent_id, now)
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        if scope == MemoryScope.AGENT_SHORT and session_id is None:
            return []
        if query.strip():
            items = self._memory_repository.search(query=query, limit=limit)
        else:
            items = self._memory_repository.list_memories(limit=limit)
        output: list[MemoryRecord] = []
        for item in items:
            mapped_scope = MemoryScope.SHARED_LONG
            if item.session_id is not None:
                mapped_scope = MemoryScope.AGENT_SHORT
            if mapped_scope != scope:
                continue
            output.append(
                MemoryRecord(
                    memory_id=item.memory_id,
                    scope=mapped_scope,
                    owner_agent_id=None,
                    session_id=item.session_id,
                    memory_type=MemoryType.FACT,
                    content=item.content,
                    tags=item.tags,
                    importance=0.5,
                    confidence=0.5,
                    status=MemoryStatus.ACTIVE,
                    created_at=item.created_at,
                    updated_at=item.created_at,
                    expires_at=None,
                    source_event_id=item.source_event_id,
                    source_agent_id=None,
                    version=1,
                    parent_memory_id=None,
                    content_hash="",
                    metadata={},
                )
            )
            if len(output) >= limit:
                break
        return output

    def forget(self, request: MemoryForgetRequest, now: datetime) -> ForgetResult:
        _ = (request, now)
        # 旧存储层没有删除接口，这里返回零并让上层继续工作，不阻塞链路。
        return ForgetResult(touched_records=0, deleted_records=0, archived_records=0)


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                stripped = raw.strip()
                if not stripped:
                    continue
                loaded = json.loads(stripped)
                if isinstance(loaded, dict):
                    rows.append(loaded)
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageError(f"Failed to read legacy candidate file '{path}': {exc}") from exc
    return rows


def _append_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise StorageError(f"Failed to append legacy candidate file '{path}': {exc}") from exc


def _write_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp_path = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp_path.replace(path)
    except OSError as exc:
        raise StorageError(f"Failed to rewrite legacy candidate file '{path}': {exc}") from exc


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _from_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(UTC)

