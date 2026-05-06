"""Structured model output validation for context compaction."""

from __future__ import annotations

import re
from typing import Any

from app.core.errors import ValidationError
from app.domain.models import EventRecord
from app.runtime.context_compaction.models import SemanticUnit
from app.runtime.context_compaction.text_utils import SUMMARY_MAX_CHARS, optional_text
from app.runtime.memory_signal_guardrails import (
    CorrectionSignal,
    SignalEvent,
    build_correction_signals,
    is_high_signal_tool_result,
    rewrite_superseded_text,
)

__all__ = ["validate_compaction_payload"]


def validate_compaction_payload(payload: dict[str, Any], *, compressed_units: list[SemanticUnit]) -> dict[str, Any]:
    event_index = _build_event_index(compressed_units)
    valid_ids = {event_id for unit in compressed_units for event_id in unit.event_ids}
    source_text = _source_text(compressed_units)
    correction_signals = build_correction_signals(_signal_events_from_units(compressed_units))
    payload = _rewrite_superseded_payload(payload, correction_signals)
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
    timeline = _string_list(payload.get("timeline"), max_items=12)
    decisions = _string_list(payload.get("decisions"), max_items=12)
    decisions = _ensure_correction_lines(decisions, correction_signals)
    memory_relevant = _ensure_correction_lines(memory_relevant, correction_signals)
    tool_progress = _tool_progress_list(payload.get("tool_progress"), event_index)
    tool_progress = _ensure_high_signal_tool_progress(tool_progress, compressed_units)
    normalized = {
        "summary": summary,
        "timeline": timeline[:12],
        "decisions": decisions[:12],
        "open_threads": _string_list(payload.get("open_threads"), max_items=12),
        "tool_progress": tool_progress,
        "agent_activity": _string_list(payload.get("agent_activity"), max_items=12),
        "memory_relevant": memory_relevant[:12],
        "evidence_event_ids": evidence,
    }
    _reject_unsupported_terms(payload=normalized, source_text=source_text)
    return normalized


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
        if not _has_tool_event_evidence(evidence, event_index):
            continue
        _require_tool_pair_evidence(evidence, event_index, field=f"tool_progress[{index}].evidence_event_ids")
        tool_name = _tool_name_from_evidence(evidence, event_index) or tool_name
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
        if not is_high_signal_tool_result(result_text):
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


def _has_tool_event_evidence(evidence: list[str], event_index: dict[str, EventRecord]) -> bool:
    return any((event := event_index.get(event_id)) is not None and event.type in {"tool_call", "tool_result"} for event_id in evidence)


def _tool_name_from_evidence(evidence: list[str], event_index: dict[str, EventRecord]) -> str | None:
    for event_id in evidence:
        event = event_index.get(event_id)
        if event is None or event.type != "tool_call":
            continue
        raw_name = event.payload.get("name")
        if isinstance(raw_name, str) and raw_name.strip():
            return raw_name.strip()
    return None


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
    output_text = _payload_string_values(payload)
    unsupported = sorted(
        {
            *(_ascii_terms(output_text) - _ascii_terms(source_text) - _COMMON_OUTPUT_TERMS),
            *(_name_claims(output_text) - _name_claims(source_text)),
            *(_unsupported_status_phrases(output_text, source_text)),
        }
    )
    if unsupported:
        raise ValidationError(f"compaction output contains unsupported terms: {','.join(unsupported)}")


def _signal_events_from_units(compressed_units: list[SemanticUnit]) -> list[SignalEvent]:
    output: list[SignalEvent] = []
    for unit in compressed_units:
        for event in unit.events:
            output.append(SignalEvent(event_id=event.event_id, event_type=event.type, text=_event_text(event)))
    return output


def _event_text(event: EventRecord) -> str:
    content = event.payload.get("content")
    if isinstance(content, str):
        return content
    result = event.payload.get("result")
    if isinstance(result, str):
        return result
    summary = event.payload.get("summary")
    if isinstance(summary, str):
        return summary
    return ""


def _ensure_correction_lines(lines: list[str], correction_signals: list[CorrectionSignal]) -> list[str]:
    output = list(lines)
    for signal in correction_signals:
        if signal.summary not in output:
            output.append(signal.summary)
        if len(output) >= 12:
            break
    return output[:12]


def _rewrite_superseded_payload(payload: dict[str, Any], correction_signals: list[CorrectionSignal]) -> dict[str, Any]:
    if not correction_signals:
        return payload
    output = dict(payload)
    for key in ("summary",):
        raw = output.get(key)
        if isinstance(raw, str):
            output[key] = rewrite_superseded_text(raw, correction_signals)
    for key in ("timeline", "decisions", "open_threads", "agent_activity", "memory_relevant"):
        raw_list = output.get(key)
        if isinstance(raw_list, list):
            output[key] = [
                rewrite_superseded_text(item, correction_signals) if isinstance(item, str) else item
                for item in raw_list
            ]
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
                    rewritten_item[field] = rewrite_superseded_text(raw, correction_signals)
            rewritten_progress.append(rewritten_item)
        output["tool_progress"] = rewritten_progress
    return output


def _payload_string_values(value: Any) -> str:
    parts: list[str] = []

    def visit(raw: Any) -> None:
        if isinstance(raw, str):
            parts.append(raw)
        elif isinstance(raw, dict):
            for child in raw.values():
                visit(child)
        elif isinstance(raw, list):
            for child in raw:
                visit(child)

    visit(value)
    return "\n".join(parts)


_ASCII_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_./-]{2,}")
_NAME_CLAIM_RE = re.compile(
    r"(?:用户叫|名字是|名字叫|称呼为|叫我)"
    r"(?P<name>[\u4e00-\u9fffA-Za-z0-9_-]{1,24}?)"
    r"(?=$|[\s，,。.!！?？；;、]|才是|是|并|但|且|或|和)"
)
_COMMON_OUTPUT_TERMS = {
    "true",
    "false",
    "string",
    "summary",
    "recent",
    "events",
    "session",
}


def _ascii_terms(text: str) -> set[str]:
    output: set[str] = set()
    for match in _ASCII_TERM_RE.finditer(text):
        term = match.group(0).strip(".,;:!?")
        if term.startswith(("evt_", "call_", "run_", "sess_")):
            continue
        if _is_high_risk_ascii_term(term):
            output.add(term)
    return output


def _is_high_risk_ascii_term(term: str) -> bool:
    if not term:
        return False
    if re.search(r"\.[A-Za-z0-9]{1,8}$", term):
        return True
    if any(char.isdigit() for char in term) and any(char.isalpha() for char in term):
        return True
    if term.isupper() and len(term) >= 2:
        return True
    return False


def _name_claims(text: str) -> set[str]:
    return {match.group("name") for match in _NAME_CLAIM_RE.finditer(text)}


def _unsupported_status_phrases(output_text: str, source_text: str) -> set[str]:
    guarded_status_phrases = {"上线生产", "已经上线", "生产环境"}
    return {phrase for phrase in guarded_status_phrases if phrase in output_text and phrase not in source_text}
