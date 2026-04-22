"""Memory read/write operations for runtime."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.core.errors import ValidationError
from app.domain.models import MemoryItem, RunContext
from app.memory.contracts import MemoryFacade
from app.memory.intake import build_candidate_request
from app.memory.models import MemoryConsolidateRequest, MemoryReadBundle, MemoryReadRequest

__all__ = ["MemoryManager"]
_logger = logging.getLogger(__name__)


class MemoryManager:
    """统一封装 memory 读写策略，供 runtime 与工具复用。"""

    def __init__(
        self,
        memory_facade: MemoryFacade,
        *,
        allow_cross_agent_read: bool = False,
        allow_cross_agent_write: bool = False,
    ) -> None:
        self._memory_facade = memory_facade
        self._allow_cross_agent_read = allow_cross_agent_read
        self._allow_cross_agent_write = allow_cross_agent_write

    def write_memory(
        self,
        content: str,
        tags: list[str],
        context: RunContext,
        source_event_id: str | None,
        source: str = "memory_manager",
        target_agent_id: str | None = None,
    ) -> MemoryItem:
        run_context = _normalize_context(context)
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("content must be a non-empty string.")
        if not isinstance(tags, list):
            raise ValidationError("tags must be a list.")

        normalized_source_event = (
            source_event_id.strip() if isinstance(source_event_id, str) and source_event_id.strip() else None
        )
        normalized_content = content.strip()
        normalized_tags = [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]
        # 默认写入当前执行 agent；仅在策略放开时允许跨 agent 写入。
        resolved_agent_id = run_context.agent_id
        if isinstance(target_agent_id, str) and target_agent_id.strip():
            normalized_target = target_agent_id.strip()
            if normalized_target != run_context.agent_id and not self._allow_cross_agent_write:
                raise ValidationError("Cross-agent write is disabled by memory policy.")
            resolved_agent_id = normalized_target
        request = build_candidate_request(
            agent_id=resolved_agent_id,
            session_id=run_context.session_id,
            content=normalized_content,
            tags=normalized_tags,
            source_event_id=normalized_source_event,
            source=source,
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
            session_id=run_context.session_id,
            content=normalized_content,
            tags=normalized_tags,
            created_at=datetime.now(UTC),
            source_event_id=normalized_source_event,
        )
        _logger.debug(
            "写入记忆成功(v2): memory_id=%s session_id=%s agent_id=%s tag_count=%s",
            memory.memory_id,
            memory.session_id,
            resolved_agent_id,
            len(memory.tags),
        )
        return memory

    def search(self, query: str, limit: int, context: RunContext) -> list[MemoryItem]:
        items, _ = self.search_with_summary(query=query, limit=limit, context=context)
        return items

    def search_with_summary(
        self,
        query: str,
        limit: int,
        context: RunContext,
    ) -> tuple[list[MemoryItem], dict[str, Any]]:
        run_context = _normalize_context(context)
        normalized_query, normalized_limit, bundle = self.search_bundle(
            query=query,
            limit=limit,
            context=run_context,
        )
        result = [_to_memory_item(item) for item in bundle.items]
        summary = _build_search_summary(
            query=normalized_query,
            agent_id=run_context.agent_id,
            session_id=run_context.session_id,
            bundle=bundle,
            hit_count=len(result),
        )
        _logger.debug(
            "检索记忆完成(v2): query=%s limit=%s agent_id=%s hit_count=%s scanned=%s",
            normalized_query,
            normalized_limit,
            run_context.agent_id,
            len(result),
            bundle.total_scanned,
        )
        return result, summary

    def search_bundle(
        self,
        query: str,
        limit: int,
        context: RunContext,
    ) -> tuple[str, int, MemoryReadBundle]:
        run_context = _normalize_context(context)
        normalized_query = _normalize_query(query)
        normalized_limit = _normalize_limit(limit)
        bundle = self._read_bundle(
            agent_id=run_context.agent_id,
            query=normalized_query,
            limit=normalized_limit,
        )
        return normalized_query, normalized_limit, bundle

    def search_for_agent(
        self,
        query: str,
        limit: int,
        request_agent_id: str,
        target_agent_id: str | None = None,
    ) -> list[MemoryItem]:
        normalized_query = _normalize_query(query)
        normalized_limit = _normalize_limit(limit)
        normalized_request_agent_id = _normalize_agent_id(request_agent_id)
        normalized_target_agent_id = (
            _normalize_agent_id(target_agent_id)
            if isinstance(target_agent_id, str) and target_agent_id.strip()
            else normalized_request_agent_id
        )
        # 跨 agent 读取需要显式开关，默认关闭，避免越权读取私有记忆。
        if normalized_target_agent_id != normalized_request_agent_id and not self._allow_cross_agent_read:
            raise ValidationError("Cross-agent read is disabled by memory policy.")
        bundle = self._read_bundle(
            agent_id=normalized_target_agent_id,
            query=normalized_query,
            limit=normalized_limit,
        )
        result = [_to_memory_item(item) for item in bundle.items]
        _logger.debug(
            "检索记忆完成(v2): query=%s limit=%s request_agent=%s target_agent=%s hit_count=%s",
            normalized_query,
            normalized_limit,
            normalized_request_agent_id,
            normalized_target_agent_id,
            len(result),
        )
        return result

    def list_memories_for_agent(
        self,
        limit: int,
        request_agent_id: str,
        target_agent_id: str | None = None,
    ) -> list[MemoryItem]:
        normalized_limit = _normalize_limit(limit)
        normalized_request_agent_id = _normalize_agent_id(request_agent_id)
        normalized_target_agent_id = (
            _normalize_agent_id(target_agent_id)
            if isinstance(target_agent_id, str) and target_agent_id.strip()
            else normalized_request_agent_id
        )
        # 列表读取同样受跨 agent 开关约束。
        if normalized_target_agent_id != normalized_request_agent_id and not self._allow_cross_agent_read:
            raise ValidationError("Cross-agent read is disabled by memory policy.")
        bundle = self._read_bundle(
            agent_id=normalized_target_agent_id,
            query="*",
            limit=normalized_limit,
        )
        result = [_to_memory_item(item) for item in bundle.items]
        _logger.debug(
            "读取记忆列表完成(v2): request_agent=%s target_agent=%s limit=%s count=%s",
            normalized_request_agent_id,
            normalized_target_agent_id,
            normalized_limit,
            len(result),
        )
        return result

    # 统一读取入口：所有检索路径都走这一条，避免策略分叉。
    def _read_bundle(
        self,
        *,
        agent_id: str,
        query: str,
        limit: int,
    ) -> MemoryReadBundle:
        return self._memory_facade.read_context(
            MemoryReadRequest(
                agent_id=agent_id,
                session_id=None,
                query=query,
                limit=limit,
                token_budget=max(600, limit * 280),
            )
        )


def _normalize_context(context: RunContext) -> RunContext:
    if not isinstance(context, RunContext):
        raise ValidationError("context must be RunContext.")
    return context


def _normalize_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValidationError("query must be a non-empty string.")
    return query.strip()


def _normalize_limit(limit: int) -> int:
    if limit <= 0:
        raise ValidationError("limit must be positive.")
    return limit


def _normalize_agent_id(agent_id: str) -> str:
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValidationError("agent_id must be a non-empty string.")
    return agent_id.strip()


def _build_search_summary(
    *,
    query: str,
    agent_id: str,
    session_id: str,
    bundle: MemoryReadBundle,
    hit_count: int,
) -> dict[str, Any]:
    return {
        "query": query,
        "agent_id": agent_id,
        "session_id": session_id,
        "hit_count": hit_count,
        "searched_scopes": [scope.value for scope in bundle.searched_scopes],
        "total_scanned": bundle.total_scanned,
        "truncated": bundle.truncated,
        "notes": bundle.notes,
    }


def _to_memory_item(record: Any) -> MemoryItem:
    return MemoryItem(
        memory_id=record.memory_id,
        session_id=record.session_id,
        content=record.content,
        tags=record.tags,
        created_at=record.created_at,
        source_event_id=record.source_event_id,
    )
