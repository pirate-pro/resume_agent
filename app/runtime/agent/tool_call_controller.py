"""Tool-call control decisions before execution reaches the gateway."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import ToolCall
from app.runtime.workflow.action_payloads import (
    build_action_payload_tool_call_from_plan,
    build_required_tool_call_hint_for_plan,
)
from app.runtime.workflow.tool_plan import runtime_plan_completion_tools

__all__ = [
    "MAX_HIDDEN_RUNTIME_TOOL_SUPPRESSIONS_PER_PLAN",
    "ToolCallController",
]

_SCHEMA_SEARCH_TOOL_NAME = "tool_search"
MAX_HIDDEN_RUNTIME_TOOL_SUPPRESSIONS_PER_PLAN = 1
_STRICT_AUTO_EXECUTE_REQUIRED_TOOLS = {
    "career_application_create",
    "career_application_merge",
    "career_job_fit_report_save",
    "career_resume_version_create",
}


@dataclass(slots=True)
class ToolCallController:
    """Normalize and repair model-authored tool calls before execution.

    This first version only moves existing runtime decisions behind a named
    boundary. It intentionally does not add new policy.
    """

    strict_auto_execute_required_tools: set[str] = field(
        default_factory=lambda: set(_STRICT_AUTO_EXECUTE_REQUIRED_TOOLS)
    )

    def strict_required_tool_auto_call(
        self,
        tool_call: ToolCall,
        *,
        pending_runtime_plan: dict[str, Any] | None,
        visible_tool_names_for_round: set[str],
    ) -> ToolCall | None:
        completion_tools = runtime_plan_completion_tools(pending_runtime_plan or {})
        retrieval_context_pack_call = _retrieval_context_pack_auto_call_from_repeated_search(
            tool_call,
            completion_tools=completion_tools,
            visible_tool_names_for_round=visible_tool_names_for_round,
        )
        if retrieval_context_pack_call is not None:
            return retrieval_context_pack_call
        if _is_read_only_probe_tool(tool_call.name) and completion_tools == ["career_application_create"]:
            return None
        return self.strict_required_tool_auto_call_from_plan(
            pending_runtime_plan=pending_runtime_plan,
            visible_tool_names_for_round=visible_tool_names_for_round,
            tool_call_id=tool_call.tool_call_id,
        )

    def strict_required_tool_auto_call_from_plan(
        self,
        *,
        pending_runtime_plan: dict[str, Any] | None,
        visible_tool_names_for_round: set[str],
        tool_call_id: str | None = None,
    ) -> ToolCall | None:
        if pending_runtime_plan is None or pending_runtime_plan.get("final_answer_ready") is True:
            return None
        completion_tools = runtime_plan_completion_tools(pending_runtime_plan)
        if len(completion_tools) != 1:
            return None
        required_tool = completion_tools[0]
        if required_tool not in self.strict_auto_execute_required_tools:
            return None
        if required_tool not in visible_tool_names_for_round:
            return None
        action_call = build_action_payload_tool_call_from_plan(
            pending_runtime_plan=pending_runtime_plan,
            visible_tool_names_for_round=visible_tool_names_for_round,
            tool_call_id=tool_call_id,
        )
        if action_call is not None:
            return action_call
        hint = build_required_tool_call_hint_for_plan(required_tool, pending_runtime_plan)
        if hint is None:
            return None
        if _string_list_from_runtime_plan(hint.get("missing_args")):
            if required_tool != "career_resume_version_create":
                return None
        if required_tool == "career_resume_version_create":
            raw_arguments = _strict_resume_version_create_auto_args(hint)
        else:
            raw_arguments = hint.get("retry_tool_call_skeleton")
            if not isinstance(raw_arguments, dict):
                raw_arguments = hint.get("available_args")
        if not isinstance(raw_arguments, dict) or not raw_arguments:
            return None
        arguments = json.loads(json.dumps(raw_arguments, ensure_ascii=False))
        return ToolCall(name=required_tool, arguments=arguments, tool_call_id=tool_call_id)

    def hidden_runtime_support_tool_allowed(
        self,
        tool_call: ToolCall,
        *,
        pending_runtime_plan: dict[str, Any] | None,
    ) -> bool:
        if pending_runtime_plan is None or pending_runtime_plan.get("final_answer_ready") is True:
            return False
        if tool_call.name != "session_create_text_artifact":
            return False
        phase = pending_runtime_plan.get("phase")
        if phase == "note_write":
            return _note_write_artifact_support_allowed(tool_call, pending_runtime_plan=pending_runtime_plan)
        if phase != "resume_version":
            return False
        if "resume_version" not in _string_list_from_runtime_plan(pending_runtime_plan.get("missing_outputs")):
            return False
        arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
        title = arguments.get("title")
        kind = arguments.get("kind")
        if kind is not None and kind != "generated_file":
            return False
        return isinstance(title, str) and _looks_like_resume_version_artifact_title(title)

    def hidden_runtime_tool_names_to_suppress(
        self,
        tool_calls: list[ToolCall],
        *,
        pending_runtime_plan: dict[str, Any] | None,
        visible_tool_names_for_round: set[str],
        strict_runtime_tool_mode: bool,
    ) -> list[str]:
        if pending_runtime_plan is None or not tool_calls:
            return []
        if not _is_final_answer_ready_runtime_plan(pending_runtime_plan) and not any(
            tool_name in visible_tool_names_for_round for tool_name in runtime_plan_completion_tools(pending_runtime_plan)
        ):
            return []
        blocked: list[str] = []
        for tool_call in tool_calls:
            if tool_call.name in visible_tool_names_for_round:
                return []
            if self.hidden_runtime_support_tool_allowed(tool_call, pending_runtime_plan=pending_runtime_plan):
                return []
            if strict_runtime_tool_mode and self.strict_required_tool_auto_call(
                tool_call,
                pending_runtime_plan=pending_runtime_plan,
                visible_tool_names_for_round=visible_tool_names_for_round,
            ) is not None:
                return []
            blocked.append(tool_call.name)
        output: list[str] = []
        seen: set[str] = set()
        for name in blocked:
            if name in seen:
                continue
            output.append(name)
            seen.add(name)
        return output

    def hidden_runtime_tool_suppression_key(
        self,
        *,
        pending_runtime_plan: dict[str, Any] | None,
        hidden_tool_names: list[str],
    ) -> str:
        raw_refs = pending_runtime_plan.get("known_refs") if pending_runtime_plan is not None else None
        known_refs = raw_refs if isinstance(raw_refs, dict) else {}
        payload = {
            "phase": pending_runtime_plan.get("phase") if pending_runtime_plan is not None else None,
            "required_tools": runtime_plan_completion_tools(pending_runtime_plan or {}),
            "missing_outputs": _string_list_from_runtime_plan(
                pending_runtime_plan.get("missing_outputs") if pending_runtime_plan is not None else None
            ),
            "blocked_tools": hidden_tool_names,
            "known_ref_keys": sorted(str(key) for key in known_refs),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def strict_auto_execute_event_payload(
        self,
        *,
        blocked_tool_call: ToolCall | None,
        replacement_tool_call: ToolCall,
        pending_runtime_plan: dict[str, Any] | None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        resolved_reason = reason or (
            "strict_premature_answer_replaced_with_required_tool"
            if blocked_tool_call is None
            else "strict_hidden_tool_replaced_with_required_tool"
        )
        return {
            "workflow_runtime_result": True,
            "policy": "repair",
            "reason": resolved_reason,
            "strict_runtime_plan": True,
            "tool_executed": True,
            "blocked_tool_name": blocked_tool_call.name if blocked_tool_call is not None else None,
            "tool_name": replacement_tool_call.name,
            "required_tool": replacement_tool_call.name,
            "required_tool_call_hint": build_required_tool_call_hint_for_plan(
                replacement_tool_call.name,
                pending_runtime_plan,
            ),
        }


def _strict_resume_version_create_auto_args(hint: dict[str, Any]) -> dict[str, Any] | None:
    missing_args = _string_list_from_runtime_plan(hint.get("missing_args"))
    blocking_missing_args = [item for item in missing_args if item != "content_or_artifact_id"]
    if blocking_missing_args:
        return None
    available_args = hint.get("available_args")
    if not isinstance(available_args, dict):
        return None
    required_fields = ("base_resume_profile_id", "target_jd_analysis_id", "evidence_refs")
    if any(field not in available_args for field in required_fields):
        return None
    arguments = dict(available_args)
    if _non_empty_string(arguments.get("artifact_id")) is None and _non_empty_string(arguments.get("content")) is None:
        arguments["use_safe_fallback"] = True
    return arguments


def _retrieval_context_pack_auto_call_from_repeated_search(
    tool_call: ToolCall,
    *,
    completion_tools: list[str],
    visible_tool_names_for_round: set[str],
) -> ToolCall | None:
    if completion_tools != ["retrieval_context_pack"]:
        return None
    if "retrieval_context_pack" not in visible_tool_names_for_round:
        return None
    if tool_call.name != "retrieval_search":
        return None
    arguments = _retrieval_context_pack_args_from_search_args(tool_call.arguments)
    if arguments is None:
        return None
    return ToolCall(
        name="retrieval_context_pack",
        arguments=arguments,
        tool_call_id=tool_call.tool_call_id,
    )


def _retrieval_context_pack_args_from_search_args(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    query = _non_empty_string(raw.get("query"))
    if query is None:
        return None
    arguments: dict[str, Any] = {"query": query}
    source_types = _optional_string_list_arg(raw.get("source_types"))
    if source_types:
        arguments["source_types"] = source_types
    related_application_id = _non_empty_string(raw.get("related_application_id"))
    if related_application_id is not None:
        arguments["related_application_id"] = related_application_id
    arguments["top_k"] = _bounded_int_arg(raw.get("top_k"), default=8, minimum=1, maximum=50)
    arguments["max_chars"] = _bounded_int_arg(raw.get("max_chars"), default=12000, minimum=200, maximum=50000)
    arguments["include_archived"] = _bool_arg(raw.get("include_archived"), default=False)
    return arguments


def _optional_string_list_arg(raw: Any) -> list[str]:
    if raw is None:
        return []
    value = raw
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, list):
                value = parsed
            else:
                value = [stripped]
        else:
            value = [stripped]
    if not isinstance(value, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        normalized = item.strip()
        if normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output


def _bounded_int_arg(raw: Any, *, default: int, minimum: int, maximum: int) -> int:
    value: int
    if isinstance(raw, bool):
        value = default
    elif isinstance(raw, int):
        value = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            value = int(raw.strip())
        except ValueError:
            value = default
    else:
        value = default
    return min(max(value, minimum), maximum)


def _bool_arg(raw: Any, *, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "y"}:
            return True
        if normalized in {"0", "false", "no", "n"}:
            return False
    return default


def _looks_like_resume_version_artifact_title(title: str) -> bool:
    normalized = title.strip().casefold()
    compact = "".join(ch for ch in normalized if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    if "简历" in compact and ("诊断" in compact or "画像" in compact):
        return False
    if "简历版本" in compact or "定制简历" in compact:
        return True
    return "resume" in compact and "version" in compact


def _note_write_artifact_support_allowed(
    tool_call: ToolCall,
    *,
    pending_runtime_plan: dict[str, Any] | None,
) -> bool:
    if "note" not in _string_list_from_runtime_plan((pending_runtime_plan or {}).get("missing_outputs")):
        return False
    arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
    title = arguments.get("title")
    content = arguments.get("content")
    kind = arguments.get("kind")
    media_type = arguments.get("media_type")
    if not isinstance(title, str) or not title.strip():
        return False
    if not isinstance(content, str) or not content.strip():
        return False
    if kind is not None and kind not in {"generated_file", "pasted_text"}:
        return False
    if media_type is not None and not isinstance(media_type, str):
        return False
    return True


def _is_read_only_probe_tool(tool_name: str) -> bool:
    name = str(tool_name or "").strip()
    if not name:
        return False
    if name == _SCHEMA_SEARCH_TOOL_NAME:
        return True
    if name.startswith("session_") and (
        name.endswith("_get") or name.endswith("_list") or name in {"session_read_artifact", "session_list_artifacts"}
    ):
        return True
    return name.endswith("_get") or name.endswith("_list")


def _is_final_answer_ready_runtime_plan(pending_runtime_plan: dict[str, Any] | None) -> bool:
    return pending_runtime_plan is not None and pending_runtime_plan.get("final_answer_ready") is True


def _string_list_from_runtime_plan(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            output.append(item.strip())
    return output


def _non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
