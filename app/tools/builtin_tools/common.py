"""Common helpers for built-in tools."""

from __future__ import annotations

from typing import Any

from app.core.errors import ToolExecutionError, ValidationError
from app.domain.models import RunContext


def validate_context(context: RunContext) -> RunContext:
    if not isinstance(context, RunContext):
        raise ValidationError("context must be RunContext.")
    return context


def require_non_empty_argument(arguments: dict[str, Any], key: str) -> str:
    if not isinstance(arguments, dict):
        raise ToolExecutionError("Tool arguments must be an object.")
    raw_value = arguments.get(key)
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ToolExecutionError(f"'{key}' must be a non-empty string.")
    return raw_value.strip()


def optional_string_argument(arguments: dict[str, Any], key: str, *, default: str) -> str:
    if not isinstance(arguments, dict):
        raise ToolExecutionError("Tool arguments must be an object.")
    raw_value = arguments.get(key, default)
    if raw_value is None:
        return default
    if not isinstance(raw_value, str):
        raise ToolExecutionError(f"'{key}' must be a string.")
    normalized = raw_value.strip()
    return normalized or default


def normalize_tags(raw_tags: Any) -> list[str]:
    if raw_tags is None:
        return []
    if not isinstance(raw_tags, list):
        raise ToolExecutionError("'tags' must be a list of strings.")
    normalized: list[str] = []
    for tag in raw_tags:
        if not isinstance(tag, str) or not tag.strip():
            raise ToolExecutionError("each tag must be a non-empty string.")
        normalized.append(tag.strip())
    return normalized


def parse_non_negative_int(raw: Any, field_name: str) -> int:
    if not isinstance(raw, int) or raw < 0:
        raise ToolExecutionError(f"'{field_name}' must be a non-negative integer.")
    return raw


def parse_positive_int(raw: Any, field_name: str) -> int:
    if not isinstance(raw, int) or raw <= 0:
        raise ToolExecutionError(f"'{field_name}' must be a positive integer.")
    return raw
