"""Common constants and validators for file-backed memory storage."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.core.errors import ValidationError
from app.core.time import from_app_iso, normalize_app_datetime
from app.memory.models import MemoryScope

SCHEMA_VERSION = "1.0"
MID_TERM_DAILY_LIMIT = 6
MID_TERM_MAX_CHARS = 2400

LONG_TERM_SECTIONS = (
    ("user", "workContext", "User work context"),
    ("user", "personalContext", "User personal context"),
    ("user", "topOfMind", "User top of mind"),
    ("history", "recentMonths", "Recent months"),
    ("history", "earlierContext", "Earlier context"),
    ("history", "longTermBackground", "Long-term background"),
)


def empty_long_term_payload(*, scope: str, agent_id: str | None, now: str) -> dict[str, Any]:
    def section() -> dict[str, Any]:
        return {"summary": "", "updatedAt": None}

    return {
        "version": SCHEMA_VERSION,
        "scope": scope,
        "ownerAgentId": agent_id,
        "lastUpdated": now,
        "user": {
            "workContext": section(),
            "personalContext": section(),
            "topOfMind": section(),
        },
        "history": {
            "recentMonths": section(),
            "earlierContext": section(),
            "longTermBackground": section(),
        },
    }


def set_long_term_section(
    payload: dict[str, Any],
    *,
    group: str,
    key: str,
    summary: str,
    refreshed_at: str,
) -> None:
    group_obj = payload.get(group)
    if not isinstance(group_obj, dict):
        group_obj = {}
        payload[group] = group_obj
    section_obj = group_obj.get(key)
    if not isinstance(section_obj, dict):
        section_obj = {}
        group_obj[key] = section_obj
    section_obj["summary"] = summary
    section_obj["updatedAt"] = refreshed_at


def to_memory_scope(*, scope: MemoryScope, owner_agent_id: str | None) -> tuple[str, str | None]:
    if scope == MemoryScope.SHARED_LONG:
        return "shared", None
    if scope in {MemoryScope.AGENT_LONG, MemoryScope.AGENT_SHORT}:
        return "agent", require_non_empty("owner_agent_id", owner_agent_id or "")
    raise ValidationError(f"Unsupported memory scope: {scope.value}")


def long_term_record_id(*, scope: str, agent_id: str | None, group: str, key: str) -> str:
    base = f"{scope}_{agent_id or 'shared'}_{group}_{key}"
    return "long_" + stable_id(base)


def mid_term_record_id(*, scope: str, agent_id: str | None, path: Path) -> str:
    base = f"{scope}_{agent_id or 'shared'}_{path.as_posix()}"
    return "mid_" + stable_id(base)


def stable_id(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:16]


def clip_text(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 24].rstrip() + "\n...[truncated]"


def parse_optional_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = from_app_iso(value)
    except ValueError:
        return None
    return normalize_datetime(parsed)


def normalize_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationError("datetime value must be datetime.")
    return normalize_app_datetime(value)


def require_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def normalize_limit(limit: int) -> int:
    if not isinstance(limit, int) or limit <= 0:
        raise ValidationError("limit must be positive integer.")
    return limit


def normalize_memory_ids(memory_ids: list[str]) -> set[str]:
    if not isinstance(memory_ids, list) or not memory_ids:
        raise ValidationError("memory_ids must be non-empty list.")
    output: set[str] = set()
    for raw in memory_ids:
        if not isinstance(raw, str) or not raw.strip():
            raise ValidationError("memory_ids entries must be non-empty strings.")
        output.add(raw.strip())
    return output
