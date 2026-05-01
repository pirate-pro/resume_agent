"""Memory query use cases for HTTP APIs."""

from __future__ import annotations

import logging

from app.core.errors import ValidationError
from app.domain.models import MemoryItem
from app.runtime.memory_manager import MemoryManager

__all__ = ["MemoryQueryService"]

_logger = logging.getLogger(__name__)


class MemoryQueryService:
    """Read/search memory through the runtime memory manager."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory_manager = memory_manager

    def list_memories(
        self,
        query: str | None,
        limit: int,
        request_agent_id: str,
        target_agent_id: str | None = None,
    ) -> list[MemoryItem]:
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        if not isinstance(request_agent_id, str) or not request_agent_id.strip():
            raise ValidationError("request_agent_id must be a non-empty string.")
        normalized_request_agent_id = request_agent_id.strip()
        normalized_target_agent_id = (
            target_agent_id.strip()
            if isinstance(target_agent_id, str) and target_agent_id.strip()
            else None
        )
        if query is None or not query.strip():
            memories = self._memory_manager.list_memories_for_agent(
                limit=limit,
                request_agent_id=normalized_request_agent_id,
                target_agent_id=normalized_target_agent_id,
            )
            _logger.debug(
                "读取记忆列表: request_agent=%s target_agent=%s limit=%s result_count=%s",
                normalized_request_agent_id,
                normalized_target_agent_id or normalized_request_agent_id,
                limit,
                len(memories),
            )
            return memories
        normalized = query.strip()
        memories = self._memory_manager.search_for_agent(
            query=normalized,
            limit=limit,
            request_agent_id=normalized_request_agent_id,
            target_agent_id=normalized_target_agent_id,
        )
        _logger.debug(
            "检索记忆: request_agent=%s target_agent=%s query=%s limit=%s result_count=%s",
            normalized_request_agent_id,
            normalized_target_agent_id or normalized_request_agent_id,
            normalized,
            limit,
            len(memories),
        )
        return memories
