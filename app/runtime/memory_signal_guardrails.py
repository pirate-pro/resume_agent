"""Generic signal extraction for memory flush and compaction guardrails."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = [
    "CorrectionSignal",
    "SignalEvent",
    "build_correction_signals",
    "candidate_from_correction",
    "is_high_signal_tool_result",
    "rewrite_superseded_text",
]


@dataclass(frozen=True, slots=True)
class SignalEvent:
    event_id: str
    event_type: str
    text: str


@dataclass(frozen=True, slots=True)
class CorrectionSignal:
    event_id: str
    text: str
    summary: str
    superseded_phrases: tuple[str, ...]


_CORRECTION_MARKERS = (
    "最终",
    "改为",
    "改成",
    "不再",
    "不是",
    "为准",
    "覆盖",
    "作废",
    "过期",
    "纠正",
    "替代",
    "废弃",
    "取消",
    "暂不",
    "不接入",
    "只作为",
)
_PROPOSAL_MARKERS = ("先讨论", "候选", "早期", "暂定", "方案")
_STABLE_MARKERS = (
    "最终",
    "以后",
    "长期",
    "必须",
    "不能",
    "不要",
    "偏好",
    "约束",
    "规则",
    "决策",
)
_FORBIDDEN_MEMORY_MARKERS = ("不要记住", "不要写入 memory", "不要写入memory")
_HIGH_SIGNAL_TOOL_RESULT_MARKERS = (
    "最新",
    "最终",
    "为准",
    "已过期",
    "过期",
    "覆盖",
    "作废",
    "纠正",
    "改为",
    "改成",
    "不是",
)
_CLAUSE_SPLIT_RE = re.compile(r"[。.!！?？；;]\s*")
_COLON_RE = re.compile(r"[：:]\s*")
_RECORDED_AS_RE = re.compile(r"已记录(?P<phrase>.+?)作为")


def build_correction_signals(events: list[SignalEvent]) -> list[CorrectionSignal]:
    signals: list[CorrectionSignal] = []
    prior_texts: list[str] = []
    for event in events:
        if event.event_type in {"user_message", "assistant_message", "assistant_thinking"}:
            text = _clean_text(event.text)
            if not text:
                continue
            if event.event_type == "user_message" and _is_correction_text(text):
                superseded = _superseded_phrases(prior_texts)
                signals.append(
                    CorrectionSignal(
                        event_id=event.event_id,
                        text=text,
                        summary=f"后续更正/最终决策：{text}",
                        superseded_phrases=tuple(superseded),
                    )
                )
            prior_texts.append(text)
    return signals


def rewrite_superseded_text(text: str, signals: list[CorrectionSignal]) -> str:
    output = text
    for signal in signals:
        for phrase in signal.superseded_phrases:
            if phrase and phrase in output:
                output = output.replace(phrase, "早期候选内容已被后续更正/最终决策取代")
    return output


def is_high_signal_tool_result(text: str) -> bool:
    normalized = _clean_text(text)
    if not normalized:
        return False
    return any(marker in normalized for marker in _HIGH_SIGNAL_TOOL_RESULT_MARKERS)


def candidate_from_correction(signal: CorrectionSignal) -> dict[str, Any] | None:
    text = _strip_leading_label(signal.text)
    if not text:
        return None
    if any(marker in text for marker in _FORBIDDEN_MEMORY_MARKERS):
        return None
    # Names and direct forms of address are handled by the canonical preference path;
    # a raw correction sentence often contains both old and new values.
    if "名字" in text or "叫我" in text or "称呼" in text:
        return None
    if not any(marker in text for marker in _STABLE_MARKERS):
        return None
    return {
        "content": text,
        "tags": _candidate_tags(text),
        "confidence": 0.82,
        "why_reusable": "用户明确给出后续仍需遵守的更正、偏好、约束或决策。",
        "evidence_event_ids": [signal.event_id],
    }


def _is_correction_text(text: str) -> bool:
    return any(marker in text for marker in _CORRECTION_MARKERS)


def _superseded_phrases(prior_texts: list[str]) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    for text in prior_texts:
        for phrase in _extract_candidate_phrases(text):
            if phrase in seen:
                continue
            seen.add(phrase)
            phrases.append(phrase)
    return phrases


def _extract_candidate_phrases(text: str) -> list[str]:
    output: list[str] = []
    recorded = _RECORDED_AS_RE.search(text)
    if recorded is not None:
        output.extend(_split_candidate_phrase(recorded.group("phrase")))
    if any(marker in text for marker in _PROPOSAL_MARKERS):
        clauses = [part.strip() for part in _CLAUSE_SPLIT_RE.split(text) if part.strip()]
        for clause in clauses:
            if any(marker in clause for marker in _PROPOSAL_MARKERS):
                output.extend(_split_candidate_phrase(clause))
    return _dedupe_phrases(output)


def _split_candidate_phrase(text: str) -> list[str]:
    parts = [part.strip() for part in _COLON_RE.split(text) if part.strip()]
    candidates = parts[-1:] if len(parts) > 1 else parts
    output: list[str] = []
    for candidate in candidates:
        cleaned = _strip_leading_label(candidate)
        cleaned = cleaned.strip(" ，,。.;；")
        if 4 <= len(cleaned) <= 120:
            output.append(cleaned)
    return output


def _strip_leading_label(text: str) -> str:
    stripped = _clean_text(text)
    parts = [part.strip() for part in _COLON_RE.split(stripped, maxsplit=1) if part.strip()]
    return parts[-1] if parts else stripped


def _candidate_tags(text: str) -> list[str]:
    tags = ["long_term", "correction"]
    if "决策" in text or "架构" in text or "方案" in text:
        tags.append("decision")
    if "偏好" in text or "叫我" in text or "称呼" in text:
        tags.append("preference")
    if "必须" in text or "不能" in text or "不要" in text or "约束" in text:
        tags.append("constraint")
    return tags


def _dedupe_phrases(phrases: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        normalized = _clean_text(phrase).strip(" ，,。.;；")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _clean_text(text: str) -> str:
    return " ".join(str(text).strip().split())
