"""Structured classification for accepted memory content."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.memory.policies import (
    MemoryCanonicalKey,
    infer_memory_kind,
    infer_source_kind_from_tags,
    normalize_memory_tags,
)

__all__ = [
    "MemoryClassification",
    "classify_memory",
]

_NEGATIVE_CUES = ("不要", "别", "不喜欢", "禁止", "不要再", "别再", "not use", "avoid", "don't")
_POSITIVE_CUES = ("以后", "请用", "保持", "prefer", "use", "请叫", "call me")
_PREFERRED_NAME_PATTERNS = (
    re.compile(
        r"(?:以后)?(?:叫我|称呼我(?:为)?|请叫我|call me)\s*[\"“”']?([^\"“”'\s，。,.!?；;:：]+)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:用户)?(?:称呼|名字|姓名)\s*(?:是|为|改为|改成)\s*[\"“”']?([^\"“”'\s，。,.!?；;:：]+)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:用户)?(?:名字|姓名)\s*(?:叫|叫做)\s*[\"“”']?([^\"“”'\s，。,.!?；;:：]+)",
        flags=re.IGNORECASE,
    ),
)
_GOAL_PATTERN = re.compile(
    r"(?:长期目标(?:是|为)?|long\s*term\s*goal(?:\s+is)?)\s*[:：]?\s*(.+)",
    flags=re.IGNORECASE,
)
_STACK_PATTERN = re.compile(
    r"(?:长期使用|主要使用|常用|主要用)\s*([A-Za-z0-9.+#_-]{2,32})",
    flags=re.IGNORECASE,
)


@dataclass(slots=True)
class MemoryClassification:
    kind: str
    source_kind: str
    canonical_key: str | None = None
    normalized_value: str | None = None
    subject_kind: str = "user"
    classification_version: str = "v1"

    def to_metadata(self) -> dict[str, str]:
        payload = {
            "kind": self.kind,
            "source_kind": self.source_kind,
            "subject_kind": self.subject_kind,
            "classification_version": self.classification_version,
        }
        if self.canonical_key:
            payload["canonical_key"] = self.canonical_key
        if self.normalized_value:
            payload["normalized_value"] = self.normalized_value
        return payload


def classify_memory(content: str, tags: list[str], source: str) -> MemoryClassification:
    normalized_content = content.strip()
    normalized_tags = set(normalize_memory_tags(tags))
    lowered = normalized_content.lower()
    source_kind = infer_source_kind_from_tags(normalized_tags, source)
    canonical_key, normalized_value = _infer_canonical_key_and_value(normalized_content, lowered)
    kind = infer_memory_kind(normalized_tags, lowered, canonical_key)
    return MemoryClassification(
        kind=kind,
        source_kind=source_kind,
        canonical_key=canonical_key,
        normalized_value=normalized_value,
    )


def _infer_canonical_key_and_value(content: str, lowered_content: str) -> tuple[str | None, str | None]:
    name_value = _extract_preferred_name(content)
    if name_value is not None:
        return MemoryCanonicalKey.PREFERRED_NAME.value, name_value

    if "中文" in content or "汉语" in content:
        return MemoryCanonicalKey.PREFERRED_LANGUAGE.value, "zh-CN"
    if "英文" in content or "英语" in content or "english" in lowered_content:
        return MemoryCanonicalKey.PREFERRED_LANGUAGE.value, "en"

    if "表格" in content and _contains_any(lowered_content, _NEGATIVE_CUES):
        return MemoryCanonicalKey.DISLIKED_FORMAT.value, "table"
    if "markdown" in lowered_content and _contains_any(lowered_content, _POSITIVE_CUES):
        return MemoryCanonicalKey.PREFERRED_FORMAT.value, "markdown"
    if "代码块" in content or "code block" in lowered_content:
        if _contains_any(lowered_content, _POSITIVE_CUES):
            return MemoryCanonicalKey.PREFERRED_FORMAT.value, "code_block"

    response_style = _infer_response_style(content, lowered_content)
    if response_style is not None:
        return MemoryCanonicalKey.RESPONSE_STYLE.value, response_style

    goal_match = _GOAL_PATTERN.search(content)
    if goal_match:
        return MemoryCanonicalKey.LONG_TERM_GOAL.value, _clean_value(goal_match.group(1))

    stack_match = _STACK_PATTERN.search(content)
    if stack_match:
        return MemoryCanonicalKey.PRIMARY_STACK.value, _clean_value(stack_match.group(1)).lower()

    interaction_style = _infer_interaction_style(content, lowered_content)
    if interaction_style is not None:
        return MemoryCanonicalKey.INTERACTION_STYLE.value, interaction_style

    return None, None


def _infer_response_style(content: str, lowered_content: str) -> str | None:
    if "简洁" in content or "简短" in content or "concise" in lowered_content:
        return "concise"
    if "详细" in content or "展开" in content or "detailed" in lowered_content:
        return "detailed"
    if "直接" in content or "先结论" in content or "direct" in lowered_content:
        return "direct"
    if "步骤" in content or "step by step" in lowered_content:
        return "stepwise"
    return None


def _infer_interaction_style(content: str, lowered_content: str) -> str | None:
    if "不喜欢铺垫" in content:
        return "no_preamble"
    if "先结论后细节" in content or "先结论再细节" in content:
        return "conclusion_first"
    if "可执行步骤" in content or "actionable steps" in lowered_content:
        return "actionable_steps"
    return None


def _extract_preferred_name(content: str) -> str | None:
    for pattern in _PREFERRED_NAME_PATTERNS:
        match = pattern.search(content)
        if match:
            return _clean_value(match.group(1))
    return None


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _clean_value(value: str) -> str:
    return value.strip().strip("“”\"'`.,，。!?！？;；:：")
