"""Memory read/write operations for runtime."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.models import MemoryItem
from app.domain.protocols import MemoryRepository

__all__ = ["MemoryManager"]
_logger = logging.getLogger(__name__)


class MemoryManager:
    """Expose minimal memory strategy for first release."""

    def __init__(self, memory_repository: MemoryRepository) -> None:
        self._memory_repository = memory_repository

    def write_memory(
        self,
        content: str,
        tags: list[str],
        session_id: str | None,
        source_event_id: str | None,
    ) -> MemoryItem:
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("content must be a non-empty string.")
        if not isinstance(tags, list):
            raise ValidationError("tags must be a list.")

        memory = MemoryItem(
            memory_id=f"mem_{uuid4().hex[:12]}",
            session_id=session_id.strip() if isinstance(session_id, str) and session_id.strip() else None,
            content=content.strip(),
            tags=[tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()],
            created_at=datetime.now(UTC),
            source_event_id=source_event_id.strip() if isinstance(source_event_id, str) and source_event_id.strip() else None,
        )
        self._memory_repository.add_memory(memory)
        _logger.debug("写入记忆成功: memory_id=%s session_id=%s tag_count=%s", memory.memory_id, memory.session_id, len(memory.tags))
        return memory

    def search(self, query: str, limit: int) -> list[MemoryItem]:
        if not isinstance(query, str) or not query.strip():
            raise ValidationError("query must be a non-empty string.")
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        result = self._memory_repository.search(query.strip(), limit)
        _logger.debug("检索记忆完成: query=%s limit=%s hit_count=%s", query.strip(), limit, len(result))
        return result

    def list_memories(self, limit: int) -> list[MemoryItem]:
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        result = self._memory_repository.list_memories(limit)
        _logger.debug("读取记忆列表完成: limit=%s count=%s", limit, len(result))
        return result
