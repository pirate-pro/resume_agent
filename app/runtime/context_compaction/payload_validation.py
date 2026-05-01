"""Structured model output validation for context compaction."""

from __future__ import annotations

from typing import Any

from app.core.errors import ValidationError
from app.runtime.context_compaction.models import SemanticUnit
from app.runtime.context_compaction.text_utils import SUMMARY_MAX_CHARS, optional_text

__all__ = ["validate_compaction_payload"]


def validate_compaction_payload(payload: dict[str, Any], *, compressed_units: list[SemanticUnit]) -> dict[str, Any]:
    summary = optional_text(payload.get("summary"), max_len=SUMMARY_MAX_CHARS)
    if summary is None:
        raise ValidationError("compaction output missing summary.")
    valid_ids = {event_id for unit in compressed_units for event_id in unit.event_ids}
    evidence = _normalize_event_ids(payload.get("evidence_event_ids"), valid_ids)
    if not evidence:
        evidence = sorted(valid_ids)
    return {
        "summary": summary,
        "timeline": _string_list(payload.get("timeline"), max_items=12),
        "decisions": _string_list(payload.get("decisions"), max_items=12),
        "open_threads": _string_list(payload.get("open_threads"), max_items=12),
        "tool_progress": _tool_progress_list(payload.get("tool_progress"), valid_ids),
        "agent_activity": _string_list(payload.get("agent_activity"), max_items=12),
        "memory_relevant": _string_list(payload.get("memory_relevant"), max_items=12),
        "evidence_event_ids": evidence,
    }


def _tool_progress_list(raw: Any, valid_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    output: list[dict[str, Any]] = []
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        tool_name = optional_text(item.get("tool_name"), max_len=120)
        call_summary = optional_text(item.get("call_summary"), max_len=400)
        result_summary = optional_text(item.get("result_summary"), max_len=500)
        evidence = _normalize_event_ids(item.get("evidence_event_ids"), valid_ids)
        if tool_name is None or call_summary is None or result_summary is None or not evidence:
            continue
        output.append(
            {
                "tool_name": tool_name,
                "call_summary": call_summary,
                "result_summary": result_summary,
                "success": bool(item.get("success")),
                "evidence_event_ids": evidence,
            }
        )
    return output


def _string_list(raw: Any, *, max_items: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    for item in raw[:max_items]:
        text = optional_text(item, max_len=600)
        if text is not None:
            output.append(text)
    return output


def _normalize_event_ids(raw: Any, valid_ids: set[str]) -> list[str]:
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        event_id = item.strip()
        if not event_id or event_id not in valid_ids or event_id in seen:
            continue
        output.append(event_id)
        seen.add(event_id)
    return output
