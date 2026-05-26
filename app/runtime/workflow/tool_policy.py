"""Tool execution policy and stable input fingerprinting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from app.domain.models import RunContext, ToolCall

__all__ = [
    "ToolExecutionPolicy",
    "canonical_tool_input_hash",
    "resolve_tool_execution_policy",
]

ToolKind = Literal["schema", "read_only", "idempotent_write", "volatile_write", "unknown"]

_SCHEMA_TOOLS = {"tool_search"}
_READ_ONLY_TOOLS = {
    "session_read_artifact",
    "session_list_artifacts",
    "session_plan_artifact_access",
    "session_search_artifact",
    "career_resume_profile_get",
    "career_resume_profile_list",
    "career_profile_get",
    "career_jd_analysis_get",
    "career_jd_analysis_list",
    "career_job_fit_report_get",
    "career_job_fit_report_list",
    "career_application_get",
    "career_application_list",
    "career_resume_version_get",
    "career_resume_version_list",
    "retrieval_search",
    "retrieval_context_pack",
    "agent_task_status",
}
_IDEMPOTENT_WRITE_TOOLS = {
    "delegate_agents",
    "session_create_text_artifact",
    "career_resume_profile_save",
    "career_jd_analysis_save",
    "career_job_fit_report_save",
    "career_application_create",
    "career_application_merge",
    "career_resume_version_create",
}
_VOLATILE_WRITE_TOOLS = {"memory_write"}


@dataclass(frozen=True, slots=True)
class ToolExecutionPolicy:
    tool_name: str
    kind: ToolKind
    cacheable: bool
    idempotent: bool
    input_hash: str | None = None
    idempotency_key: str | None = None


def resolve_tool_execution_policy(
    tool_call: ToolCall,
    context: RunContext,
    *,
    idempotency_key: str | None = None,
) -> ToolExecutionPolicy:
    tool_name = tool_call.name
    kind = _tool_kind(tool_name)
    cacheable = kind == "read_only"
    stable_hash = canonical_tool_input_hash(tool_name, tool_call.arguments) if cacheable else None
    return ToolExecutionPolicy(
        tool_name=tool_name,
        kind=kind,
        cacheable=cacheable,
        idempotent=kind == "idempotent_write" and idempotency_key is not None,
        input_hash=stable_hash,
        idempotency_key=idempotency_key,
    )


def canonical_tool_input_hash(tool_name: str, arguments: dict[str, Any]) -> str:
    payload = {
        "tool_name": tool_name,
        "arguments": _normalize_fingerprint_value(arguments),
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tool_kind(tool_name: str) -> ToolKind:
    if tool_name in _SCHEMA_TOOLS:
        return "schema"
    if tool_name in _READ_ONLY_TOOLS:
        return "read_only"
    if tool_name in _IDEMPOTENT_WRITE_TOOLS:
        return "idempotent_write"
    if tool_name in _VOLATILE_WRITE_TOOLS:
        return "volatile_write"
    return "unknown"


def _normalize_fingerprint_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize_fingerprint_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
            if str(key) not in {"tool_call_id"}
        }
    if isinstance(value, list):
        return [_normalize_fingerprint_value(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if len(stripped) <= 500:
            return stripped
        digest = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
        return {"sha256": digest, "chars": len(stripped)}
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)
