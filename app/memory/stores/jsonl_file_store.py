"""JSONL file-backed memory store."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from app.core.errors import StorageError, ValidationError
from app.memory.models import (
    CompactResult,
    ForgetResult,
    MemoryCandidate,
    MemoryCompactRequest,
    MemoryForgetRequest,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    make_content_hash,
)

__all__ = ["JsonlFileMemoryStore"]
_logger = logging.getLogger(__name__)

_NAME_INTENT_TRIGGERS = (
    "你叫什么名字",
    "叫什么名字",
    "你的名字",
    "叫你什么",
    "怎么称呼",
    "称呼",
    "名字",
)
_NAME_INTENT_EXPANSIONS = ("名字", "称呼", "叫我", "叫你", "名称")
_CHAR_STOPWORDS = {"的", "了", "呢", "吗", "啊", "呀", "是", "在", "和", "与", "及", "你", "我", "他", "她", "它"}


@dataclass(slots=True)
class _QueryPlan:
    normalized_query: str
    strict_tokens: list[str]
    fallback_tokens: list[str]
    wildcard: bool


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
        query_plan = _build_query_plan(query)
        _logger.debug(
            "memory 检索预处理: query=%s normalized=%s strict_tokens=%s fallback_tokens=%s wildcard=%s",
            query,
            query_plan.normalized_query,
            len(query_plan.strict_tokens),
            len(query_plan.fallback_tokens),
            query_plan.wildcard,
        )
        strict_candidates: list[tuple[int, MemoryRecord]] = []
        fallback_candidates: list[tuple[int, MemoryRecord]] = []

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
                if query_plan.wildcard:
                    strict_candidates.append((1, record))
                    continue

                strict_score = _score_record(
                    record=record,
                    tokens=query_plan.strict_tokens,
                    normalized_query=query_plan.normalized_query,
                )
                if strict_score > 0:
                    strict_candidates.append((strict_score, record))
                    continue

                # 两阶段召回：严格阶段未命中时，再尝试更宽松的中文短词兜底召回。
                fallback_score = _score_record(
                    record=record,
                    tokens=query_plan.fallback_tokens,
                    normalized_query="",
                )
                if fallback_score > 0:
                    fallback_candidates.append((fallback_score, record))

        candidates = strict_candidates if strict_candidates else fallback_candidates
        if not strict_candidates and fallback_candidates:
            _logger.debug(
                "memory 检索使用兜底召回: query=%s fallback_hit_count=%s",
                query_plan.normalized_query,
                len(fallback_candidates),
            )

        candidates.sort(
            key=lambda item: (item[0], item[1].confidence, item[1].importance, item[1].updated_at),
            reverse=True,
        )
        return [record for _, record in candidates[:limit]]

    def count_active_records_by_hash(
        self,
        *,
        scope: MemoryScope,
        agent_id: str | None,
        session_id: str | None,
        content_hash: str,
        now: datetime,
    ) -> int:
        normalized_hash = str(content_hash).strip()
        if not normalized_hash:
            raise ValidationError("content_hash must be non-empty string.")
        count = 0
        for path in self._iter_scope_files(scope=scope, agent_id=agent_id, session_id=session_id):
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
                if record.content_hash != normalized_hash:
                    continue
                count += 1
        return count

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

    def compact(self, request: MemoryCompactRequest, now: datetime) -> CompactResult:
        if not isinstance(request, MemoryCompactRequest):
            raise ValidationError("request must be MemoryCompactRequest.")
        unique_paths = _dedupe_paths(self._collect_compact_paths(request))

        scanned_files = 0
        rewritten_files = 0
        scanned_rows = 0
        kept_rows = 0
        dropped_deleted = 0
        dropped_expired = 0
        dropped_superseded = 0
        dropped_duplicate_hash = 0
        invalid_rows = 0
        index_files_written = 0

        for path in unique_paths:
            rows = _read_jsonl_rows(path)
            if not rows:
                continue
            scanned_files += 1
            scanned_rows += len(rows)

            compacted = _compact_rows(rows=rows, request=request, now=now)
            kept_rows += compacted.kept_rows
            dropped_deleted += compacted.dropped_deleted
            dropped_expired += compacted.dropped_expired
            dropped_superseded += compacted.dropped_superseded
            dropped_duplicate_hash += compacted.dropped_duplicate_hash
            invalid_rows += compacted.invalid_rows

            if _rows_changed(original_rows=rows, compacted_rows=compacted.rows):
                _write_jsonl_rows(path, compacted.rows)
                rewritten_files += 1
            if request.write_index:
                self._write_index_file(path=path, records=compacted.records, invalid_rows=compacted.invalid_rows, now=now)
                index_files_written += 1

        result = CompactResult(
            scanned_files=scanned_files,
            rewritten_files=rewritten_files,
            scanned_rows=scanned_rows,
            kept_rows=kept_rows,
            dropped_deleted=dropped_deleted,
            dropped_expired=dropped_expired,
            dropped_superseded=dropped_superseded,
            dropped_duplicate_hash=dropped_duplicate_hash,
            invalid_rows=invalid_rows,
            index_files_written=index_files_written,
        )
        self._append_compact_log(request=request, result=result, now=now)
        return result

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

    def _collect_compact_paths(self, request: MemoryCompactRequest) -> list[Path]:
        paths: list[Path] = []
        for scope in request.scopes:
            paths.extend(self._iter_scope_files(scope=scope, agent_id=request.agent_id, session_id=request.session_id))
        return paths

    def _write_index_file(
        self,
        *,
        path: Path,
        records: list[MemoryRecord],
        invalid_rows: int,
        now: datetime,
    ) -> None:
        index_path = self._resolve_index_file_path(path)
        tag_counter = Counter[str]()
        active_count = 0
        deleted_count = 0
        expired_count = 0
        for record in records:
            tag_counter.update(record.tags)
            if record.status == MemoryStatus.ACTIVE:
                active_count += 1
            if record.status == MemoryStatus.DELETED:
                deleted_count += 1
            if record.expires_at is not None and record.expires_at <= now:
                expired_count += 1
        payload = {
            "schema": "memory_index_v1",
            "source_file": str(path.relative_to(self._root_dir)),
            "record_count": len(records),
            "active_count": active_count,
            "deleted_count": deleted_count,
            "expired_count": expired_count,
            "invalid_rows": invalid_rows,
            "top_tags": [{"tag": item[0], "count": item[1]} for item in tag_counter.most_common(20)],
            "updated_at": _to_iso(now),
        }
        _write_json_file(index_path, payload)

    def _resolve_index_file_path(self, record_file_path: Path) -> Path:
        if record_file_path == self._shared_dir / "long.jsonl":
            return self._shared_dir / "index.json"
        try:
            relative = record_file_path.relative_to(self._agents_dir)
        except ValueError:
            return record_file_path.with_suffix(".index.json")
        parts = relative.parts
        if len(parts) == 2 and parts[1] == "long.jsonl":
            return self._agents_dir / parts[0] / "long.index.json"
        if len(parts) >= 3 and parts[1] == "short":
            stem = Path(parts[-1]).stem
            return record_file_path.with_name(f"{stem}.index.json")
        return record_file_path.with_suffix(".index.json")

    def _append_compact_log(self, *, request: MemoryCompactRequest, result: CompactResult, now: datetime) -> None:
        payload = {
            "operation": "compact",
            "timestamp": _to_iso(now),
            "request": {
                "scopes": [scope.value for scope in request.scopes],
                "agent_id": request.agent_id,
                "session_id": request.session_id,
                "remove_deleted": request.remove_deleted,
                "remove_expired": request.remove_expired,
                "dedupe_by_memory_id": request.dedupe_by_memory_id,
                "dedupe_by_content_hash": request.dedupe_by_content_hash,
                "write_index": request.write_index,
            },
            "result": {
                "scanned_files": result.scanned_files,
                "rewritten_files": result.rewritten_files,
                "scanned_rows": result.scanned_rows,
                "kept_rows": result.kept_rows,
                "dropped_deleted": result.dropped_deleted,
                "dropped_expired": result.dropped_expired,
                "dropped_superseded": result.dropped_superseded,
                "dropped_duplicate_hash": result.dropped_duplicate_hash,
                "invalid_rows": result.invalid_rows,
                "index_files_written": result.index_files_written,
            },
        }
        _append_jsonl_rows(self._ops_dir / "compact.log.jsonl", [payload])


def _score_record(record: MemoryRecord, tokens: list[str], normalized_query: str) -> int:
    if not tokens and not normalized_query:
        return 0
    content = record.content.lower()
    tags = [tag.lower() for tag in record.tags]
    score = 0

    # 完整查询串命中优先级最高，提升“明确提问词”的召回稳定性。
    if normalized_query and normalized_query in content:
        score += 8
    if normalized_query and any(normalized_query in tag for tag in tags):
        score += 4

    for token in tokens:
        weight = _token_weight(token)
        if token in content:
            score += weight
        if any(token in tag for tag in tags):
            score += max(1, weight // 2)
    return score


def _build_query_plan(query: str) -> _QueryPlan:
    raw_query = query.strip().lower()
    if raw_query in {"*", "__all__"}:
        return _QueryPlan(
            normalized_query=raw_query,
            strict_tokens=[],
            fallback_tokens=[],
            wildcard=True,
        )

    normalized_query = _normalize_query_text(query)
    if normalized_query in {"*", "__all__"}:
        return _QueryPlan(
            normalized_query=normalized_query,
            strict_tokens=[],
            fallback_tokens=[],
            wildcard=True,
        )

    strict_tokens = _build_strict_tokens(normalized_query)
    fallback_tokens = _build_fallback_tokens(normalized_query, strict_tokens)
    return _QueryPlan(
        normalized_query=normalized_query,
        strict_tokens=strict_tokens,
        fallback_tokens=fallback_tokens,
        wildcard=False,
    )


def _normalize_query_text(query: str) -> str:
    lowered = query.strip().lower()
    if not lowered:
        return ""
    # 将符号统一替换为空格，保证中英文查询都能稳定分词。
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", lowered)
    return " ".join(token for token in normalized.split() if token)


def _build_strict_tokens(normalized_query: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()

    def add_token(value: str) -> None:
        candidate = value.strip()
        if not candidate:
            return
        if candidate in seen:
            return
        seen.add(candidate)
        tokens.append(candidate)

    for token in normalized_query.split():
        add_token(token)
        # 中文片段补齐 2-3 gram，解决“你叫什么名字”这类整句无法命中的问题。
        for gram in _cjk_ngrams(token, min_n=2, max_n=3):
            add_token(gram)

    compact_query = normalized_query.replace(" ", "")
    if compact_query:
        for gram in _cjk_ngrams(compact_query, min_n=2, max_n=3):
            add_token(gram)

    if any(trigger in compact_query for trigger in _NAME_INTENT_TRIGGERS):
        for item in _NAME_INTENT_EXPANSIONS:
            add_token(item)

    return tokens[:80]


def _build_fallback_tokens(normalized_query: str, strict_tokens: list[str]) -> list[str]:
    strict_set = set(strict_tokens)
    compact_query = normalized_query.replace(" ", "")
    dedup: list[str] = []
    seen: set[str] = set()
    for char in compact_query:
        if char in _CHAR_STOPWORDS:
            continue
        if char in strict_set:
            continue
        if char in seen:
            continue
        seen.add(char)
        dedup.append(char)
    return dedup[:40]


def _cjk_ngrams(text: str, min_n: int, max_n: int) -> list[str]:
    chars = [char for char in text if _is_cjk(char)]
    if not chars:
        return []
    grams: list[str] = []
    for n in range(min_n, max_n + 1):
        if len(chars) < n:
            continue
        for idx in range(0, len(chars) - n + 1):
            grams.append("".join(chars[idx : idx + n]))
    return grams


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def _token_weight(token: str) -> int:
    length = len(token)
    if length >= 4:
        return 4
    if length == 3:
        return 3
    if length == 2:
        return 2
    return 1


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


@dataclass(slots=True)
class _CompactionRows:
    rows: list[dict[str, Any]]
    records: list[MemoryRecord]
    kept_rows: int
    dropped_deleted: int
    dropped_expired: int
    dropped_superseded: int
    dropped_duplicate_hash: int
    invalid_rows: int


def _compact_rows(rows: list[dict[str, Any]], request: MemoryCompactRequest, now: datetime) -> _CompactionRows:
    valid_records: list[MemoryRecord] = []
    invalid_rows: list[dict[str, Any]] = []
    for row in rows:
        try:
            valid_records.append(_payload_to_record(row))
        except ValidationError as exc:
            _logger.warning("compact 遇到非法记录，已保留原始行: error=%s row=%s", exc, row)
            invalid_rows.append(row)

    dropped_deleted = 0
    dropped_expired = 0
    filtered: list[MemoryRecord] = []
    for record in valid_records:
        if request.remove_deleted and record.status == MemoryStatus.DELETED:
            dropped_deleted += 1
            continue
        if request.remove_expired and record.expires_at is not None and record.expires_at <= now:
            dropped_expired += 1
            continue
        filtered.append(record)

    dropped_superseded = 0
    if request.dedupe_by_memory_id:
        filtered, dropped_superseded = _dedupe_records(
            records=filtered,
            key_fn=lambda item: item.memory_id,
        )

    dropped_duplicate_hash = 0
    if request.dedupe_by_content_hash:
        filtered, dropped_duplicate_hash = _dedupe_records(
            records=filtered,
            key_fn=lambda item: f"{item.scope.value}|{item.owner_agent_id or '-'}|{item.session_id or '-'}|{item.content_hash}",
        )

    # 保持文件内容稳定可预期，按更新时间与 memory_id 排序写回。
    filtered.sort(key=lambda item: (item.updated_at, item.created_at, item.memory_id))
    compacted_rows = [_record_to_payload(item) for item in filtered]
    compacted_rows.extend(invalid_rows)
    return _CompactionRows(
        rows=compacted_rows,
        records=filtered,
        kept_rows=len(filtered),
        dropped_deleted=dropped_deleted,
        dropped_expired=dropped_expired,
        dropped_superseded=dropped_superseded,
        dropped_duplicate_hash=dropped_duplicate_hash,
        invalid_rows=len(invalid_rows),
    )


def _dedupe_records(
    *,
    records: list[MemoryRecord],
    key_fn: Callable[[MemoryRecord], str],
) -> tuple[list[MemoryRecord], int]:
    kept: dict[str, MemoryRecord] = {}
    dropped = 0
    for record in records:
        key = str(key_fn(record))
        existing = kept.get(key)
        if existing is None:
            kept[key] = record
            continue
        dropped += 1
        if _is_newer_record(record, existing):
            kept[key] = record
    return list(kept.values()), dropped


def _is_newer_record(current: MemoryRecord, existing: MemoryRecord) -> bool:
    return (
        current.updated_at,
        current.version,
        current.created_at,
        current.memory_id,
    ) > (
        existing.updated_at,
        existing.version,
        existing.created_at,
        existing.memory_id,
    )


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    output: list[Path] = []
    seen: set[Path] = set()
    for path in sorted(paths):
        if path in seen:
            continue
        seen.add(path)
        output.append(path)
    return output


def _rows_changed(*, original_rows: list[dict[str, Any]], compacted_rows: list[dict[str, Any]]) -> bool:
    if len(original_rows) != len(compacted_rows):
        return True
    for left, right in zip(original_rows, compacted_rows, strict=False):
        left_json = json.dumps(left, ensure_ascii=False, sort_keys=True)
        right_json = json.dumps(right, ensure_ascii=False, sort_keys=True)
        if left_json != right_json:
            return True
    return False


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


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        tmp_path.replace(path)
    except OSError as exc:
        raise StorageError(f"Failed to write memory json file '{path}': {exc}") from exc


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _from_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(UTC)
