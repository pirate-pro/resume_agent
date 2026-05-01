"""HTTP response presenters for API DTOs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, cast

from app.domain.models import EventRecord, MemoryItem, SessionMeta
from app.schemas.chat import (
    AnswerArtifactView,
    EventView,
    MemoryView,
    SessionListItem,
    SessionMessage,
    SkillSummaryView,
    ToolCallView,
)
from app.services.answer_normalizer import AnswerFormat, LayoutHint, RenderHint, SourceKind

__all__ = [
    "event_view",
    "memory_view",
    "session_item_view",
    "session_message_view",
    "skill_summary_view",
]

_ANSWER_FORMATS = {"plain_text", "markdown", "code", "markdown_source"}
_RENDER_HINTS = {"plain", "markdown_document", "markdown_source", "code_block", "large_document"}
_LAYOUT_HINTS = {"brief", "paragraph", "bullets", "steps"}
_SOURCE_KINDS = {"direct_answer", "generated_document", "file_content", "summary"}


class SkillSummaryLike(Protocol):
    name: str
    description: str


def session_item_view(item: SessionMeta) -> SessionListItem:
    return SessionListItem(
        session_id=item.session_id,
        title=item.title,
        created_at=item.created_at,
        updated_at=item.updated_at,
        is_pinned=item.is_pinned,
        pinned_at=item.pinned_at,
    )


def skill_summary_view(item: SkillSummaryLike) -> SkillSummaryView:
    return SkillSummaryView(name=item.name, description=item.description)


def event_view(item: EventRecord) -> EventView:
    return EventView(
        event_id=item.event_id,
        session_id=item.session_id,
        agent_id=item.agent_id,
        run_id=item.run_id,
        parent_run_id=item.parent_run_id,
        event_version=item.event_version,
        type=item.type,
        payload=item.payload,
        created_at=item.created_at,
    )


def memory_view(item: MemoryItem) -> MemoryView:
    return MemoryView(memory_id=item.memory_id, content=item.content, tags=item.tags)


def session_message_view(raw: Mapping[str, object]) -> SessionMessage:
    return SessionMessage(
        role=str(raw.get("role", "")),
        content=str(raw.get("content", "")),
        answer_format=cast(AnswerFormat, _enum_text(raw.get("answer_format"), _ANSWER_FORMATS, "plain_text")),
        render_hint=cast(RenderHint, _enum_text(raw.get("render_hint"), _RENDER_HINTS, "plain")),
        layout_hint=cast(LayoutHint, _enum_text(raw.get("layout_hint"), _LAYOUT_HINTS, "paragraph")),
        source_kind=cast(SourceKind, _enum_text(raw.get("source_kind"), _SOURCE_KINDS, "direct_answer")),
        artifacts=_artifact_views(raw.get("artifacts")),
        tool_calls=_tool_call_views(raw.get("tool_calls")),
        created_at=_optional_datetime(raw.get("created_at")),
    )


def _artifact_views(raw: object) -> list[AnswerArtifactView]:
    rows = raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)) else []
    return [
        AnswerArtifactView(
            type=str(item.get("type", "")),
            path=str(item.get("path", "")),
            role=str(item.get("role", "")),
        )
        for item in rows
        if isinstance(item, Mapping)
    ]


def _tool_call_views(raw: object) -> list[ToolCallView]:
    rows = raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)) else []
    return [
        ToolCallView(
            name=str(item.get("name", "")),
            arguments=_dict_value(item.get("arguments")),
        )
        for item in rows
        if isinstance(item, Mapping)
    ]


def _dict_value(raw: object) -> dict[str, Any]:
    return {str(k): v for k, v in raw.items()} if isinstance(raw, Mapping) else {}


def _enum_text(raw: object, allowed: set[str], default: str) -> str:
    text = str(raw or "").strip()
    return text if text in allowed else default


def _optional_datetime(raw: object) -> datetime | None:
    return raw if isinstance(raw, datetime) else None
