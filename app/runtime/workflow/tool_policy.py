"""Tool execution policy and stable input fingerprinting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.domain.models import RunContext, ToolCall
from app.runtime.tool_capabilities import ToolKind, tool_kind

__all__ = [
    "ToolExecutionPolicy",
    "canonical_tool_input_hash",
    "resolve_tool_execution_policy",
]


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
    kind = tool_kind(tool_name)
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
