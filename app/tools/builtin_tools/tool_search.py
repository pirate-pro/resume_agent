"""Built-in tool for discovering available runtime tools."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from app.core.errors import ToolExecutionError
from app.domain.models import RunContext, ToolDefinition, ToolExecutionResult
from app.runtime.tool_catalog import ToolCatalog
from app.runtime.workflow.tool_plan import RuntimeToolPlan
from app.tools.builtin_tools.common import validate_context

__all__ = ["ToolSearchTool"]

_CAREER_PLAN_GROUPS = {
    "career",
    "career_read",
    "career_diagnosis",
    "career_jd_fit",
    "career_resume_version",
    "career_application",
    "delegation",
}
_CAREER_PLAN_KEYWORDS = (
    "career",
    "求职",
    "简历",
    "resume",
    "职业画像",
    "jd",
    "岗位",
    "职位",
    "匹配",
    "投递",
    "申请",
    "application",
    "面试",
    "job fit",
)


class ToolSearchTool:
    """Search the current agent's allowed tool catalog without returning schemas."""

    def __init__(
        self,
        tool_definitions_provider: Callable[[str], Sequence[ToolDefinition]],
        runtime_plan_provider: Callable[[RunContext], RuntimeToolPlan | None] | None = None,
    ) -> None:
        self._tool_definitions_provider = tool_definitions_provider
        self._runtime_plan_provider = runtime_plan_provider

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="tool_search",
            description=(
                "Search the current agent's tool catalog when you need a capability but do not yet know "
                "which concrete tool schema is available. The result lists tool names and descriptions only; "
                "the runtime will reveal matching schemas on the next model round. Search for the final "
                "capability you need, not only the first small lookup step. After a tool name has been revealed, "
                "call that tool directly instead of searching for it again."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Describe the final capability you need, such as retrieving previous records, "
                            "creating a custom resume version, or saving a note."
                        ),
                    },
                    "groups": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional capability groups: artifact, retrieval, career, career_read, "
                            "career_diagnosis, career_jd_fit, career_resume_version, career_application, "
                            "note, learning, memory, delegation."
                        ),
                    },
                    "top_k": {
                        "type": "integer",
                        "default": 8,
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        query = _required_string(arguments.get("query"), field_name="query")
        groups = _optional_string_list(arguments.get("groups"), field_name="groups")
        top_k = _optional_int(arguments.get("top_k"), field_name="top_k", default=8, minimum=1, maximum=20)
        definitions = list(self._tool_definitions_provider(run_context.agent_id))
        catalog = ToolCatalog(definitions)
        result = catalog.search(query=query, groups=groups, top_k=top_k)
        payload = result.to_payload()
        runtime_plan = self._load_runtime_plan(run_context)
        if runtime_plan is not None and _runtime_plan_applies(
            runtime_plan=runtime_plan,
            query=query,
            requested_groups=groups,
            matched_groups=result.matched_groups,
        ):
            payload = _apply_runtime_plan(payload=payload, catalog=catalog, runtime_plan=runtime_plan)
        return ToolExecutionResult(
            tool_name="tool_search",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )

    def _load_runtime_plan(self, context: RunContext) -> RuntimeToolPlan | None:
        if self._runtime_plan_provider is None:
            return None
        plan = self._runtime_plan_provider(context)
        if plan is None or plan.is_empty():
            return None
        return plan


def _runtime_plan_applies(
    *,
    runtime_plan: RuntimeToolPlan,
    query: str,
    requested_groups: list[str],
    matched_groups: list[str],
) -> bool:
    if runtime_plan.phase is None:
        return False
    requested = {item.strip().casefold() for item in requested_groups}
    matched = set(matched_groups)
    if requested.intersection(_CAREER_PLAN_GROUPS) or matched.intersection(_CAREER_PLAN_GROUPS):
        return True
    normalized_query = query.strip().casefold()
    return any(keyword in normalized_query for keyword in _CAREER_PLAN_KEYWORDS)


def _apply_runtime_plan(
    *,
    payload: dict[str, Any],
    catalog: ToolCatalog,
    runtime_plan: RuntimeToolPlan,
) -> dict[str, Any]:
    output = dict(payload)
    output["runtime_plan_applied"] = True
    output["runtime_plan_phase"] = runtime_plan.phase
    output["runtime_next_action"] = runtime_plan.next_action
    output["runtime_next_allowed_tools"] = runtime_plan.next_allowed_tools
    output["runtime_discouraged_tools"] = runtime_plan.discouraged_tools
    output["runtime_final_answer_ready"] = runtime_plan.final_answer_ready
    if runtime_plan.known_refs:
        output["runtime_known_refs"] = runtime_plan.known_refs
    if runtime_plan.missing_outputs:
        output["runtime_missing_outputs"] = runtime_plan.missing_outputs

    if runtime_plan.final_answer_ready:
        output["revealed_tools"] = []
        output["revealed_tool_names"] = []
        output["revealed_tool_count"] = 0
        output["next_step"] = "RuntimeToolPlan 判断关键产物已完成；不要继续 reveal 工具，直接最终答复。"
        output["search_guidance"] = "当前阶段不需要新的工具 schema。"
        return output

    if runtime_plan.next_allowed_tools:
        entries = catalog.entries_for_names(runtime_plan.next_allowed_tools)
        if entries:
            revealed_names = [entry.name for entry in entries]
            output["revealed_tools"] = [
                entry.to_payload(why="RuntimeToolPlan 判断这是当前阶段下一步工具。")
                for entry in entries
            ]
            output["revealed_tool_names"] = revealed_names
            output["revealed_tool_count"] = len(revealed_names)
            unavailable = [
                name for name in runtime_plan.next_allowed_tools if name not in set(revealed_names)
            ]
            if unavailable:
                output["runtime_unavailable_next_allowed_tools"] = unavailable
            output["next_step"] = "下一轮优先直接调用 runtime_next_allowed_tools；不要为同一步继续 tool_search。"
            output["search_guidance"] = "RuntimeToolPlan 已收窄当前阶段工具面。"
    return output


def _required_string(raw: Any, *, field_name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ToolExecutionError(f"'{field_name}' must be a non-empty string.")
    return raw.strip()


def _optional_string_list(raw: Any, *, field_name: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ToolExecutionError(f"'{field_name}' must be a list of strings.")
    output: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ToolExecutionError(f"each '{field_name}' item must be a non-empty string.")
        output.append(item.strip())
    return output


def _optional_int(raw: Any, *, field_name: str, default: int, minimum: int, maximum: int) -> int:
    if raw is None:
        return default
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ToolExecutionError(f"'{field_name}' must be an integer.")
    if raw < minimum or raw > maximum:
        raise ToolExecutionError(f"'{field_name}' must be in range {minimum}..{maximum}.")
    return raw
