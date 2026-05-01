"""Session metadata, events, and message query use cases."""

from __future__ import annotations

import asyncio
import logging

from app.core.errors import SessionNotFoundError, ValidationError
from app.domain.models import EventRecord, SessionMeta, ToolCall
from app.domain.protocols import SessionRepository
from app.infra.locks.session_lock_manager import SessionLockManager
from app.schemas.chat import SessionUpdateRequest
from app.services.answer_normalizer import AnswerArtifact, AnswerNormalizer

__all__ = ["SessionQueryService"]

_logger = logging.getLogger(__name__)


class SessionQueryService:
    """Handle session metadata and history read/update operations."""

    def __init__(
        self,
        session_repository: SessionRepository,
        session_lock_manager: SessionLockManager,
        answer_normalizer: AnswerNormalizer,
    ) -> None:
        self._session_repository = session_repository
        self._session_lock_manager = session_lock_manager
        self._answer_normalizer = answer_normalizer

    def list_sessions(self) -> list[SessionMeta]:
        return self._session_repository.list_sessions()

    async def update_session(self, session_id: str, request: SessionUpdateRequest) -> SessionMeta:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        if not isinstance(request, SessionUpdateRequest):
            raise ValidationError("request must be SessionUpdateRequest.")
        if request.title is None and request.is_pinned is None:
            raise ValidationError("At least one of title/is_pinned must be provided.")

        normalized = session_id.strip()
        lock = self._session_lock_manager.get_lock(normalized)
        async with lock:
            current = self._session_repository.get_session(normalized)
            if current is None:
                raise SessionNotFoundError(f"Session not found: {normalized}")
            updated = current
            if request.title is not None and request.title != updated.title:
                updated = self._session_repository.update_session_title(normalized, request.title)
            if request.is_pinned is not None and request.is_pinned != updated.is_pinned:
                updated = self._session_repository.update_session_pin(normalized, request.is_pinned)
        _logger.info(
            "会话元数据更新完成: session_id=%s title=%s is_pinned=%s",
            updated.session_id,
            updated.title,
            updated.is_pinned,
        )
        return updated

    def list_session_messages(self, session_id: str) -> list[dict[str, object]]:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        normalized_session_id = session_id.strip()
        events = self._session_repository.list_events(normalized_session_id)
        messages: list[dict[str, object]] = []
        pending_tool_calls: list[dict[str, object]] = []

        for event in events:
            payload = event.payload if isinstance(event.payload, dict) else {}
            if event.type == "user_message":
                pending_tool_calls = []
                normalized = self._answer_normalizer.normalize_user_message(str(payload.get("content", "")))
                messages.append(
                    {
                        "role": "user",
                        "content": normalized.content,
                        "answer_format": normalized.answer_format,
                        "render_hint": normalized.render_hint,
                        "layout_hint": normalized.layout_hint,
                        "source_kind": normalized.source_kind,
                        "artifacts": [_artifact_to_payload(item) for item in normalized.artifacts],
                        "tool_calls": [],
                        "created_at": event.created_at,
                    }
                )
                continue

            if event.type == "tool_call":
                tool_name = str(payload.get("name", "")).strip()
                arguments = payload.get("arguments", {})
                if tool_name and isinstance(arguments, dict):
                    pending_tool_calls.append(
                        {
                            "name": tool_name,
                            "arguments": arguments,
                        }
                    )
                continue

            if event.type == "assistant_message":
                tool_calls = _payload_tool_calls_to_domain(pending_tool_calls)
                normalized = self._answer_normalizer.normalize_assistant_message(
                    str(payload.get("content", "")),
                    tool_calls=tool_calls,
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": normalized.content,
                        "answer_format": normalized.answer_format,
                        "render_hint": normalized.render_hint,
                        "layout_hint": normalized.layout_hint,
                        "source_kind": normalized.source_kind,
                        "artifacts": [_artifact_to_payload(item) for item in normalized.artifacts],
                        "tool_calls": pending_tool_calls,
                        "created_at": event.created_at,
                    }
                )
                pending_tool_calls = []

        return messages

    def list_session_events(self, session_id: str) -> list[EventRecord]:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        normalized = session_id.strip()
        events = self._session_repository.list_events(normalized)
        _logger.debug("读取会话事件: session_id=%s event_count=%s", normalized, len(events))
        return events

    async def delete_session(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        normalized = session_id.strip()
        lock = self._session_lock_manager.get_lock(normalized)
        async with lock:
            await asyncio.to_thread(self._session_repository.delete_session, normalized)


def _artifact_to_payload(item: AnswerArtifact) -> dict[str, str]:
    return {
        "type": item.type,
        "path": item.path,
        "role": item.role,
    }


def _payload_tool_calls_to_domain(payload: list[dict[str, object]]) -> list[ToolCall]:
    tool_calls: list[ToolCall] = []
    for item in payload:
        name = str(item.get("name", "")).strip()
        arguments = item.get("arguments", {})
        if not name or not isinstance(arguments, dict):
            continue
        tool_calls.append(ToolCall(name=name, arguments=arguments))
    return tool_calls
