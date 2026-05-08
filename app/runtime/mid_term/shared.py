"""Shared helpers for mid-term memory flushing."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import ValidationError
from app.core.time import from_app_iso, normalize_app_datetime, to_app_iso
from app.domain.models import EventRecord

MAX_LIST_LINES = 8
MAX_TEXT_LEN = 1200
MAX_TOOL_TEXT_LEN = 1600
MIN_INPUT_BUDGET_TOKENS = 512

_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def parse_json_object(text: str) -> dict[str, Any]:
    if not text:
        raise ValidationError("summarizer output is empty.")
    candidates = [text]
    fence_start = text.find("```")
    if fence_start != -1:
        fence_end = text.rfind("```")
        if fence_end > fence_start:
            body = text[fence_start + 3 : fence_end].strip()
            if body.lower().startswith("json"):
                body = body[4:].strip()
            candidates.append(body)
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidates.append(text[first : last + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return {str(k): v for k, v in payload.items()}
    raise ValidationError("summarizer output is not valid JSON object.")


def flush_id_for_pack(pack: Any) -> str:
    return f"{pack.session_id}|{pack.agent_id}|{pack.first_event_id}..{pack.last_event_id}"


def normalize_event_for_pack(event: EventRecord) -> dict[str, Any]:
    payload = event.payload if isinstance(event.payload, dict) else {}
    base: dict[str, Any] = {
        "event_id": event.event_id,
        "type": event.type,
        "created_at": format_iso(event.created_at),
        "run_id": event.run_id,
    }
    if event.type in {"user_message", "assistant_message", "assistant_thinking"}:
        base["text"] = safe_text(payload.get("content"))
        return base
    if event.type == "tool_call":
        base["tool_name"] = safe_text(payload.get("name"), max_len=80)
        base["tool_call_id"] = optional_text(payload.get("tool_call_id"))
        base["arguments"] = compact_json(payload.get("arguments"), max_len=MAX_TOOL_TEXT_LEN)
        return base
    if event.type == "tool_result":
        base["tool_name"] = safe_text(payload.get("tool_name"), max_len=80)
        base["tool_call_id"] = optional_text(payload.get("tool_call_id"))
        base["success"] = bool(payload.get("success"))
        base["result"] = safe_text(payload.get("content"), max_len=MAX_TOOL_TEXT_LEN)
        return base
    if event.type == "memory_write":
        args = payload.get("arguments")
        if isinstance(args, dict):
            base["content"] = safe_text(args.get("content"))
            tags = args.get("tags")
            if isinstance(tags, list):
                base["tags"] = [tag for tag in tags if isinstance(tag, str) and tag.strip()]
        return base
    if event.type == "run_finished":
        base["answer_length"] = payload.get("answer_length")
        base["tool_calls"] = payload.get("tool_calls")
        return base
    base["payload"] = compact_json(payload, max_len=MAX_TOOL_TEXT_LEN)
    return base


def tool_call_id(payload: dict[str, Any]) -> str | None:
    raw = payload.get("tool_call_id")
    return optional_text(raw)


def normalize_evidence(raw: Any, valid_event_ids: set[str]) -> list[str]:
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        event_id = item.strip()
        if not event_id or event_id in seen:
            continue
        if event_id not in valid_event_ids:
            continue
        seen.add(event_id)
        output.append(event_id)
    return output


def normalize_score(raw: Any, *, default: float) -> float:
    if isinstance(raw, (int, float)):
        value = float(raw)
        if 0 <= value <= 1:
            return round(value, 3)
    return default


def safe_text(raw: Any, *, max_len: int = MAX_TEXT_LEN) -> str:
    if raw is None:
        return ""
    text = str(raw).strip().replace("\n", " ")
    if not text:
        return ""
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def compact_json(raw: Any, *, max_len: int = MAX_TOOL_TEXT_LEN) -> str:
    try:
        text = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(raw)
    return safe_text(text, max_len=max_len)


def estimate_tokens_from_text(text: str) -> int:
    if not text:
        return 0
    cjk_count = len(_CJK_PATTERN.findall(text))
    non_cjk_len = max(0, len(text) - cjk_count)
    ascii_token_estimate = (non_cjk_len + 3) // 4
    return max(1, cjk_count + ascii_token_estimate)


def estimate_tokens_from_object(value: Any) -> int:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(value)
    return estimate_tokens_from_text(text)


def require_non_empty(field_name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def require_positive_int(field_name: str, value: Any) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValidationError(f"{field_name} must be a positive integer.")
    return value


def require_non_negative_int(field_name: str, value: Any) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValidationError(f"{field_name} must be a non-negative integer.")
    return value


def optional_text(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    return text or None


def parse_iso_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = from_app_iso(raw)
    except ValueError:
        return None
    return normalize_app_datetime(value)


def format_iso(value: datetime) -> str:
    return to_app_iso(value.replace(microsecond=0))


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValidationError(f"json object expected: {path}")
    return {str(k): v for k, v in payload.items()}


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)
