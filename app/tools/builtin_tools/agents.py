"""Built-in tools for controlled multi-agent delegation."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.core.errors import ToolExecutionError, ValidationError
from app.domain.models import RunContext, ToolDefinition, ToolExecutionResult
from app.services.agent_task_runtime import AgentTaskGroupRequest, AgentTaskRuntime, AgentTaskSpec
from app.tools.builtin_tools.common import parse_positive_int, validate_context

__all__ = ["DelegateAgentsTool"]


class DelegateAgentsTool:
    """Delegate independent child-agent tasks and wait for aggregated results."""

    def __init__(self, agent_task_runtime_provider: Callable[[], AgentTaskRuntime]) -> None:
        self._agent_task_runtime_provider = agent_task_runtime_provider

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="delegate_agents",
            description=(
                "Delegate independent subtasks to registered child agents concurrently and wait for their results. "
                "Use only when the subtasks are logically independent."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "properties": {
                                "target_agent_id": {"type": "string"},
                                "instruction": {"type": "string"},
                                "constraints": {"type": "array", "items": {"type": "string"}},
                                "artifact_refs": {"type": "array", "items": {"type": "string"}},
                                "skill_names": {"type": "array", "items": {"type": "string"}},
                                "max_tool_rounds": {"type": "integer", "minimum": 0, "maximum": 10},
                                "depends_on": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["target_agent_id", "instruction"],
                        },
                    },
                    "wait": {
                        "type": "boolean",
                        "default": True,
                        "description": "Only true is supported in this version.",
                    },
                    "max_concurrency": {"type": "integer", "default": 3, "minimum": 1, "maximum": 8},
                },
                "required": ["tasks"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        if not isinstance(arguments, dict):
            raise ToolExecutionError("Tool arguments must be an object.")
        wait = _parse_wait(arguments.get("wait", True))
        if not wait:
            raise ToolExecutionError("delegate_agents currently supports wait=true only.")
        max_concurrency = min(parse_positive_int(arguments.get("max_concurrency", 3), "max_concurrency"), 8)
        specs = _parse_task_specs(arguments.get("tasks"))
        try:
            result = self._agent_task_runtime_provider().run_group(
                AgentTaskGroupRequest(
                    source_context=run_context,
                    tasks=specs,
                    wait=True,
                    max_concurrency=max_concurrency,
                )
            )
        except ValidationError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return ToolExecutionResult(
            tool_name="delegate_agents",
            success=True,
            content=json.dumps(result.to_payload(), ensure_ascii=False),
        )


def _parse_wait(raw: Any) -> bool:
    if not isinstance(raw, bool):
        raise ToolExecutionError("'wait' must be a boolean.")
    return raw


def _parse_task_specs(raw: Any) -> list[AgentTaskSpec]:
    if not isinstance(raw, list) or not raw:
        raise ToolExecutionError("'tasks' must be a non-empty list.")
    if len(raw) > 8:
        raise ToolExecutionError("'tasks' cannot exceed 8 items.")
    specs: list[AgentTaskSpec] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ToolExecutionError("each task must be an object.")
        depends_on = _optional_string_list(item.get("depends_on"), field_name="depends_on")
        if depends_on:
            raise ToolExecutionError("'depends_on' is reserved for later; only independent tasks are supported now.")
        try:
            specs.append(
                AgentTaskSpec(
                    target_agent_id=_required_string(item.get("target_agent_id"), field_name="target_agent_id"),
                    instruction=_required_string(item.get("instruction"), field_name="instruction"),
                    constraints=_optional_string_list(item.get("constraints"), field_name="constraints"),
                    artifact_refs=_optional_string_list(item.get("artifact_refs"), field_name="artifact_refs"),
                    skill_names=_optional_string_list(
                        item.get("skill_names"),
                        field_name="skill_names",
                        default=["base", "tools", "file-reader"],
                    ),
                    max_tool_rounds=_parse_max_tool_rounds(item.get("max_tool_rounds", 2)),
                    depends_on=[],
                )
            )
        except ValidationError as exc:
            raise ToolExecutionError(str(exc)) from exc
    return specs


def _required_string(raw: Any, *, field_name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ToolExecutionError(f"'{field_name}' must be a non-empty string.")
    return raw.strip()


def _optional_string_list(
    raw: Any,
    *,
    field_name: str,
    default: list[str] | None = None,
) -> list[str]:
    if raw is None:
        return list(default or [])
    if not isinstance(raw, list):
        raise ToolExecutionError(f"'{field_name}' must be a list of strings.")
    output: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ToolExecutionError(f"each '{field_name}' item must be a non-empty string.")
        output.append(item.strip())
    return output


def _parse_max_tool_rounds(raw: Any) -> int:
    if not isinstance(raw, int) or raw < 0 or raw > 10:
        raise ToolExecutionError("'max_tool_rounds' must be an integer in range 0..10.")
    return raw
