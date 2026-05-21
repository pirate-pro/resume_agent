"""Event projection helpers used by compaction prompts."""

from __future__ import annotations

from typing import Any

from app.domain.models import EventRecord
from app.runtime.context_compaction.models import CONTEXT_SUMMARY_EVENT
from app.runtime.context_compaction.text_utils import (
    MAX_TOOL_TEXT_LEN,
    SUMMARY_MAX_CHARS,
    compact_json,
    estimate_tokens_from_object,
    format_iso,
    payload_text,
    safe_text,
)

__all__ = [
    "agent_pair_summary",
    "agent_result_summary",
    "agent_task_summary",
    "estimate_tokens_from_events",
    "generic_event_summary",
    "normalize_event_for_prompt",
    "tool_call_summary",
    "tool_pair_summary",
    "tool_result_summary",
]


def normalize_event_for_prompt(event: EventRecord) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_id": event.event_id,
        "type": event.type,
        "agent_id": event.agent_id,
        "run_id": event.run_id,
        "parent_run_id": event.parent_run_id,
        "created_at": format_iso(event.created_at),
    }
    payload = event.payload
    if event.type in {"user_message", "assistant_message", "assistant_thinking"}:
        base["text"] = safe_text(payload.get("content"))
    elif event.type == "tool_call":
        base["tool_name"] = safe_text(payload.get("name"), max_len=120)
        base["tool_call_id"] = payload_text(payload, "tool_call_id")
        base["arguments"] = compact_json(payload.get("arguments"), max_len=MAX_TOOL_TEXT_LEN)
    elif event.type == "tool_result":
        base["tool_name"] = safe_text(payload.get("tool_name"), max_len=120)
        base["tool_call_id"] = payload_text(payload, "tool_call_id")
        base["success"] = bool(payload.get("success"))
        base["result"] = safe_text(payload.get("content"), max_len=MAX_TOOL_TEXT_LEN)
    elif event.type == CONTEXT_SUMMARY_EVENT:
        base["summary"] = safe_text(payload.get("summary") or payload.get("content"), max_len=SUMMARY_MAX_CHARS)
    else:
        base["payload"] = compact_json(payload, max_len=MAX_TOOL_TEXT_LEN)
    return base


def estimate_tokens_from_events(events: list[EventRecord]) -> int:
    return sum(estimate_tokens_from_object(normalize_event_for_prompt(event)) for event in events)


def tool_call_summary(event: EventRecord) -> dict[str, Any]:
    return {
        "tool_name": safe_text(event.payload.get("name"), max_len=120),
        "arguments": compact_json(event.payload.get("arguments"), max_len=MAX_TOOL_TEXT_LEN),
    }


def tool_result_summary(event: EventRecord) -> dict[str, Any]:
    return {
        "tool_name": safe_text(event.payload.get("tool_name"), max_len=120),
        "success": bool(event.payload.get("success")),
        "result": safe_text(event.payload.get("content"), max_len=MAX_TOOL_TEXT_LEN),
    }


def tool_pair_summary(call_event: EventRecord, result_event: EventRecord) -> dict[str, Any]:
    return {
        "tool_name": safe_text(call_event.payload.get("name"), max_len=120)
        or safe_text(result_event.payload.get("tool_name"), max_len=120),
        "call_arguments": compact_json(call_event.payload.get("arguments"), max_len=MAX_TOOL_TEXT_LEN),
        "result_success": bool(result_event.payload.get("success")),
        "result_content": safe_text(result_event.payload.get("content"), max_len=MAX_TOOL_TEXT_LEN),
    }


def agent_task_summary(event: EventRecord) -> dict[str, Any]:
    return {
        "task_id": payload_text(event.payload, "task_id"),
        "source_agent_id": payload_text(event.payload, "source_agent_id"),
        "target_agent_id": payload_text(event.payload, "target_agent_id"),
        "instruction": safe_text(event.payload.get("instruction"), max_len=800),
    }


def agent_result_summary(event: EventRecord) -> dict[str, Any]:
    return {
        "task_id": payload_text(event.payload, "task_id"),
        "source_agent_id": payload_text(event.payload, "source_agent_id"),
        "target_agent_id": payload_text(event.payload, "target_agent_id"),
        "status": payload_text(event.payload, "status"),
        "summary": safe_text(event.payload.get("summary"), max_len=800),
        "artifact_refs": event.payload.get("artifact_refs") or [],
        "output_artifact_refs": event.payload.get("output_artifact_refs") or [],
        "product_refs": event.payload.get("product_refs") or [],
    }


def agent_pair_summary(task_event: EventRecord, result_event: EventRecord) -> dict[str, Any]:
    return {
        "task": agent_task_summary(task_event),
        "result": agent_result_summary(result_event),
    }


def generic_event_summary(event: EventRecord) -> dict[str, Any]:
    return {"type": event.type, "payload": compact_json(event.payload, max_len=MAX_TOOL_TEXT_LEN)}
