"""Built-in memory tools."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.errors import ToolExecutionError, ValidationError
from app.domain.models import RunContext, ToolDefinition, ToolExecutionResult
from app.memory.admission import evaluate_memory_admission
from app.runtime.memory_manager import MemoryManager
from app.tools.builtin_tools.common import (
    normalize_tags,
    optional_string_argument,
    require_non_empty_argument,
    validate_context,
)
from app.tools.builtin_tools.memory_helpers import (
    build_ambiguous_update_payload,
    build_explain_payload,
    build_no_match_update_payload,
    build_rejected_update_payload,
    build_semantic_noop_update_payload,
    build_source_priority_conflict_payload,
    build_successful_update_payload,
    dedupe_scopes,
    parse_bool_argument,
    parse_limit_argument,
    resolve_update_tags,
    serialize_memory_record,
    update_allowed_by_source_priority,
)

_logger = logging.getLogger(__name__)


class MemoryWriteTool:
    """写入记忆候选。"""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory_manager = memory_manager

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="memory_write",
            description=(
                "Write a durable memory fact. Default route is current agent private memory. "
                "Rejects session working state and raw file/tool output; use state_set for current task notes. "
                "Use tags like preference/constraint/long_term for durable memory; only identity, strong rules, "
                "and policies are injected by default. Use shared/global/cross_agent only for shared memory."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                    },
                },
                "required": ["content"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        content = require_non_empty_argument(arguments, "content")
        tags = normalize_tags(arguments.get("tags", []))
        _logger.debug(
            "执行 memory_write: session_id=%s agent_id=%s tags=%s content_len=%s",
            run_context.session_id,
            run_context.agent_id,
            len(tags),
            len(content),
        )
        try:
            memory = self._memory_manager.write_memory(
                content=content,
                tags=tags,
                context=run_context,
                source_event_id=None,
                source="memory_write_tool",
            )
        except ValidationError as exc:
            raise ToolExecutionError(str(exc)) from exc
        payload = {
            "memory_id": memory.memory_id,
            "written_records": 1,
            "storage": "memory",
        }
        return ToolExecutionResult(
            tool_name="memory_write",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class MemorySearchTool:
    """Search memory items by query."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory_manager = memory_manager

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="memory_search",
            description=(
                "Search memory only when relevant memory is not already present in the current context, "
                "or when the user asks to inspect/manage memory. Uses current agent-visible scopes; "
                "other agents are isolated by default."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        query = require_non_empty_argument(arguments, "query")
        limit = parse_limit_argument(arguments, field_name="limit", default=5, max_value=20)
        _, _, bundle = self._memory_manager.search_bundle(
            query=query,
            limit=limit,
            context=run_context,
        )
        hits = bundle.items
        _logger.debug(
            "执行 memory_search: session_id=%s agent_id=%s query=%s hit_count=%s scanned=%s",
            run_context.session_id,
            run_context.agent_id,
            query,
            len(hits),
            bundle.total_scanned,
        )
        payload = [
            {
                "memory_id": item.memory_id,
                "content": item.content,
                "tags": item.tags,
                "scope": item.scope.value,
                "confidence": item.confidence,
            }
            for item in hits
        ]
        return ToolExecutionResult(
            tool_name="memory_search",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class MemoryInspectTool:
    """Inspect current agent-visible memory records with structured schema fields."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory_manager = memory_manager

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="memory_inspect",
            description=(
                "Inspect current agent-visible active memory records with scope, lane, canonical schema fields, "
                "source, timestamps, and status. Use query='*' to list visible memories."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "default": "*"},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                    "include_metadata": {"type": "boolean", "default": True},
                },
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        query = optional_string_argument(arguments, "query", default="*")
        limit = parse_limit_argument(arguments, field_name="limit", default=20, max_value=100)
        include_metadata = parse_bool_argument(arguments, field_name="include_metadata", default=True)

        normalized_query, normalized_limit, bundle = self._memory_manager.search_bundle(
            query=query,
            limit=limit,
            context=run_context,
        )
        records = bundle.items
        payload = {
            "query": normalized_query,
            "limit": normalized_limit,
            "agent_id": run_context.agent_id,
            "session_id": run_context.session_id,
            "count": len(records),
            "searched_scopes": [scope.value for scope in bundle.searched_scopes],
            "total_scanned": bundle.total_scanned,
            "truncated": bundle.truncated,
            "notes": bundle.notes,
            "memories": [serialize_memory_record(record, include_metadata=include_metadata) for record in records],
        }
        return ToolExecutionResult(
            tool_name="memory_inspect",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class MemoryExplainTool:
    """Dry-run memory admission/classification/routing for one content string."""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="memory_explain",
            description=(
                "Explain how a content string would be handled by memory admission, policy routing, "
                "classification, canonicalization, and lane mapping. Dry-run only; does not write memory."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                    },
                    "source": {"type": "string", "default": "memory_explain_tool"},
                },
                "required": ["content"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        content = require_non_empty_argument(arguments, "content")
        tags = normalize_tags(arguments.get("tags", []))
        source = optional_string_argument(arguments, "source", default="memory_explain_tool")
        payload = build_explain_payload(
            context=run_context,
            content=content,
            tags=tags,
            source=source,
        )
        return ToolExecutionResult(
            tool_name="memory_explain",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class MemoryForgetTool:
    """按查询结果删除/遗忘记忆。"""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory_manager = memory_manager

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="memory_forget",
            description=(
                "Forget memory records by query in current agent-visible scopes. "
                "Use this when user explicitly asks to delete/forget previous memory."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                    "hard_delete": {"type": "boolean", "default": False},
                    "reason": {"type": "string"},
                },
                "required": ["query"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        query = require_non_empty_argument(arguments, "query")
        limit = parse_limit_argument(arguments, field_name="limit", default=5, max_value=20)
        hard_delete = parse_bool_argument(arguments, field_name="hard_delete", default=False)
        raw_reason = arguments.get("reason")
        reason = raw_reason.strip() if isinstance(raw_reason, str) and raw_reason.strip() else None

        _, _, bundle = self._memory_manager.search_bundle(
            query=query,
            limit=limit,
            context=run_context,
        )
        hits = bundle.items
        if not hits:
            return ToolExecutionResult(
                tool_name="memory_forget",
                success=True,
                content=json.dumps(
                    {
                        "matched": 0,
                        "forgotten": 0,
                        "deleted": 0,
                        "archived": 0,
                    },
                    ensure_ascii=False,
                ),
            )

        memory_ids = [item.memory_id for item in hits]
        scopes = dedupe_scopes([item.scope for item in hits])
        forget_result = self._memory_manager.forget_memory_ids(
            context=run_context,
            memory_ids=memory_ids,
            scopes=scopes,
            hard_delete=hard_delete,
            reason=reason or f"memory_forget_tool:{query[:80]}",
        )
        payload = {
            "matched": len(hits),
            "memory_ids": memory_ids,
            "scopes": [item.value for item in scopes],
            "forgotten": forget_result.touched_records,
            "deleted": forget_result.deleted_records,
            "archived": forget_result.archived_records,
        }
        return ToolExecutionResult(
            tool_name="memory_forget",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class MemoryUpdateTool:
    """Replace one uniquely matched memory by archiving the old record and writing a new one."""

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory_manager = memory_manager

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="memory_update",
            description=(
                "Update one memory by query. If multiple targets match, return candidates without changing memory."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "new_content": {"type": "string"},
                    "new_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                    },
                    "limit": {"type": "integer", "default": 3, "minimum": 1, "maximum": 8},
                },
                "required": ["query", "new_content"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        query = require_non_empty_argument(arguments, "query")
        new_content = require_non_empty_argument(arguments, "new_content")
        new_tags = normalize_tags(arguments.get("new_tags", []))
        limit = parse_limit_argument(arguments, field_name="limit", default=3, max_value=8)

        hits, match_strategy = self._memory_manager.resolve_update_targets(
            query=query,
            limit=limit,
            context=run_context,
        )
        if not hits:
            return ToolExecutionResult(
                tool_name="memory_update",
                success=True,
                content=json.dumps(build_no_match_update_payload(query=query, match_strategy=match_strategy), ensure_ascii=False),
            )

        if len(hits) > 1:
            return ToolExecutionResult(
                tool_name="memory_update",
                success=True,
                content=json.dumps(build_ambiguous_update_payload(query=query, match_strategy=match_strategy, candidates=hits), ensure_ascii=False),
            )

        target = hits[0]
        resolved_tags = resolve_update_tags(new_tags=new_tags, target_scope=target.scope, target_tags=target.tags)
        admission = evaluate_memory_admission(new_content, resolved_tags)
        if not admission.accepted:
            return ToolExecutionResult(
                tool_name="memory_update",
                success=True,
                content=json.dumps(
                    build_rejected_update_payload(
                        reason=admission.reason,
                        query=query,
                        match_strategy=match_strategy,
                        target=target,
                        resolved_tags=resolved_tags,
                    ),
                    ensure_ascii=False,
                ),
            )
        if not update_allowed_by_source_priority(new_content=new_content, tags=resolved_tags, target=target):
            return ToolExecutionResult(
                tool_name="memory_update",
                success=True,
                content=json.dumps(
                    build_source_priority_conflict_payload(
                        query=query,
                        match_strategy=match_strategy,
                        target=target,
                        resolved_tags=resolved_tags,
                    ),
                    ensure_ascii=False,
                ),
            )
        forget_result = self._memory_manager.forget_memory_ids(
            context=run_context,
            memory_ids=[target.memory_id],
            scopes=[target.scope],
            hard_delete=False,
            reason=f"memory_update_tool:{query[:80]}",
        )
        write_result = self._memory_manager.write_memory_with_result(
            content=new_content,
            tags=resolved_tags,
            context=run_context,
            source_event_id=None,
            source="memory_update_tool",
        )
        if write_result.written_records == 0:
            return ToolExecutionResult(
                tool_name="memory_update",
                success=True,
                content=json.dumps(
                    build_semantic_noop_update_payload(
                        query=query,
                        match_strategy=match_strategy,
                        target=target,
                        resolved_tags=resolved_tags,
                        forget_result=forget_result,
                    ),
                    ensure_ascii=False,
                ),
            )
        payload = build_successful_update_payload(
            match_strategy=match_strategy,
            target=target,
            new_memory_id=write_result.memory.memory_id,
            resolved_tags=resolved_tags,
            forget_result=forget_result,
        )
        return ToolExecutionResult(
            tool_name="memory_update",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )
