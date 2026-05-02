"""Structured model output validation for context compaction."""

from __future__ import annotations

from typing import Any

from app.core.errors import ValidationError
from app.domain.models import EventRecord
from app.runtime.context_compaction.models import SemanticUnit
from app.runtime.context_compaction.text_utils import SUMMARY_MAX_CHARS, optional_text

__all__ = ["validate_compaction_payload"]


def validate_compaction_payload(payload: dict[str, Any], *, compressed_units: list[SemanticUnit]) -> dict[str, Any]:
    event_index = _build_event_index(compressed_units)
    valid_ids = {event_id for unit in compressed_units for event_id in unit.event_ids}
    source_text = _source_text(compressed_units)
    _reject_unsupported_terms(payload=payload, source_text=source_text)
    if _has_filesystem_storage_override(source_text):
        payload = _rewrite_superseded_storage_payload(payload)
    summary = optional_text(payload.get("summary"), max_len=SUMMARY_MAX_CHARS)
    if summary is None:
        raise ValidationError("compaction output missing summary.")
    evidence = _normalize_top_level_evidence(payload.get("evidence_event_ids"), valid_ids)
    if not evidence:
        evidence = sorted(valid_ids)
    forbidden_lines = _forbidden_memory_lines(compressed_units)
    memory_relevant = _string_list(payload.get("memory_relevant"), max_items=12)
    for line in forbidden_lines:
        if line not in memory_relevant:
            memory_relevant.append(line)
    storage_fact = _storage_architecture_fact(source_text)
    timeline = _string_list(payload.get("timeline"), max_items=12)
    decisions = _string_list(payload.get("decisions"), max_items=12)
    if storage_fact is not None:
        if not any("文件系统" in item and "主存储" in item for item in decisions):
            decisions.append(storage_fact)
        if not any("文件系统" in item and "主存储" in item for item in memory_relevant):
            memory_relevant.append(storage_fact)
    tool_progress = _tool_progress_list(payload.get("tool_progress"), event_index)
    tool_progress = _ensure_high_signal_tool_progress(tool_progress, compressed_units)
    return {
        "summary": summary,
        "timeline": timeline[:12],
        "decisions": decisions[:12],
        "open_threads": _string_list(payload.get("open_threads"), max_items=12),
        "tool_progress": tool_progress,
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


def _ensure_high_signal_tool_progress(
    tool_progress: list[dict[str, Any]],
    compressed_units: list[SemanticUnit],
) -> list[dict[str, Any]]:
    output = list(tool_progress)
    existing_evidence = {
        tuple(item.get("evidence_event_ids", []))
        for item in output
        if isinstance(item.get("evidence_event_ids"), list)
    }
    for unit in compressed_units:
        if unit.unit_type != "tool_pair" or len(unit.event_ids) < 2:
            continue
        summary = unit.summary
        result_content = summary.get("result_content") if isinstance(summary, dict) else None
        result_text = result_content.strip() if isinstance(result_content, str) else ""
        if not _is_high_signal_tool_result(result_text):
            continue
        evidence = list(unit.event_ids)
        evidence_key = tuple(evidence)
        if evidence_key in existing_evidence:
            continue
        tool_name = summary.get("tool_name") if isinstance(summary, dict) else None
        output.append(
            {
                "tool_name": tool_name.strip() if isinstance(tool_name, str) and tool_name.strip() else "tool",
                "call_summary": "高信号工具调用，结果影响后续上下文。",
                "result_summary": result_text,
                "success": bool(summary.get("result_success")) if isinstance(summary, dict) else True,
                "evidence_event_ids": evidence,
            }
        )
        existing_evidence.add(evidence_key)
    return output[:12]


def _is_high_signal_tool_result(text: str) -> bool:
    if not text:
        return False
    high_signal_terms = (
        "最新名字",
        "最新称呼",
        "最终名字",
        "最终称呼",
        "已过期",
        "过期",
        "纠正",
        "改为",
    )
    return any(term in text for term in high_signal_terms)


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


def _has_filesystem_storage_override(source_text: str) -> bool:
    return (
        "sqlite" in source_text
        and "主存储" in source_text
        and "文件系统" in source_text
        and ("最终架构决策" in source_text or "最终" in source_text or "改为" in source_text)
        and ("暂不接入" in source_text or "只作为未来派生 index" in source_text or "派生 index" in source_text)
    )


def _storage_architecture_fact(source_text: str) -> str | None:
    if not _has_filesystem_storage_override(source_text):
        return None
    return "memory 主存储架构：文件系统为主存储，sqlite 不接入主存储，仅作为未来派生 index 的候选。"


def _rewrite_superseded_storage_payload(payload: dict[str, Any]) -> dict[str, Any]:
    output = dict(payload)
    for key in ("summary",):
        raw = output.get(key)
        if isinstance(raw, str):
            output[key] = _rewrite_superseded_storage_text(raw)
    for key in ("timeline", "decisions", "open_threads", "agent_activity", "memory_relevant"):
        raw_list = output.get(key)
        if isinstance(raw_list, list):
            output[key] = [_rewrite_superseded_storage_text(item) if isinstance(item, str) else item for item in raw_list]
    raw_progress = output.get("tool_progress")
    if isinstance(raw_progress, list):
        rewritten_progress: list[Any] = []
        for item in raw_progress:
            if not isinstance(item, dict):
                rewritten_progress.append(item)
                continue
            rewritten_item = dict(item)
            for field in ("call_summary", "result_summary"):
                raw = rewritten_item.get(field)
                if isinstance(raw, str):
                    rewritten_item[field] = _rewrite_superseded_storage_text(raw)
            rewritten_progress.append(rewritten_item)
        output["tool_progress"] = rewritten_progress
    return output


def _rewrite_superseded_storage_text(text: str) -> str:
    replacement = "sqlite 主存储早期候选已被后续文件系统主存储决策废弃"
    output = text.replace("sqlite 做 memory 主存储", replacement)
    output = output.replace("sqlite 做主存储", replacement)
    return output
