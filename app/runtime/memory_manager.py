"""Memory read/write operations for runtime."""

from __future__ import annotations

import logging
from typing import Any

from app.core.errors import ValidationError
from app.domain.models import MemoryItem, RunContext
from app.memory.admission import evaluate_memory_admission
from app.memory.models import (
    ForgetResult,
    MemoryReadBundle,
    MemoryRecord,
    MemoryScope,
)
from app.memory.file_store import FileMemoryStore
from app.memory.write_plan import build_memory_write_plan, infer_write_scope_from_tags
from app.runtime.agent_capability import AgentCapabilityRegistry
from app.runtime.memory.context_lanes import (
    dedupe_records,
    flatten_memory_lanes,
    group_records_by_context_lane,
    limit_memory_lanes,
)
from app.runtime.memory.models import MemoryWriteResult
from app.runtime.memory.read_plans import build_agent_read_plan, build_context_read_plan
from app.runtime.memory.serializers import (
    build_search_summary,
    memory_item_from_fact,
    memory_metadata_from_plan,
    to_memory_item,
)
from app.runtime.memory.validation import (
    normalize_agent_id,
    normalize_context,
    normalize_limit,
    normalize_memory_ids,
    normalize_query,
    normalize_scopes,
)

__all__ = ["MemoryManager", "MemoryWriteResult"]
_logger = logging.getLogger(__name__)


