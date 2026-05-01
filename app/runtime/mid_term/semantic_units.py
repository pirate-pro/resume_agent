"""Semantic unit construction for mid-term memory flushing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.domain.models import EventRecord
from app.runtime.mid_term.shared import (
    MAX_TOOL_TEXT_LEN,
    compact_json,
    estimate_tokens_from_object,
    format_iso,
    normalize_event_for_pack,
    safe_text,
    tool_call_id,
)

__all__ = [
    "PreparedSemanticUnit",
    "build_semantic_units",
    "collect_unique_events_from_units",
    "split_units_into_batches",
]


@dataclass(slots=True)
class PreparedSemanticUnit:
    unit_id: str
    unit_type: str
    event_ids: list[str]
    events: list[dict[str, Any]]
    summary: dict[str, Any]
    created_at: datetime
    estimated_tokens: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "unit_type": self.unit_type,
            "event_ids": self.event_ids,
            "created_at": format_iso(self.created_at),
            "summary": self.summary,
            "events": self.events,
            "estimated_tokens": self.estimated_tokens,
        }


def build_semantic_units(events: list[EventRecord]) -> list[PreparedSemanticUnit]:
    message_types = {"user_message", "assistant_message", "assistant_thinking"}
    normalized_cache = {event.event_id: normalize_event_for_pack(event) for event in events}
    buffered_messages: list[EventRecord] = []
    pending_calls: dict[str, EventRecord] = {}
    units: list[PreparedSemanticUnit] = []

    def flush_messages() -> None:
        nonlocal buffered_messages
        if not buffered_messages:
            return
        message_events = [normalized_cache[item.event_id] for item in buffered_messages]
        event_ids = [item.event_id for item in buffered_messages]
        user_text = [safe_text(item.payload.get("content")) for item in buffered_messages if item.type == "user_message"]
        assistant_text = [
            safe_text(item.payload.get("content"))
            for item in buffered_messages
            if item.type in {"assistant_message", "assistant_thinking"}
        ]
        summary = {
            "user_messages": [text for text in user_text if text],
            "assistant_messages": [text for text in assistant_text if text],
        }
        units.append(
            _make_unit(
                unit_id=f"unit_msg_{event_ids[0]}",
                unit_type="message_turn",
                event_ids=event_ids,
                events=message_events,
                summary=summary,
                created_at=buffered_messages[-1].created_at,
            )
        )
        buffered_messages = []

    def append_single_event_unit(
        *,
        event: EventRecord,
        unit_type: str,
        summary: dict[str, Any],
    ) -> None:
        units.append(
            _make_unit(
                unit_id=f"unit_{unit_type}_{event.event_id}",
                unit_type=unit_type,
                event_ids=[event.event_id],
                events=[normalized_cache[event.event_id]],
                summary=summary,
                created_at=event.created_at,
            )
        )

    for event in events:
        if event.type in message_types:
            if event.type == "user_message" and buffered_messages:
                flush_messages()
            buffered_messages.append(event)
            continue

        flush_messages()

        if event.type == "tool_call":
            call_id = tool_call_id(event.payload)
            if call_id is not None:
                pending_calls[call_id] = event
            else:
                append_single_event_unit(
                    event=event,
                    unit_type="tool_call_orphan",
                    summary={
                        "tool_name": safe_text(event.payload.get("name"), max_len=80),
                        "arguments": compact_json(event.payload.get("arguments"), max_len=MAX_TOOL_TEXT_LEN),
                    },
                )
            continue

        if event.type == "tool_result":
            call_id = tool_call_id(event.payload)
            call_event = pending_calls.pop(call_id, None) if call_id is not None else None
            if call_event is not None:
                event_ids = [call_event.event_id, event.event_id]
                summary = {
                    "tool_name": safe_text(call_event.payload.get("name"), max_len=80)
                    or safe_text(event.payload.get("tool_name"), max_len=80),
                    "call_arguments": compact_json(call_event.payload.get("arguments"), max_len=MAX_TOOL_TEXT_LEN),
                    "result_success": bool(event.payload.get("success")),
                    "result_content": safe_text(event.payload.get("content"), max_len=MAX_TOOL_TEXT_LEN),
                }
                units.append(
                    _make_unit(
                        unit_id=f"unit_tool_pair_{call_event.event_id}_{event.event_id}",
                        unit_type="tool_pair",
                        event_ids=event_ids,
                        events=[normalized_cache[call_event.event_id], normalized_cache[event.event_id]],
                        summary=summary,
                        created_at=event.created_at,
                    )
                )
            else:
                append_single_event_unit(
                    event=event,
                    unit_type="tool_result_orphan",
                    summary={
                        "tool_name": safe_text(event.payload.get("tool_name"), max_len=80),
                        "result_success": bool(event.payload.get("success")),
                        "result_content": safe_text(event.payload.get("content"), max_len=MAX_TOOL_TEXT_LEN),
                    },
                )
            continue

        if event.type == "memory_write":
            args = event.payload.get("arguments") if isinstance(event.payload, dict) else {}
            if not isinstance(args, dict):
                args = {}
            tags = args.get("tags")
            append_single_event_unit(
                event=event,
                unit_type="memory_write",
                summary={
                    "content": safe_text(args.get("content")),
                    "tags": [tag for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else [],
                },
            )
            continue

        if event.type == "run_finished":
            append_single_event_unit(
                event=event,
                unit_type="run_boundary",
                summary={
                    "answer_length": event.payload.get("answer_length") if isinstance(event.payload, dict) else None,
                    "tool_calls": event.payload.get("tool_calls") if isinstance(event.payload, dict) else None,
                },
            )
            continue

        append_single_event_unit(
            event=event,
            unit_type="event",
            summary={
                "type": event.type,
                "payload": compact_json(event.payload, max_len=MAX_TOOL_TEXT_LEN),
            },
        )

    flush_messages()

    if pending_calls:
        for call_event in sorted(pending_calls.values(), key=lambda item: item.created_at):
            append_single_event_unit(
                event=call_event,
                unit_type="tool_call_orphan",
                summary={
                    "tool_name": safe_text(call_event.payload.get("name"), max_len=80),
                    "arguments": compact_json(call_event.payload.get("arguments"), max_len=MAX_TOOL_TEXT_LEN),
                },
            )

    units.sort(key=lambda unit: unit.created_at)
    return units


def split_units_into_batches(
    units: list[PreparedSemanticUnit],
    *,
    budget_tokens: int,
) -> list[list[PreparedSemanticUnit]]:
    if not units:
        return []
    reversed_chunks: list[list[PreparedSemanticUnit]] = []
    current_reversed: list[PreparedSemanticUnit] = []
    current_tokens = 0

    for unit in reversed(units):
        estimated = max(1, unit.estimated_tokens)
        if current_reversed and current_tokens + estimated > budget_tokens:
            reversed_chunks.append(current_reversed)
            current_reversed = [unit]
            current_tokens = estimated
            continue
        current_reversed.append(unit)
        current_tokens += estimated

    if current_reversed:
        reversed_chunks.append(current_reversed)

    batches: list[list[PreparedSemanticUnit]] = []
    for chunk in reversed(reversed_chunks):
        batches.append(list(reversed(chunk)))
    return batches


def collect_unique_events_from_units(units: list[PreparedSemanticUnit]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for unit in units:
        for event in unit.events:
            event_id = str(event.get("event_id", "")).strip()
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            rows.append(event)
    rows.sort(key=lambda row: str(row.get("created_at", "")))
    return rows


def _make_unit(
    *,
    unit_id: str,
    unit_type: str,
    event_ids: list[str],
    events: list[dict[str, Any]],
    summary: dict[str, Any],
    created_at: datetime,
) -> PreparedSemanticUnit:
    unit_payload = {
        "unit_type": unit_type,
        "event_ids": event_ids,
        "summary": summary,
        "events": events,
    }
    return PreparedSemanticUnit(
        unit_id=unit_id,
        unit_type=unit_type,
        event_ids=event_ids,
        events=events,
        summary=summary,
        created_at=created_at,
        estimated_tokens=estimate_tokens_from_object(unit_payload),
    )
