"""JSONL file-backed memory store."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.errors import StorageError, ValidationError
from app.memory.models import (
    ForgetResult,
    MemoryCandidate,
    MemoryForgetRequest,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    make_content_hash,
)

__all__ = ["JsonlFileMemoryStore"]
_logger = logging.getLogger(__name__)


class JsonlFileMemoryStore:
    """Persist memory candidates and records in JSONL files."""

    def __init__(self, root_dir: Path) -> None:
        if not isinstance(root_dir, Path):
            raise ValidationError("root_dir must be pathlib.Path.")
        self._root_dir = root_dir
        self._shared_dir = self._root_dir / "shared"
        self._agents_dir = self._root_dir / "agents"
        self._candidates_dir = self._root_dir / "candidates"
        self._processed_dir = self._candidates_dir / "processed"
        self._ops_dir = self._root_dir / "ops"
        self._pending_file = self._candidates_dir / "pending.jsonl"

        self._shared_dir.mkdir(parents=True, exist_ok=True)
        self._agents_dir.mkdir(parents=True, exist_ok=True)
        self._candidates_dir.mkdir(parents=True, exist_ok=True)
        self._processed_dir.mkdir(parents=True, exist_ok=True)
        self._ops_dir.mkdir(parents=True, exist_ok=True)
        self._pending_file.touch(exist_ok=True)

    def add_candidate(self, candidate: MemoryCandidate) -> None:
        if not isinstance(candidate, MemoryCandidate):
            raise ValidationError("candidate must be MemoryCandidate.")
        existing_keys = self._load_pending_idempotency_keys()
        if candidate.idempotency_key in existing_keys:
            _logger.debug("memory 候选幂等命中，跳过写入: key=%s", candidate.idempotency_key)
            return
        payload = _candidate_to_payload(candidate)
        _append_jsonl_rows(self._pending_file, [payload])

    def list_pending_candidates(self, limit: int) -> list[MemoryCandidate]:
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        rows = _read_jsonl_rows(self._pending_file)
        output: list[MemoryCandidate] = []
        for row in rows:
            try:
                output.append(_payload_to_candidate(row))
            except ValidationError as exc:
                _logger.warning("memory candidate 记录不合法，已跳过: error=%s row=%s", exc, row)
            if len(output) >= limit:
                break
        return output

    def archive_pending_candidates(self, candidate_ids: list[str], processed_at: datetime) -> int:
        if not candidate_ids:
            return 0
        normalized_ids = {item.strip() for item in candidate_ids if isinstance(item, str) and item.strip()}
        if not normalized_ids:
            return 0

        rows = _read_jsonl_rows(self._pending_file)
        remaining: list[dict[str, Any]] = []
        selected: list[dict[str, Any]] = []
        for row in rows:
            candidate_id = str(row.get("candidate_id", "")).strip()
            if candidate_id and candidate_id in normalized_ids:
                with_processed = dict(row)
                with_processed["processed_at"] = _to_iso(processed_at.astimezone(UTC))
                selected.append(with_processed)
                continue
            remaining.append(row)

        _write_jsonl_rows(self._pending_file, remaining)
        if selected:
            processed_file = self._processed_dir / f"{processed_at.date().isoformat()}.jsonl"
            _append_jsonl_rows(processed_file, selected)
        return len(selected)

    def write_records(self, records: list[MemoryRecord]) -> None:
        if not isinstance(records, list):
            raise ValidationError("records must be a list.")
        grouped: dict[Path, list[dict[str, Any]]] = {}
        for record in records:
            if not isinstance(record, MemoryRecord):
                raise ValidationError("records item must be MemoryRecord.")
            target = self._record_file_for(record.scope, record.owner_agent_id, record.session_id)
            grouped.setdefault(target, []).append(_record_to_payload(record))
        for path, rows in grouped.items():
            _append_jsonl_rows(path, rows)

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
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValidationError("agent_id must be non-empty string.")
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        tokens = [token for token in query.lower().split() if token]
        candidates: list[tuple[int, MemoryRecord]] = []

        for path in self._iter_scope_files(scope=scope, agent_id=agent_id.strip(), session_id=session_id):
            rows = _read_jsonl_rows(path)
            for row in rows:
                try:
                    record = _payload_to_record(row)
                except ValidationError as exc:
                    _logger.warning("memory record 不合法，已跳过: path=%s error=%s row=%s", path, exc, row)
                    continue
                if record.status != MemoryStatus.ACTIVE:
                    continue
                if record.expires_at is not None and record.expires_at <= now:
                    continue
                score = _score_record(record=record, tokens=tokens)
                if tokens and score <= 0:
                    continue
                candidates.append((score, record))

        candidates.sort(
            key=lambda item: (item[0], item[1].confidence, item[1].importance, item[1].updated_at),
            reverse=True,
        )
        return [record for _, record in candidates[:limit]]

    def forget(self, request: MemoryForgetRequest, now: datetime) -> ForgetResult:
        touched = 0
        deleted = 0
        archived = 0
        target_ids = set(request.memory_ids)

        for scope in request.scopes:
            for path in self._iter_scope_files(scope=scope, agent_id=request.agent_id, session_id=request.session_id):
                rows = _read_jsonl_rows(path)
                if not rows:
                    continue
                changed = False
                output: list[dict[str, Any]] = []
                for row in rows:
                    try:
                        record = _payload_to_record(row)
                    except ValidationError:
                        output.append(row)
                        continue
                    if not _match_forget(record=record, request=request, target_ids=target_ids):
                        output.append(row)
                        continue
                    touched += 1
                    changed = True
                    if request.hard_delete:
                        deleted += 1
                        continue
                    metadata = dict(record.metadata)
                    if request.reason is not None:
                        metadata["forget_reason"] = request.reason
                    updated_record = MemoryRecord(
                        memory_id=record.memory_id,
                        scope=record.scope,
                        owner_agent_id=record.owner_agent_id,
                        session_id=record.session_id,
                        memory_type=record.memory_type,
                        content=record.content,
                        tags=record.tags,
                        importance=record.importance,
                        confidence=record.confidence,
                        status=MemoryStatus.DELETED,
                        created_at=record.created_at,
                        updated_at=now,
                        expires_at=record.expires_at,
                        source_event_id=record.source_event_id,
                        source_agent_id=record.source_agent_id,
                        version=record.version,
                        parent_memory_id=record.parent_memory_id,
                        content_hash=record.content_hash,
                        metadata=metadata,
                    )
                    output.append(_record_to_payload(updated_record))
                    archived += 1
                if changed:
                    _write_jsonl_rows(path, output)

        return ForgetResult(touched_records=touched, deleted_records=deleted, archived_records=archived)

    def _load_pending_idempotency_keys(self) -> set[str]:
        keys: set[str] = set()
        for row in _read_jsonl_rows(self._pending_file):
            raw = row.get("idempotency_key")
            if isinstance(raw, str) and raw.strip():
                keys.add(raw.strip())
        return keys

    def _iter_scope_files(self, scope: MemoryScope, agent_id: str | None, session_id: str | None) -> list[Path]:
        if scope == MemoryScope.SHARED_LONG:
            return [self._shared_dir / "long.jsonl"]
        if scope == MemoryScope.AGENT_LONG:
            if agent_id is not None:
                return [self._agents_dir / agent_id / "long.jsonl"]
            return sorted((self._agents_dir).glob("*/long.jsonl"))
        if agent_id is None:
            return sorted(self._agents_dir.glob("*/short/*.jsonl"))
        if scope == MemoryScope.AGENT_SHORT:
            if session_id is not None:
                return [self._agents_dir / agent_id / "short" / f"{session_id}.jsonl"]
            return sorted((self._agents_dir / agent_id / "short").glob("*.jsonl"))
        return []

    def _record_file_for(self, scope: MemoryScope, owner_agent_id: str | None, session_id: str | None) -> Path:
        if scope == MemoryScope.SHARED_LONG:
            return self._shared_dir / "long.jsonl"
        if owner_agent_id is None:
            raise ValidationError("owner_agent_id is required for agent scope records.")
        if scope == MemoryScope.AGENT_LONG:
            return self._agents_dir / owner_agent_id / "long.jsonl"
        if session_id is None:
            raise ValidationError("session_id is required for agent_short records.")
        return self._agents_dir / owner_agent_id / "short" / f"{session_id}.jsonl"


def _score_record(record: MemoryRecord, tokens: list[str]) -> int:
    if not tokens:
        return 1
    content = record.content.lower()
    tags = [tag.lower() for tag in record.tags]
    score = 0
    for token in tokens:
        if token in content:
            score += 2
        if any(token in tag for tag in tags):
            score += 1
    return score


def _match_forget(record: MemoryRecord, request: MemoryForgetRequest, target_ids: set[str]) -> bool:
    if record.status == MemoryStatus.DELETED:
        return False
    if target_ids and record.memory_id not in target_ids:
        return False
    if request.agent_id is not None and record.owner_agent_id != request.agent_id:
        return False
    if request.session_id is not None and record.session_id != request.session_id:
        return False
    if request.before is not None and record.updated_at >= request.before:
        return False
    return True


def _candidate_to_payload(candidate: MemoryCandidate) -> dict[str, Any]:
    return {
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


def _payload_to_candidate(payload: dict[str, Any]) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=str(payload["candidate_id"]),
        agent_id=str(payload["agent_id"]),
        session_id=None if payload.get("session_id") is None else str(payload["session_id"]),
        scope_hint=MemoryScope(str(payload["scope_hint"])),
        memory_type=MemoryType(str(payload["memory_type"])),
        content=str(payload["content"]),
        tags=[str(item) for item in payload.get("tags", [])],
        confidence=float(payload["confidence"]),
        source_event_id=None if payload.get("source_event_id") is None else str(payload["source_event_id"]),
        idempotency_key=str(payload["idempotency_key"]),
        created_at=_from_iso(str(payload["created_at"])),
        metadata={str(key): str(value) for key, value in dict(payload.get("metadata", {})).items()},
    )


def _record_to_payload(record: MemoryRecord) -> dict[str, Any]:
    return {
        "memory_id": record.memory_id,
        "scope": record.scope.value,
        "owner_agent_id": record.owner_agent_id,
        "session_id": record.session_id,
        "memory_type": record.memory_type.value,
        "content": record.content,
        "tags": record.tags,
        "importance": record.importance,
        "confidence": record.confidence,
        "status": record.status.value,
        "created_at": _to_iso(record.created_at),
        "updated_at": _to_iso(record.updated_at),
        "expires_at": None if record.expires_at is None else _to_iso(record.expires_at),
        "source_event_id": record.source_event_id,
        "source_agent_id": record.source_agent_id,
        "version": record.version,
        "parent_memory_id": record.parent_memory_id,
        "content_hash": record.content_hash or make_content_hash(record.content),
        "metadata": record.metadata,
    }


def _payload_to_record(payload: dict[str, Any]) -> MemoryRecord:
    return MemoryRecord(
        memory_id=str(payload["memory_id"]),
        scope=MemoryScope(str(payload["scope"])),
        owner_agent_id=None if payload.get("owner_agent_id") is None else str(payload["owner_agent_id"]),
        session_id=None if payload.get("session_id") is None else str(payload["session_id"]),
        memory_type=MemoryType(str(payload["memory_type"])),
        content=str(payload["content"]),
        tags=[str(item) for item in payload.get("tags", [])],
        importance=float(payload.get("importance", 0.5)),
        confidence=float(payload.get("confidence", 0.5)),
        status=MemoryStatus(str(payload.get("status", "active"))),
        created_at=_from_iso(str(payload["created_at"])),
        updated_at=_from_iso(str(payload["updated_at"])),
        expires_at=None if payload.get("expires_at") is None else _from_iso(str(payload["expires_at"])),
        source_event_id=None if payload.get("source_event_id") is None else str(payload["source_event_id"]),
        source_agent_id=None if payload.get("source_agent_id") is None else str(payload["source_agent_id"]),
        version=int(payload.get("version", 1)),
        parent_memory_id=None if payload.get("parent_memory_id") is None else str(payload["parent_memory_id"]),
        content_hash=str(payload.get("content_hash", "")),
        metadata={str(key): str(value) for key, value in dict(payload.get("metadata", {})).items()},
    )


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
    except OSError as exc:
        raise StorageError(f"Failed to read memory jsonl '{path}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise StorageError(f"Invalid JSONL format '{path}': {exc}") from exc
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
        raise StorageError(f"Failed to append memory jsonl '{path}': {exc}") from exc


def _write_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp_path.replace(path)
    except OSError as exc:
        raise StorageError(f"Failed to rewrite memory jsonl '{path}': {exc}") from exc


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _from_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(UTC)

