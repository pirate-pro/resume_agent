"""JSONL-backed memory repository."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.core.errors import StorageError, ValidationError
from app.domain.models import MemoryItem

__all__ = ["JsonlMemoryRepository"]
_logger = logging.getLogger(__name__)


class JsonlMemoryRepository:
    """Persist memory items in a single JSONL file."""

    def __init__(self, data_dir: Path) -> None:
        if not isinstance(data_dir, Path):
            raise ValidationError("data_dir must be a pathlib.Path.")
        self._data_dir = data_dir
        self._memory_dir = self._data_dir / "memory"
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._memory_file = self._memory_dir / "memories.jsonl"
        self._memory_file.touch(exist_ok=True)

    def add_memory(self, item: MemoryItem) -> None:
        if not isinstance(item, MemoryItem):
            raise ValidationError("item must be a MemoryItem.")
        payload = {
            "memory_id": item.memory_id,
            "session_id": item.session_id,
            "content": item.content,
            "tags": item.tags,
            "created_at": _to_iso(item.created_at),
            "source_event_id": item.source_event_id,
        }
        try:
            with self._memory_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError as exc:
            raise StorageError(f"Failed to write memory: {exc}") from exc
        _logger.debug("memory 已写入: memory_id=%s session_id=%s", item.memory_id, item.session_id)

    def search(self, query: str, limit: int) -> list[MemoryItem]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValidationError("query must be a non-empty string.")
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        items = self._read_all_items()
        tokens = [token for token in normalized_query.lower().split() if token]

        scored: list[tuple[int, MemoryItem]] = []
        for item in items:
            content = item.content.lower()
            tags = [tag.lower() for tag in item.tags]
            score = 0
            for token in tokens:
                if token in content:
                    score += 2
                if any(token in tag for tag in tags):
                    score += 1
            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        result = [item for _, item in scored[:limit]]
        _logger.debug("memory 检索完成: query=%s limit=%s hit_count=%s", normalized_query, limit, len(result))
        return result

    def list_memories(self, limit: int) -> list[MemoryItem]:
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        items = self._read_all_items()
        items.sort(key=lambda item: item.created_at, reverse=True)
        result = items[:limit]
        _logger.debug("memory 列表读取完成: limit=%s count=%s", limit, len(result))
        return result

    def _read_all_items(self) -> list[MemoryItem]:
        items: list[MemoryItem] = []
        try:
            with self._memory_file.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    row = json.loads(stripped)
                    items.append(
                        MemoryItem(
                            memory_id=str(row["memory_id"]),
                            session_id=None if row["session_id"] is None else str(row["session_id"]),
                            content=str(row["content"]),
                            tags=list(row["tags"]),
                            created_at=_from_iso(str(row["created_at"])),
                            source_event_id=None
                            if row["source_event_id"] is None
                            else str(row["source_event_id"]),
                        )
                    )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
            raise StorageError(f"Failed to read memory file: {exc}") from exc
        return items



def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")



def _from_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(UTC)
