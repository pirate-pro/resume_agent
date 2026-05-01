"""Built-in session state tools."""

from __future__ import annotations

import json
from datetime import UTC
from typing import Any

from app.core.errors import ToolExecutionError
from app.domain.models import RunContext, ToolDefinition, ToolExecutionResult
from app.state.manager import StateManager
from app.state.models import StateRecord
from app.tools.builtin_tools.common import require_non_empty_argument, validate_context


class StateSetTool:
    """Write agent-private working state for the current session."""

    def __init__(self, state_manager: StateManager) -> None:
        self._state_manager = state_manager

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="state_set",
            description=(
                "Write or update current agent private session state. "
                "Use for current goal, next step, temporary decisions, and working notes "
                "that should persist in this session but are not long-term memory."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        key = require_non_empty_argument(arguments, "key")
        value = require_non_empty_argument(arguments, "value")
        record = self._state_manager.set_agent_state(
            session_id=run_context.session_id,
            agent_id=run_context.agent_id,
            key=key,
            value=value,
            source_run_id=run_context.run_id,
            metadata={"updated_by": "state_set_tool"},
        )
        return ToolExecutionResult(
            tool_name="state_set",
            success=True,
            content=json.dumps(_serialize_state_record(record), ensure_ascii=False),
        )


class StatePublishTool:
    """Publish selected private state records to main orchestration state."""

    def __init__(self, state_manager: StateManager) -> None:
        self._state_manager = state_manager

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="state_publish",
            description=(
                "Publish selected private state keys into main orchestration state. "
                "Use this for session-level progress the main agent should track."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                },
                "required": ["keys"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        raw_keys = arguments.get("keys")
        if not isinstance(raw_keys, list):
            raise ToolExecutionError("'keys' must be an array of strings.")
        keys = _normalize_state_keys(raw_keys)
        published = self._state_manager.publish_agent_state(
            session_id=run_context.session_id,
            agent_id=run_context.agent_id,
            keys=keys,
        )
        payload = {
            "published": len(published),
            "records": [_serialize_state_record(record) for record in published],
        }
        return ToolExecutionResult(
            tool_name="state_publish",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class StateListTool:
    """List private state and main orchestration state visible in the current session."""

    def __init__(self, state_manager: StateManager) -> None:
        self._state_manager = state_manager

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="state_list",
            description=(
                "List current session state. Scope can be 'agent', 'shared', or 'all'. "
                "Private agent state is isolated per agent; shared means main orchestration state."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["agent", "shared", "all"],
                        "default": "all",
                    },
                },
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        scope = _normalize_state_list_scope(arguments.get("scope", "all"))
        agent_records: list[StateRecord] = []
        shared_records: list[StateRecord] = []
        if scope in {"agent", "all"}:
            agent_records = self._state_manager.list_agent_state(
                session_id=run_context.session_id,
                agent_id=run_context.agent_id,
            )
        if scope in {"shared", "all"}:
            shared_records = self._state_manager.list_shared_state(session_id=run_context.session_id)
        payload = {
            "scope": scope,
            "agent_state": [_serialize_state_record(record) for record in agent_records],
            "shared_state": [_serialize_state_record(record) for record in shared_records],
        }
        return ToolExecutionResult(
            tool_name="state_list",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


def _normalize_state_keys(raw_keys: list[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_keys:
        key = str(raw).strip()
        if not key:
            continue
        if key in seen:
            continue
        normalized.append(key)
        seen.add(key)
    if not normalized:
        raise ToolExecutionError("'keys' must contain at least one non-empty string.")
    return normalized


def _normalize_state_list_scope(raw_scope: Any) -> str:
    if not isinstance(raw_scope, str):
        raise ToolExecutionError("'scope' must be one of: agent, shared, all.")
    normalized = raw_scope.strip().lower()
    if normalized not in {"agent", "shared", "all"}:
        raise ToolExecutionError("'scope' must be one of: agent, shared, all.")
    return normalized


def _serialize_state_record(record: StateRecord) -> dict[str, Any]:
    return {
        "state_id": record.state_id,
        "scope": record.scope.value,
        "owner_agent_id": record.owner_agent_id,
        "session_id": record.session_id,
        "key": record.key,
        "value": record.value,
        "status": record.status.value,
        "version": record.version,
        "source_run_id": record.source_run_id,
        "metadata": record.metadata,
        "created_at": record.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "updated_at": record.updated_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }
