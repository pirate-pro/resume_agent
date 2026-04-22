"""Memory read/write operations for runtime."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.core.errors import ValidationError
from app.memory.contracts import MemoryFacade
from app.memory.intake import build_candidate_request
from app.memory.models import MemoryConsolidateRequest, MemoryReadRequest
from app.domain.models import MemoryItem

__all__ = ["MemoryManager"]
_logger = logging.getLogger(__name__)


class MemoryManager:
    """Expose minimal memory strategy for first release."""

    def __init__(
        self,
        memory_facade: MemoryFacade,
        default_agent_id: str = "agent_main",
    ) -> None:
        self._memory_facade = memory_facade
        self._default_agent_id = default_agent_id.strip() if default_agent_id.strip() else "agent_main"

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

        normalized_session_id = session_id.strip() if isinstance(session_id, str) and session_id.strip() else None
        normalized_source_event = (
            source_event_id.strip() if isinstance(source_event_id, str) and source_event_id.strip() else None
        )
        normalized_content = content.strip()
        normalized_tags = [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]
        request = build_candidate_request(
            agent_id=self._default_agent_id,
            session_id=normalized_session_id,
            content=normalized_content,
            tags=normalized_tags,
            source_event_id=normalized_source_event,
            source="memory_manager",
        )
        candidate = self._memory_facade.write_candidate(request)
        consolidate_result = self._memory_facade.consolidate(MemoryConsolidateRequest(max_candidates=8))
        resolved_memory_id = (
            consolidate_result.written_memory_ids[0]
            if consolidate_result.written_memory_ids
            else f"cand_{candidate.candidate_id}"
        )
        memory = MemoryItem(
            memory_id=resolved_memory_id,
            session_id=normalized_session_id,
            content=normalized_content,
            tags=normalized_tags,
            created_at=datetime.now(UTC),
            source_event_id=normalized_source_event,
        )
        _logger.debug(
            "写入记忆成功(v2): memory_id=%s session_id=%s tag_count=%s",
            memory.memory_id,
            memory.session_id,
            len(memory.tags),
        )
        return memory

    def search(self, query: str, limit: int) -> list[MemoryItem]:
        if not isinstance(query, str) or not query.strip():
            raise ValidationError("query must be a non-empty string.")
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        bundle = self._memory_facade.read_context(
            MemoryReadRequest(
                agent_id=self._default_agent_id,
                session_id=None,
                query=query.strip(),
                limit=limit,
                token_budget=max(600, limit * 280),
            )
        )
        result = [_to_memory_item(item) for item in bundle.items]
        _logger.debug(
            "检索记忆完成(v2): query=%s limit=%s hit_count=%s",
            query.strip(),
            limit,
            len(result),
        )
        return result

    def list_memories(self, limit: int) -> list[MemoryItem]:
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        bundle = self._memory_facade.read_context(
            MemoryReadRequest(
                agent_id=self._default_agent_id,
                session_id=None,
                query="*",
                limit=limit,
                token_budget=max(800, limit * 320),
            )
        )
        result = [_to_memory_item(item) for item in bundle.items]
        _logger.debug("读取记忆列表完成(v2): limit=%s count=%s", limit, len(result))
        return result


def _to_memory_item(record: Any) -> MemoryItem:
    return MemoryItem(
        memory_id=record.memory_id,
        session_id=record.session_id,
        content=record.content,
        tags=record.tags,
        created_at=record.created_at,
        source_event_id=record.source_event_id,
    )
