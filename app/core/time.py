"""Application time helpers."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

__all__ = [
    "APP_TIMEZONE",
    "app_now",
    "from_app_iso",
    "normalize_app_datetime",
    "to_app_iso",
]

APP_TIMEZONE = ZoneInfo("Asia/Shanghai")


def app_now() -> datetime:
    """Return the current application time in Asia/Shanghai."""

    return datetime.now(APP_TIMEZONE)


def normalize_app_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("value must be datetime.")
    if value.tzinfo is None:
        value = value.replace(tzinfo=APP_TIMEZONE)
    return value.astimezone(APP_TIMEZONE)


def to_app_iso(value: datetime) -> str:
    return normalize_app_datetime(value).isoformat()


def from_app_iso(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    return normalize_app_datetime(parsed)
