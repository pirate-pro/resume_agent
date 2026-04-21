"""Session orchestration helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.models import EventRecord, SessionMeta
from app.domain.protocols import SessionRepository

__all__ = ["SessionManager"]
_logger = logging.getLogger(__name__)


class SessionManager:
    """Get/create sessions and expose session-local helpers."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def get_or_create_session(self, session_id: str | None) -> SessionMeta:
        if session_id is None or not session_id.strip():
            new_id = f"sess_{uuid4().hex[:12]}"
            _logger.info("创建新会话: session_id=%s", new_id)
            return self._session_repository.create_session(new_id)

        normalized = session_id.strip()
        existing = self._session_repository.get_session(normalized)
        if existing is not None:
            _logger.debug("复用已有会话: session_id=%s", normalized)
            return existing
        _logger.info("会话不存在，自动创建: session_id=%s", normalized)
        return self._session_repository.create_session(normalized)

    def list_recent_events(self, session_id: str, limit: int) -> list[EventRecord]:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        return self._session_repository.list_recent_events(session_id.strip(), limit)

    def get_workspace_path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        return self._session_repository.get_workspace_path(session_id.strip())
