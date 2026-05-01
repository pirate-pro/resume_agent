"""Text, JSON, and token helpers for context compaction."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from typing import Any

from app.core.errors import ValidationError

__all__ = [
    "MAX_TOOL_TEXT_LEN",
    "SUMMARY_MAX_CHARS",
    "compact_json",
    "estimate_tokens_from_object",
    "estimate_tokens_from_text",
    "format_iso",
    "optional_text",
    "parse_json_object",
    "payload_text",
    "safe_text",
]

MAX_TOOL_TEXT_LEN = 1200
SUMMARY_MAX_CHARS = 6000
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def payload_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def parse_json_object(text: str) -> dict[str, Any]:
    if not text:
        raise ValidationError("compaction output is empty.")
    candidates = [text]
    fence_start = text.find("```")
    fence_end = text.rfind("```")
    if fence_start != -1 and fence_end > fence_start:
        fenced = text[fence_start + 3 : fence_end].strip()
        if fenced.lower().startswith("json"):
            fenced = fenced[4:].strip()
        candidates.append(fenced)
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return {str(key): value for key, value in payload.items()}
    raise ValidationError("compaction output is not valid JSON object.")


def estimate_tokens_from_object(value: Any) -> int:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(value)
    return estimate_tokens_from_text(text)


def estimate_tokens_from_text(text: str) -> int:
    if not text:
        return 0
    cjk_count = len(_CJK_PATTERN.findall(text))
    non_cjk_len = max(0, len(text) - cjk_count)
    ascii_token_estimate = (non_cjk_len + 3) // 4
    return max(1, cjk_count + ascii_token_estimate)


def compact_json(raw: Any, *, max_len: int) -> str:
    try:
        text = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(raw)
    return safe_text(text, max_len=max_len) or ""


def safe_text(raw: Any, *, max_len: int = 2000) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def optional_text(raw: Any, *, max_len: int = 2000) -> str | None:
    return safe_text(raw, max_len=max_len)


def format_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
