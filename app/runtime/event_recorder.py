"""Event recorder for runtime lifecycle and interactions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.models import EventRecord
from app.domain.protocols import SessionRepository

__all__ = ["EventRecorder"]
_logger = logging.getLogger(__name__)

_ALLOWED_EVENT_TYPES = {
    "run_started",
    "user_message",
    "tool_call",
    "tool_result",
    "assistant_message",
    "memory_write",
    "run_finished",
}


class EventRecorder:
    """Create and append normalized events into session logs."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def record(self, session_id: str, event_type: str, payload: dict[str, Any]) -> EventRecord:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        if not isinstance(event_type, str) or event_type not in _ALLOWED_EVENT_TYPES:
            raise ValidationError(f"Unsupported event type: {event_type}")
        if not isinstance(payload, dict):
            raise ValidationError("payload must be a dictionary.")

        event = EventRecord(
            event_id=f"evt_{uuid4().hex[:12]}",
            session_id=session_id.strip(),
            type=event_type,
            payload=payload,
            created_at=datetime.now(UTC),
        )
        self._session_repository.append_event(session_id.strip(), event)
        _logger.debug("记录事件成功: session_id=%s event_type=%s event_id=%s", session_id, event_type, event.event_id)
        return event