class MemoryManager:
    """统一封装 memory 读写策略，供 runtime 与工具复用。"""

    def __init__(
        self,
        capability_registry: AgentCapabilityRegistry,
        memory_store: FileMemoryStore,
    ) -> None:
        self._capability_registry = capability_registry
        self._memory_store = memory_store

    def write_memory(
        self,
        content: str,
        tags: list[str],
        context: RunContext,
        source_event_id: str | None,
        source: str = "memory_manager",
        target_agent_id: str | None = None,
    ) -> MemoryItem:
        result = self.write_memory_with_result(
            content=content,
            tags=tags,
            context=context,
            source_event_id=source_event_id,
            source=source,
            target_agent_id=target_agent_id,
        )
        return result.memory

    def write_memory_with_result(
        self,
        content: str,
        tags: list[str],
        context: RunContext,
        source_event_id: str | None,
        source: str = "memory_manager",
        target_agent_id: str | None = None,
    ) -> MemoryWriteResult:
        run_context = normalize_context(context)
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("content must be a non-empty string.")
        if not isinstance(tags, list):
            raise ValidationError("tags must be a list.")

        normalized_source_event = (
            source_event_id.strip() if isinstance(source_event_id, str) and source_event_id.strip() else None
        )
        normalized_content = content.strip()
        normalized_tags = [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]
        admission = evaluate_memory_admission(normalized_content, normalized_tags)
        if not admission.accepted:
            raise ValidationError(admission.reason)
        requester_capability = self._capability_registry.require(run_context.agent_id)
        target_scope = infer_write_scope_from_tags(normalized_tags)
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
        plan = build_memory_write_plan(
            agent_id=resolved_agent_id,
            session_id=run_context.session_id,
            content=normalized_content,
            tags=normalized_tags,
            source_event_id=normalized_source_event,
            source=source,
        )
        existing_fact = self._memory_store.find_active_fact_by_content(
            scope=plan.scope,
            agent_id=None if plan.scope == MemoryScope.SHARED_LONG else resolved_agent_id,
            content=plan.content,
        )
        if existing_fact is not None:
            memory = memory_item_from_fact(
                fact=existing_fact,
                session_id=run_context.session_id,
                scope=plan.scope,
                source_kind=plan.source_kind,
            )
            _logger.debug(
                "跳过重复记忆写入: memory_id=%s session_id=%s agent_id=%s scope=%s",
                memory.memory_id,
                memory.session_id,
                resolved_agent_id,
                plan.scope.value,
            )
            return MemoryWriteResult(
                memory=memory,
                write_id=plan.write_key,
                written_records=0,
                written_memory_ids=[],
            )
        if plan.canonical_key and plan.scope in {MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG}:
            archived = self._memory_store.archive_active_facts_by_canonical_key(
                scope=plan.scope,
                agent_id=None if plan.scope == MemoryScope.SHARED_LONG else resolved_agent_id,
                canonical_key=plan.canonical_key,
                reason=f"canonical_replace:{plan.canonical_key}",
            )
            if archived.archived_records:
                _logger.debug(
                    "归档同 canonical_key 旧记忆: key=%s archived=%s agent_id=%s scope=%s",
                    plan.canonical_key,
                    archived.archived_records,
                    resolved_agent_id,
                    plan.scope.value,
                )
        fact = self._memory_store.append_fact(
            content=plan.content,
            category=plan.category,
            confidence=plan.confidence,
            scope=plan.scope,
            owner_agent_id=None if plan.scope == MemoryScope.SHARED_LONG else resolved_agent_id,
            session_id=run_context.session_id,
            source_event_id=normalized_source_event,
            source_type=source,
            tags=plan.tags,
            inject_policy=plan.inject_policy,
            metadata=memory_metadata_from_plan(
                plan=plan,
                source_agent_id=run_context.agent_id,
                target_agent_id=resolved_agent_id,
            ),
        )
        self._refresh_long_term_summary_best_effort(scope=plan.scope, agent_id=resolved_agent_id)
        memory_metadata = dict(fact.metadata)
        memory_metadata.update(
            {
                "memory_layer": "facts",
                "storage_scope": fact.scope,
                "category": fact.category,
                "visibility": fact.visibility,
                "inject_policy": fact.inject_policy,
            }
        )
        memory = MemoryItem(
            memory_id=fact.id,
            session_id=run_context.session_id,
            content=fact.content,
            tags=fact.tags,
            created_at=fact.created_at,
            source_event_id=normalized_source_event,
            scope=plan.scope.value,
            memory_layer="facts",
            source_kind=plan.source_kind,
            metadata=memory_metadata,
        )
        _logger.debug(
            "写入记忆成功: memory_id=%s session_id=%s agent_id=%s scope=%s tag_count=%s",
            memory.memory_id,
            memory.session_id,
            resolved_agent_id,
            plan.scope.value,
            len(memory.tags),
        )
        return MemoryWriteResult(
            memory=memory,
            write_id=plan.write_key,
            written_records=1,
            written_memory_ids=[fact.id],
        )

    def search(self, query: str, limit: int, context: RunContext) -> list[MemoryItem]:
        items, _ = self.search_with_summary(query=query, limit=limit, context=context)
        return items

    def search_context_memories(
        self,
        query: str,
        limit: int,
        context: RunContext,
    ) -> tuple[list[MemoryItem], dict[str, Any]]:
        lanes, summary = self.search_context_memory_lanes(query=query, limit=limit, context=context)
        result = flatten_memory_lanes(lanes)
        summary["hit_count"] = len(result)
        return result, summary

    def search_context_memory_lanes(
        self,
        query: str,
        limit: int,
        context: RunContext,
    ) -> tuple[dict[str, list[MemoryItem]], dict[str, Any]]:
        run_context = normalize_context(context)
        normalized_query, normalized_limit, bundle = self._search_bundle_for_context(
            query=query,
            limit=max(limit * 2, 12),
            context=run_context,
        )
        requester_capability = self._capability_registry.require(run_context.agent_id)
        read_plan = build_context_read_plan(
            capability=requester_capability,
            session_id=run_context.session_id,
            include_short=False,
        )
        standing_bundle = self._read_bundle(
            agent_id=run_context.agent_id,
            query="*",
            limit=max(normalized_limit * 3, 12),
            include_scopes=read_plan.include_scopes,
            short_session_id=read_plan.short_session_id,
            standing_only=True,
            include_long_term_summaries=True,
        )
        records = dedupe_records(bundle.items + standing_bundle.items)
        lanes = limit_memory_lanes(group_records_by_context_lane(records), max_total=normalized_limit)
        result = flatten_memory_lanes(lanes)
        summary = build_search_summary(
            query=normalized_query,
            agent_id=run_context.agent_id,
            session_id=run_context.session_id,
            bundle=bundle,
            hit_count=len(result),
        )
        summary["standing_count"] = len(standing_bundle.items)
        summary["total_scanned"] = bundle.total_scanned + standing_bundle.total_scanned
        summary["lanes"] = {lane: len(items) for lane, items in lanes.items()}
        _logger.debug(
            "检索上下文长期记忆完成: query=%s limit=%s agent_id=%s hit_count=%s scanned=%s lanes=%s",
            normalized_query,
            normalized_limit,
            run_context.agent_id,
            len(result),
            bundle.total_scanned,
            summary["lanes"],
        )
        return lanes, summary

    def search_with_summary(
        self,
        query: str,
        limit: int,
        context: RunContext,
    ) -> tuple[list[MemoryItem], dict[str, Any]]:
        run_context = normalize_context(context)
        normalized_query, normalized_limit, bundle = self.search_bundle(
            query=query,
            limit=limit,
            context=run_context,
        )
        result = [to_memory_item(item) for item in bundle.items]
        summary = build_search_summary(
            query=normalized_query,
            agent_id=run_context.agent_id,
            session_id=run_context.session_id,
            bundle=bundle,
            hit_count=len(result),
        )
        _logger.debug(
            "检索记忆完成: query=%s limit=%s agent_id=%s hit_count=%s scanned=%s",
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
        run_context = normalize_context(context)
        normalized_query = normalize_query(query)
        normalized_limit = normalize_limit(limit)
        requester_capability = self._capability_registry.require(run_context.agent_id)
        read_plan = build_context_read_plan(capability=requester_capability, session_id=run_context.session_id)
        bundle = self._read_bundle(
            agent_id=run_context.agent_id,
            query=normalized_query,
            limit=normalized_limit,
            include_scopes=read_plan.include_scopes,
            short_session_id=read_plan.short_session_id,
        )
        return normalized_query, normalized_limit, bundle

    def resolve_update_targets(
        self,
        *,
        query: str,
        limit: int,
        context: RunContext,
    ) -> tuple[list[MemoryRecord], str]:
        run_context = normalize_context(context)
        normalized_query = normalize_query(query)
        normalized_limit = normalize_limit(limit)
        _, _, bundle = self.search_bundle(
            query=normalized_query,
            limit=normalized_limit,
            context=run_context,
        )
        return bundle.items, "text_search"

    def _search_bundle_for_context(
        self,
        *,
        query: str,
        limit: int,
        context: RunContext,
    ) -> tuple[str, int, MemoryReadBundle]:
        run_context = normalize_context(context)
        normalized_query = normalize_query(query)
        normalized_limit = normalize_limit(limit)
        requester_capability = self._capability_registry.require(run_context.agent_id)
        read_plan = build_context_read_plan(
            capability=requester_capability,
            session_id=run_context.session_id,
            include_short=False,
        )
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
        normalized_query = normalize_query(query)
        normalized_limit = normalize_limit(limit)
        normalized_request_agent_id = normalize_agent_id(request_agent_id)
        requester_capability = self._capability_registry.require(normalized_request_agent_id)
        normalized_target_agent_id = (
            normalize_agent_id(target_agent_id)
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
        read_plan = build_agent_read_plan(
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
        result = [to_memory_item(item) for item in bundle.items]
        _logger.debug(
            "检索记忆完成: query=%s limit=%s request_agent=%s target_agent=%s hit_count=%s",
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
        normalized_limit = normalize_limit(limit)
        normalized_request_agent_id = normalize_agent_id(request_agent_id)
        requester_capability = self._capability_registry.require(normalized_request_agent_id)
        normalized_target_agent_id = (
            normalize_agent_id(target_agent_id)
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
        read_plan = build_agent_read_plan(
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
        result = [to_memory_item(item) for item in bundle.items]
        _logger.debug(
            "读取记忆列表完成: request_agent=%s target_agent=%s limit=%s count=%s",
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
        run_context = normalize_context(context)
        normalized_ids = normalize_memory_ids(memory_ids)
        normalized_scopes = normalize_scopes(scopes)
        if not isinstance(hard_delete, bool):
            raise ValidationError("hard_delete must be bool.")
        normalized_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None

        requester_capability = self._capability_registry.require(run_context.agent_id)
        for scope in normalized_scopes:
            if not requester_capability.can_write_scope(scope):
                raise ValidationError(
                    f"Memory forget scope not allowed for agent '{run_context.agent_id}': {scope.value}"
                )

        result = self._memory_store.forget(
            agent_id=run_context.agent_id,
            memory_ids=normalized_ids,
            scopes=normalized_scopes,
            hard_delete=hard_delete,
            reason=normalized_reason,
        )
        if result.touched_records > 0:
            for scope in normalized_scopes:
                self._refresh_long_term_summary_best_effort(scope=scope, agent_id=run_context.agent_id)
        _logger.debug(
            "遗忘记忆完成: agent_id=%s memory_ids=%s scopes=%s touched=%s deleted=%s archived=%s",
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
        standing_only: bool = False,
        include_long_term_summaries: bool = False,
    ) -> MemoryReadBundle:
        _ = short_session_id
        return self._memory_store.read_bundle(
            agent_id=agent_id,
            query=query,
            limit=limit,
            include_scopes=include_scopes,
            short_session_id=short_session_id,
            standing_only=standing_only,
            include_long_term_summaries=include_long_term_summaries,
        )

    def _refresh_long_term_summary_best_effort(
        self,
        *,
        scope: MemoryScope,
        agent_id: str,
    ) -> None:
        try:
            if scope == MemoryScope.SHARED_LONG:
                self._memory_store.refresh_long_term_summary_from_facts(
                    scope=MemoryScope.SHARED_LONG,
                    agent_id=None,
                )
                return
            if scope == MemoryScope.AGENT_LONG:
                self._memory_store.refresh_long_term_summary_from_facts(
                    scope=MemoryScope.AGENT_LONG,
                    agent_id=agent_id,
                )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "刷新 long-term summary 失败(忽略，不影响主链路): agent_id=%s scope=%s error=%s",
                agent_id,
                scope.value,
                exc,
            )
