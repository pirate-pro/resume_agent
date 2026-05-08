"""Shared JSON and time helpers for session storage."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import StorageError
from app.core.time import app_now, from_app_iso, to_app_iso

__all__ = [
    "from_iso",
    "to_iso",
    "utc_now",
    "write_json_atomically",
]


def utc_now() -> datetime:
    return app_now()


def to_iso(value: datetime) -> str:
    return to_app_iso(value)


def from_iso(value: str) -> datetime:
    return from_app_iso(value)


def write_json_atomically(path: Path, payload: dict[str, Any], *, error_prefix: str) -> None:
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)
    except OSError as exc:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise StorageError(f"{error_prefix}: {exc}") from exc
