"""Session-level lock manager for single process runtime."""

from __future__ import annotations

import asyncio
import threading

from app.core.errors import ValidationError

__all__ = ["SessionLockManager"]


class SessionLockManager:
    """Provide one asyncio lock per session ID."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = threading.Lock()

    def get_lock(self, session_id: str) -> asyncio.Lock:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        normalized = session_id.strip()
        with self._guard:
            existing = self._locks.get(normalized)
            if existing is not None:
                return existing
            created = asyncio.Lock()
            self._locks[normalized] = created
            return created
