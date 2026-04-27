"""Structured classification for accepted memory content."""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "MemoryClassification",
    "classify_memory",
]

_PREFERENCE_TAGS = {"preference", "style", "habit"}
_CONSTRAINT_TAGS = {"constraint", "rule", "policy", "limit"}
_FEEDBACK_TAGS = {"feedback"}
_INTERACTION_TAGS = {"interaction_pattern"}
_VERIFIED_TAGS = {"verified", "tool_verified"}
_INFERRED_TAGS = {"assistant_inferred", "guess", "draft"}

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
    normalized_tags = {tag.strip().lower() for tag in tags if isinstance(tag, str) and tag.strip()}
    lowered = normalized_content.lower()
    source_kind = _infer_source_kind(normalized_tags, source)
    canonical_key, normalized_value = _infer_canonical_key_and_value(normalized_content, lowered)
    kind = _infer_kind(normalized_tags, lowered, canonical_key)
    return MemoryClassification(
        kind=kind,
        source_kind=source_kind,
        canonical_key=canonical_key,
        normalized_value=normalized_value,
    )


def _infer_source_kind(tags: set[str], source: str) -> str:
    normalized_source = source.strip().lower()
    if "system_policy" in tags or normalized_source == "system_policy":
        return "system_policy"
    if "explicit_user_rule" in tags or normalized_source == "explicit_user_rule":
        return "explicit_user_rule"
    if tags.intersection(_VERIFIED_TAGS):
        return "tool_verified"
    if tags.intersection(_INFERRED_TAGS):
        return "assistant_inferred"
    return "explicit_user"


def _infer_kind(tags: set[str], lowered_content: str, canonical_key: str | None) -> str:
    if tags.intersection(_FEEDBACK_TAGS):
        return "feedback_memory"
    if _looks_like_feedback(lowered_content):
        return "feedback_memory"
    if tags.intersection(_INTERACTION_TAGS) or canonical_key == "interaction_style":
        return "interaction_pattern"
    if canonical_key in {"preferred_name", "preferred_language", "response_style", "preferred_format", "disliked_format"}:
        return "user_preference"
    if tags.intersection(_PREFERENCE_TAGS) or tags.intersection(_CONSTRAINT_TAGS):
        return "user_preference"
    return "user_fact"


def _infer_canonical_key_and_value(content: str, lowered_content: str) -> tuple[str | None, str | None]:
    name_value = _extract_preferred_name(content)
    if name_value is not None:
        return "preferred_name", name_value

    if "中文" in content or "汉语" in content:
        return "preferred_language", "zh-CN"
    if "英文" in content or "英语" in content or "english" in lowered_content:
        return "preferred_language", "en"

    if "表格" in content and _contains_any(lowered_content, _NEGATIVE_CUES):
        return "disliked_format", "table"
    if "markdown" in lowered_content and _contains_any(lowered_content, _POSITIVE_CUES):
        return "preferred_format", "markdown"
    if "代码块" in content or "code block" in lowered_content:
        if _contains_any(lowered_content, _POSITIVE_CUES):
            return "preferred_format", "code_block"

    response_style = _infer_response_style(content, lowered_content)
    if response_style is not None:
        return "response_style", response_style

    goal_match = _GOAL_PATTERN.search(content)
    if goal_match:
        return "long_term_goal", _clean_value(goal_match.group(1))

    stack_match = _STACK_PATTERN.search(content)
    if stack_match:
        return "primary_stack", _clean_value(stack_match.group(1)).lower()

    interaction_style = _infer_interaction_style(content, lowered_content)
    if interaction_style is not None:
        return "interaction_style", interaction_style

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


def _looks_like_feedback(lowered_content: str) -> bool:
    return any(token in lowered_content for token in ("不要再", "别再", "以后保持", "这个格式很好", "keep this format"))


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _clean_value(value: str) -> str:
    return value.strip().strip("“”\"'`.,，。!?！？;；:：")
