"""Memory read/write operations for runtime."""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
from app.memory.policies import (
    CONTEXT_LANE_LIMITS,
    CONTEXT_LANE_ORDER,
    memory_lane_for_metadata,
)
from app.memory.v3_models import MemoryV3Fact
from app.memory.v3_store import FileMemoryV3Store
from app.memory.write_plan import MemoryWritePlan, build_memory_write_plan, infer_write_scope_from_tags
from app.runtime.agent_capability import AgentCapability, AgentCapabilityRegistry

__all__ = ["MemoryManager", "MemoryWriteResult"]
_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MemoryWriteResult:
    memory: MemoryItem
    write_id: str
    written_records: int
    written_memory_ids: list[str]


class MemoryManager:
    """统一封装 memory 读写策略，供 runtime 与工具复用。"""

    def __init__(
        self,
        capability_registry: AgentCapabilityRegistry,
        memory_v3_store: FileMemoryV3Store,
    ) -> None:
        self._capability_registry = capability_registry
        self._memory_v3_store = memory_v3_store

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
        existing_fact = self._memory_v3_store.find_active_fact_by_content(
            scope=plan.scope,
            agent_id=None if plan.scope == MemoryScope.SHARED_LONG else resolved_agent_id,
            content=plan.content,
        )
        if existing_fact is not None:
            memory = _memory_item_from_fact(
                fact=existing_fact,
                session_id=run_context.session_id,
                scope=plan.scope,
                source_kind=plan.source_kind,
            )
            _logger.debug(
                "跳过重复记忆写入(v3): memory_id=%s session_id=%s agent_id=%s scope=%s",
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
            archived = self._memory_v3_store.archive_active_facts_by_canonical_key(
                scope=plan.scope,
                agent_id=None if plan.scope == MemoryScope.SHARED_LONG else resolved_agent_id,
                canonical_key=plan.canonical_key,
                reason=f"canonical_replace:{plan.canonical_key}",
            )
            if archived.archived_records:
                _logger.debug(
                    "归档同 canonical_key 旧记忆(v3): key=%s archived=%s agent_id=%s scope=%s",
                    plan.canonical_key,
                    archived.archived_records,
                    resolved_agent_id,
                    plan.scope.value,
                )
        fact = self._memory_v3_store.append_fact(
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
            metadata=_v3_metadata_from_plan(
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
                "v3_scope": fact.scope,
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
            "写入记忆成功(v3): memory_id=%s session_id=%s agent_id=%s scope=%s tag_count=%s",
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
        result = _flatten_memory_lanes(lanes)
        summary["hit_count"] = len(result)
        return result, summary

    def search_context_memory_lanes(
        self,
        query: str,
        limit: int,
        context: RunContext,
    ) -> tuple[dict[str, list[MemoryItem]], dict[str, Any]]:
        run_context = _normalize_context(context)
        normalized_query, normalized_limit, bundle = self._search_bundle_for_context(
            query=query,
            limit=max(limit * 2, 12),
            context=run_context,
        )
        requester_capability = self._capability_registry.require(run_context.agent_id)
        read_plan = _build_context_read_plan(
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
        records = _dedupe_records(bundle.items + standing_bundle.items)
        lanes = _limit_memory_lanes(_group_records_by_context_lane(records), max_total=normalized_limit)
        result = _flatten_memory_lanes(lanes)
        summary = _build_search_summary(
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
            "检索上下文长期记忆完成(v3): query=%s limit=%s agent_id=%s hit_count=%s scanned=%s lanes=%s",
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
            "检索记忆完成(v3): query=%s limit=%s agent_id=%s hit_count=%s scanned=%s",
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

    def resolve_update_targets(
        self,
        *,
        query: str,
        limit: int,
        context: RunContext,
    ) -> tuple[list[MemoryRecord], str]:
        run_context = _normalize_context(context)
        normalized_query = _normalize_query(query)
        normalized_limit = _normalize_limit(limit)
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
        run_context = _normalize_context(context)
        normalized_query = _normalize_query(query)
        normalized_limit = _normalize_limit(limit)
        requester_capability = self._capability_registry.require(run_context.agent_id)
        read_plan = _build_context_read_plan(
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
            "检索记忆完成(v3): query=%s limit=%s request_agent=%s target_agent=%s hit_count=%s",
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
            "读取记忆列表完成(v3): request_agent=%s target_agent=%s limit=%s count=%s",
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

        result = self._memory_v3_store.forget(
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
            "遗忘记忆完成(v3): agent_id=%s memory_ids=%s scopes=%s touched=%s deleted=%s archived=%s",
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
        return self._memory_v3_store.read_bundle(
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
                self._memory_v3_store.refresh_long_term_summary_from_facts(
                    scope=MemoryScope.SHARED_LONG,
                    agent_id=None,
                )
                return
            if scope == MemoryScope.AGENT_LONG:
                self._memory_v3_store.refresh_long_term_summary_from_facts(
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


def _group_records_by_context_lane(records: list[MemoryRecord]) -> dict[str, list[MemoryItem]]:
    lanes: dict[str, list[MemoryItem]] = {lane: [] for lane in CONTEXT_LANE_ORDER}
    for record in records:
        lane = _context_lane_for_record(record)
        lanes.setdefault(lane, []).append(_to_memory_item(record))
    return lanes


def _context_lane_for_record(record: MemoryRecord) -> str:
    return memory_lane_for_metadata(record.canonical_key, record.kind)


def _limit_memory_lanes(
    lanes: dict[str, list[MemoryItem]],
    *,
    max_total: int,
) -> dict[str, list[MemoryItem]]:
    limited: dict[str, list[MemoryItem]] = {}
    remaining = max(0, max_total)
    for lane in CONTEXT_LANE_ORDER:
        if remaining <= 0:
            break
        items = lanes.get(lane, [])
        if not items:
            continue
        lane_limit = min(CONTEXT_LANE_LIMITS[lane], remaining)
        selected = _dedupe_memory_items(items)[:lane_limit]
        if not selected:
            continue
        limited[lane] = selected
        remaining -= len(selected)
    return limited


def _flatten_memory_lanes(lanes: dict[str, list[MemoryItem]]) -> list[MemoryItem]:
    flattened: list[MemoryItem] = []
    for lane in CONTEXT_LANE_ORDER:
        flattened.extend(lanes.get(lane, []))
    return _dedupe_memory_items(flattened)


def _dedupe_records(records: list[MemoryRecord]) -> list[MemoryRecord]:
    output: list[MemoryRecord] = []
    seen: set[str] = set()
    for record in records:
        if record.memory_id in seen:
            continue
        seen.add(record.memory_id)
        output.append(record)
    return output


def _dedupe_memory_items(items: list[MemoryItem]) -> list[MemoryItem]:
    output: list[MemoryItem] = []
    seen: set[str] = set()
    for item in items:
        if item.memory_id in seen:
            continue
        seen.add(item.memory_id)
        output.append(item)
    return output


def _v3_metadata_from_plan(
    *,
    plan: MemoryWritePlan,
    source_agent_id: str,
    target_agent_id: str,
) -> dict[str, str]:
    metadata: dict[str, str] = {
        "source_agent_id": source_agent_id,
        "target_agent_id": target_agent_id,
        "memory_type": plan.memory_type.value,
        "memory_scope": plan.scope.value,
        "kind": plan.kind,
        "source_kind": plan.source_kind,
        "subject_kind": plan.subject_kind,
        "classification_version": plan.classification_version,
        "write_key": plan.write_key,
    }
    if plan.canonical_key:
        metadata["canonical_key"] = plan.canonical_key
    if plan.normalized_value:
        metadata["normalized_value"] = plan.normalized_value
    raw_source = plan.metadata.get("source") if isinstance(plan.metadata, dict) else None
    if isinstance(raw_source, str) and raw_source.strip():
        metadata["source"] = raw_source.strip()
    return metadata

def _to_memory_item(record: Any) -> MemoryItem:
    raw_scope = getattr(record, "scope", None)
    if isinstance(raw_scope, MemoryScope):
        scope = raw_scope.value
    elif raw_scope is None:
        scope = None
    else:
        scope = str(raw_scope)
    metadata = getattr(record, "metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    memory_layer = metadata.get("memory_layer")
    source_kind = getattr(record, "source_kind", None)
    return MemoryItem(
        memory_id=record.memory_id,
        session_id=record.session_id,
        content=record.content,
        tags=record.tags,
        created_at=record.created_at,
        source_event_id=record.source_event_id,
        scope=scope,
        memory_layer=str(memory_layer) if memory_layer else None,
        source_kind=str(source_kind) if source_kind else None,
        metadata={str(key): str(value) for key, value in metadata.items()},
    )


def _memory_item_from_fact(
    *,
    fact: MemoryV3Fact,
    session_id: str,
    scope: MemoryScope,
    source_kind: str,
) -> MemoryItem:
    metadata = dict(fact.metadata)
    metadata.update(
        {
            "memory_layer": "facts",
            "v3_scope": fact.scope,
            "category": fact.category,
            "visibility": fact.visibility,
            "inject_policy": fact.inject_policy,
            "duplicate_write": "true",
        }
    )
    source_event_id = fact.source.event_ids[0] if fact.source.event_ids else None
    return MemoryItem(
        memory_id=fact.id,
        session_id=session_id,
        content=fact.content,
        tags=fact.tags,
        created_at=fact.created_at,
        source_event_id=source_event_id,
        scope=scope.value,
        memory_layer="facts",
        source_kind=source_kind,
        metadata={str(key): str(value) for key, value in metadata.items()},
    )


def _build_context_read_plan(capability: AgentCapability, session_id: str, *, include_short: bool = True) -> _ReadPlan:
    scopes = list(capability.memory_read_scopes)
    if not include_short:
        scopes = [scope for scope in scopes if scope != MemoryScope.AGENT_SHORT]
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
