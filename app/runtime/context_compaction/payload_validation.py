"""Structured model output validation for context compaction."""

from __future__ import annotations

from typing import Any

from app.core.errors import ValidationError
from app.domain.models import EventRecord
from app.runtime.context_compaction.models import SemanticUnit
from app.runtime.context_compaction.text_utils import SUMMARY_MAX_CHARS, optional_text

__all__ = ["validate_compaction_payload"]


def validate_compaction_payload(payload: dict[str, Any], *, compressed_units: list[SemanticUnit]) -> dict[str, Any]:
    summary = optional_text(payload.get("summary"), max_len=SUMMARY_MAX_CHARS)
    if summary is None:
        raise ValidationError("compaction output missing summary.")
    event_index = _build_event_index(compressed_units)
    valid_ids = {event_id for unit in compressed_units for event_id in unit.event_ids}
    source_text = _source_text(compressed_units)
    _reject_unsupported_terms(payload=payload, source_text=source_text)
    evidence = _normalize_top_level_evidence(payload.get("evidence_event_ids"), valid_ids)
    if not evidence:
        evidence = sorted(valid_ids)
    forbidden_lines = _forbidden_memory_lines(compressed_units)
    memory_relevant = _string_list(payload.get("memory_relevant"), max_items=12)
    for line in forbidden_lines:
        if line not in memory_relevant:
            memory_relevant.append(line)
    return {
        "summary": summary,
        "timeline": _string_list(payload.get("timeline"), max_items=12),
        "decisions": _string_list(payload.get("decisions"), max_items=12),
        "open_threads": _string_list(payload.get("open_threads"), max_items=12),
        "tool_progress": _tool_progress_list(payload.get("tool_progress"), event_index),
        "agent_activity": _string_list(payload.get("agent_activity"), max_items=12),
        "memory_relevant": memory_relevant[:12],
        "evidence_event_ids": evidence,
    }


def _tool_progress_list(raw: Any, event_index: dict[str, EventRecord]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    valid_ids = set(event_index)
    output: list[dict[str, Any]] = []
    for index, item in enumerate(raw[:12]):
        if not isinstance(item, dict):
            continue
        tool_name = optional_text(item.get("tool_name"), max_len=120)
        call_summary = optional_text(item.get("call_summary"), max_len=400)
        result_summary = optional_text(item.get("result_summary"), max_len=500)
        evidence = _normalize_required_event_ids(
            item.get("evidence_event_ids"),
            valid_ids,
            field=f"tool_progress[{index}].evidence_event_ids",
        )
        if tool_name is None or call_summary is None or result_summary is None or not evidence:
            continue
        _require_tool_pair_evidence(evidence, event_index, field=f"tool_progress[{index}].evidence_event_ids")
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


def _normalize_optional_event_ids(raw: Any, valid_ids: set[str], *, field: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError(f"{field} must be list.")
    return _normalize_event_ids(raw, valid_ids, field=field, require_non_empty=False)


def _normalize_top_level_evidence(raw: Any, valid_ids: set[str]) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError("evidence_event_ids must be list.")
    output: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        event_id = item.strip()
        if not event_id or event_id in seen or event_id not in valid_ids:
            continue
        output.append(event_id)
        seen.add(event_id)
    return output


def _normalize_required_event_ids(raw: Any, valid_ids: set[str], *, field: str) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise ValidationError(f"{field} must contain at least one valid event id.")
    return _normalize_event_ids(raw, valid_ids, field=field, require_non_empty=True)


def _normalize_event_ids(
    raw: list[Any],
    valid_ids: set[str],
    *,
    field: str,
    require_non_empty: bool,
) -> list[str]:
    raw_ids = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
    if require_non_empty and not raw_ids:
        raise ValidationError(f"{field} must contain at least one valid event id.")
    invalid = sorted({event_id for event_id in raw_ids if event_id not in valid_ids})
    if invalid:
        raise ValidationError(f"{field} contains invalid event ids: {','.join(invalid)}")
    if not raw_ids:
        return []
    output: list[str] = []
    seen: set[str] = set()
    for event_id in raw_ids:
        if event_id in seen:
            continue
        output.append(event_id)
        seen.add(event_id)
    return output


def _build_event_index(compressed_units: list[SemanticUnit]) -> dict[str, EventRecord]:
    output: dict[str, EventRecord] = {}
    for unit in compressed_units:
        for event in unit.events:
            output[event.event_id] = event
    return output


def _require_tool_pair_evidence(evidence: list[str], event_index: dict[str, EventRecord], *, field: str) -> None:
    observed: dict[str, set[str]] = {}
    for event_id in evidence:
        event = event_index.get(event_id)
        if event is None or event.type not in {"tool_call", "tool_result"}:
            continue
        raw_call_id = event.payload.get("tool_call_id")
        call_id = raw_call_id.strip() if isinstance(raw_call_id, str) else ""
        if not call_id:
            raise ValidationError(f"{field} references tool event without tool_call_id: {event_id}")
        observed.setdefault(call_id, set()).add(event.type)
    for call_id, types in observed.items():
        if types != {"tool_call", "tool_result"}:
            raise ValidationError(f"{field} must include paired tool_call/tool_result for {call_id}.")


def _source_text(compressed_units: list[SemanticUnit]) -> str:
    parts: list[str] = []
    for unit in compressed_units:
        parts.append(str(unit.summary))
        for event in unit.events:
            parts.append(str(event.payload))
    return "\n".join(parts)


def _forbidden_memory_lines(compressed_units: list[SemanticUnit]) -> list[str]:
    output: list[str] = []
    for unit in compressed_units:
        for event in unit.events:
            if event.type != "user_message":
                continue
            content = event.payload.get("content")
            if not isinstance(content, str):
                continue
            if "不要记住" not in content and "不要写入 memory" not in content and "不要写入memory" not in content:
                continue
            output.append(f"用户明确声明该临时上下文不要记住/不要写入长期 memory：{content[:240]}")
    return output


def _reject_unsupported_terms(*, payload: dict[str, Any], source_text: str) -> None:
    output_text = str(payload)
    guarded_terms = (
        "小猪",
        "小明",
        "小王",
        "张三",
        "火星",
        "Redis 缓存",
        "已经上线生产",
        "sqlite",
        "文件系统",
        "MEMORY_DEV_PROGRESS.md",
        "蓝鲸",
    )
    unsupported = sorted({term for term in guarded_terms if term in output_text and term not in source_text})
    if unsupported:
        raise ValidationError(f"compaction output contains unsupported terms: {','.join(unsupported)}")
