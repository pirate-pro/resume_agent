"""Memory read/write operations for runtime."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.core.errors import ValidationError
from app.domain.models import MemoryItem, RunContext
from app.memory.contracts import MemoryFacade
from app.memory.intake import build_candidate_request, infer_scope_hint_from_tags
from app.memory.models import (
    ForgetResult,
    MemoryConsolidateRequest,
    MemoryForgetRequest,
    MemoryReadBundle,
    MemoryReadRequest,
    MemoryScope,
)
from app.runtime.agent_capability import AgentCapability, AgentCapabilityRegistry

__all__ = ["MemoryManager"]
_logger = logging.getLogger(__name__)


class MemoryManager:
    """统一封装 memory 读写策略，供 runtime 与工具复用。"""

    def __init__(
        self,
        memory_facade: MemoryFacade,
        capability_registry: AgentCapabilityRegistry,
    ) -> None:
        self._memory_facade = memory_facade
        self._capability_registry = capability_registry

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
        requester_capability = self._capability_registry.require(run_context.agent_id)
        target_scope = infer_scope_hint_from_tags(normalized_tags)
        if not requester_capability.can_write_scope(target_scope):
            raise ValidationError(f"Memory write scope not allowed for agent '{run_context.agent_id}': {target_scope.value}")
        # 默认写入当前执行 agent；仅在能力矩阵放开时允许跨 agent 写入。
        resolved_agent_id = run_context.agent_id
        if isinstance(target_agent_id, str) and target_agent_id.strip():
            normalized_target = target_agent_id.strip()
            if normalized_target != run_context.agent_id and not requester_capability.allow_cross_agent_memory_write:
                raise ValidationError("Cross-agent write is disabled by agent capability.")
            self._capability_registry.require(normalized_target)
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
        requester_capability = self._capability_registry.require(run_context.agent_id)
        read_plan = _build_context_read_plan(capability=requester_capability, session_id=run_context.session_id)
        bundle = self._read_bundle(
            agent_id=run_context.agent_id,
            query=normalized_query,
            limit=normalized_limit,
            include_scopes=read_plan.include_scopes,
            short_session_id=read_plan.short_session_id,
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
        requester_capability = self._capability_registry.require(normalized_request_agent_id)
        normalized_target_agent_id = (
            _normalize_agent_id(target_agent_id)
            if isinstance(target_agent_id, str) and target_agent_id.strip()
            else normalized_request_agent_id
        )
        # 跨 agent 读取需要能力矩阵显式放行，默认关闭，避免越权读取私有记忆。
        if (
            normalized_target_agent_id != normalized_request_agent_id
            and not requester_capability.allow_cross_agent_memory_read
        ):
            raise ValidationError("Cross-agent read is disabled by agent capability.")
        self._capability_registry.require(normalized_target_agent_id)
        read_plan = _build_agent_read_plan(
            capability=requester_capability,
            session_id=None,
        )
        bundle = self._read_bundle(
            agent_id=normalized_target_agent_id,
            query=normalized_query,
            limit=normalized_limit,
            include_scopes=read_plan.include_scopes,
            short_session_id=read_plan.short_session_id,
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
        requester_capability = self._capability_registry.require(normalized_request_agent_id)
        normalized_target_agent_id = (
            _normalize_agent_id(target_agent_id)
            if isinstance(target_agent_id, str) and target_agent_id.strip()
            else normalized_request_agent_id
        )
        # 列表读取同样受跨 agent 开关约束。
        if (
            normalized_target_agent_id != normalized_request_agent_id
            and not requester_capability.allow_cross_agent_memory_read
        ):
            raise ValidationError("Cross-agent read is disabled by agent capability.")
        self._capability_registry.require(normalized_target_agent_id)
        read_plan = _build_agent_read_plan(
            capability=requester_capability,
            session_id=None,
        )
        bundle = self._read_bundle(
            agent_id=normalized_target_agent_id,
            query="*",
            limit=normalized_limit,
            include_scopes=read_plan.include_scopes,
            short_session_id=read_plan.short_session_id,
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

    def forget_memory_ids(
        self,
        *,
        context: RunContext,
        memory_ids: list[str],
        scopes: list[MemoryScope],
        hard_delete: bool = False,
        reason: str | None = None,
    ) -> ForgetResult:
        run_context = _normalize_context(context)
        normalized_ids = _normalize_memory_ids(memory_ids)
        normalized_scopes = _normalize_scopes(scopes)
        if not isinstance(hard_delete, bool):
            raise ValidationError("hard_delete must be bool.")
        normalized_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None

        requester_capability = self._capability_registry.require(run_context.agent_id)
        for scope in normalized_scopes:
            if not requester_capability.can_write_scope(scope):
                raise ValidationError(
                    f"Memory forget scope not allowed for agent '{run_context.agent_id}': {scope.value}"
                )

        # 包含 shared_long 时需允许 owner_agent_id=None 的记录参与匹配。
        request_agent_id = None if MemoryScope.SHARED_LONG in normalized_scopes else run_context.agent_id
        request = MemoryForgetRequest(
            agent_id=request_agent_id,
            session_id=None,
            scopes=normalized_scopes,
            before=None,
            memory_ids=normalized_ids,
            hard_delete=hard_delete,
            reason=normalized_reason,
        )
        result = self._memory_facade.forget(request)
        _logger.debug(
            "遗忘记忆完成(v2): agent_id=%s memory_ids=%s scopes=%s touched=%s deleted=%s archived=%s",
            run_context.agent_id,
            len(normalized_ids),
            [item.value for item in normalized_scopes],
            result.touched_records,
            result.deleted_records,
            result.archived_records,
        )
        return result

    # 统一读取入口：所有检索路径都走这一条，避免策略分叉。
    def _read_bundle(
        self,
        *,
        agent_id: str,
        query: str,
        limit: int,
        include_scopes: list[MemoryScope],
        short_session_id: str | None,
    ) -> MemoryReadBundle:
        return self._memory_facade.read_context(
            MemoryReadRequest(
                agent_id=agent_id,
                session_id=short_session_id,
                query=query,
                include_scopes=include_scopes,
                limit=limit,
                token_budget=max(600, limit * 280),
            )
        )


class _ReadPlan:
    def __init__(self, include_scopes: list[MemoryScope], short_session_id: str | None) -> None:
        self.include_scopes = include_scopes
        self.short_session_id = short_session_id


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


def _normalize_memory_ids(memory_ids: list[str]) -> list[str]:
    if not isinstance(memory_ids, list) or not memory_ids:
        raise ValidationError("memory_ids must be a non-empty list.")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in memory_ids:
        if not isinstance(raw, str) or not raw.strip():
            raise ValidationError("memory_ids entries must be non-empty strings.")
        item = raw.strip()
        if item in seen:
            continue
        normalized.append(item)
        seen.add(item)
    if not normalized:
        raise ValidationError("memory_ids must contain at least one valid id.")
    return normalized


def _normalize_scopes(scopes: list[MemoryScope]) -> list[MemoryScope]:
    if not isinstance(scopes, list) or not scopes:
        raise ValidationError("scopes must be a non-empty list.")
    output: list[MemoryScope] = []
    seen: set[MemoryScope] = set()
    for raw in scopes:
        if isinstance(raw, MemoryScope):
            scope = raw
        elif isinstance(raw, str) and raw.strip():
            try:
                scope = MemoryScope(raw.strip())
            except ValueError as exc:
                raise ValidationError(f"Unsupported memory scope: {raw}") from exc
        else:
            raise ValidationError("scopes entries must be MemoryScope or non-empty string.")
        if scope in seen:
            continue
        output.append(scope)
        seen.add(scope)
    if not output:
        raise ValidationError("scopes cannot be empty after normalization.")
    return output


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


def _build_context_read_plan(capability: AgentCapability, session_id: str) -> _ReadPlan:
    scopes = list(capability.memory_read_scopes)
    short_session_id = None
    if MemoryScope.AGENT_SHORT in scopes and not capability.allow_cross_session_short_read:
        short_session_id = session_id
    return _ReadPlan(include_scopes=scopes, short_session_id=short_session_id)


def _build_agent_read_plan(capability: AgentCapability, session_id: str | None) -> _ReadPlan:
    scopes = list(capability.memory_read_scopes)
    short_session_id = None
    if MemoryScope.AGENT_SHORT in scopes:
        if capability.allow_cross_session_short_read:
            short_session_id = None
        else:
            # 非会话上下文查询默认不扫描 short，防止在 API/管理接口跨会话泄露短期记忆。
            if session_id is None:
                scopes = [scope for scope in scopes if scope != MemoryScope.AGENT_SHORT]
            else:
                short_session_id = session_id
    return _ReadPlan(include_scopes=scopes, short_session_id=short_session_id)
