"""Semantic unit construction for context compaction."""

from __future__ import annotations

from typing import Any

from app.domain.models import EventRecord
from app.runtime.agent_events import AGENT_RESULT_SUMMARY_EVENT, AGENT_TASK_ASSIGNED_EVENT
from app.runtime.context_compaction.event_projection import (
    agent_pair_summary,
    agent_result_summary,
    agent_task_summary,
    generic_event_summary,
    normalize_event_for_prompt,
    tool_call_summary,
    tool_pair_summary,
    tool_result_summary,
)
from app.runtime.context_compaction.models import SemanticUnit
from app.runtime.context_compaction.text_utils import estimate_tokens_from_object, payload_text, safe_text

__all__ = [
    "build_semantic_units",
    "collect_unique_events",
]


def build_semantic_units(events: list[EventRecord]) -> list[SemanticUnit]:
    message_types = {"user_message", "assistant_message", "assistant_thinking"}
    units: list[SemanticUnit] = []
    buffered_messages: list[EventRecord] = []
    pending_tool_calls: dict[str, EventRecord] = {}
    pending_agent_tasks: dict[str, EventRecord] = {}

    def flush_messages() -> None:
        nonlocal buffered_messages
        if not buffered_messages:
            return
        summary = {
            "user_messages": [
                safe_text(event.payload.get("content"))
                for event in buffered_messages
                if event.type == "user_message" and safe_text(event.payload.get("content"))
            ],
            "assistant_messages": [
                safe_text(event.payload.get("content"))
                for event in buffered_messages
                if event.type in {"assistant_message", "assistant_thinking"}
                and safe_text(event.payload.get("content"))
            ],
        }
        units.append(_make_unit("message_turn", buffered_messages, summary))
        buffered_messages = []

    for event in events:
        if event.type in message_types:
            if event.type == "user_message" and buffered_messages:
                flush_messages()
            buffered_messages.append(event)
            continue

        flush_messages()

        if event.type == "tool_call":
            tool_call_id = payload_text(event.payload, "tool_call_id")
            if tool_call_id:
                pending_tool_calls[tool_call_id] = event
            else:
                units.append(_make_unit("tool_call_orphan", [event], tool_call_summary(event)))
            continue

        if event.type == "tool_result":
            tool_call_id = payload_text(event.payload, "tool_call_id")
            call_event = pending_tool_calls.pop(tool_call_id, None) if tool_call_id else None
            if call_event is None:
                units.append(_make_unit("tool_result_orphan", [event], tool_result_summary(event)))
            else:
                units.append(_make_unit("tool_pair", [call_event, event], tool_pair_summary(call_event, event)))
            continue

        if event.type == AGENT_TASK_ASSIGNED_EVENT:
            task_id = payload_text(event.payload, "task_id")
            if task_id:
                pending_agent_tasks[task_id] = event
            else:
                units.append(_make_unit("agent_task_orphan", [event], agent_task_summary(event)))
            continue

        if event.type == AGENT_RESULT_SUMMARY_EVENT:
            task_id = payload_text(event.payload, "task_id")
            task_event = pending_agent_tasks.pop(task_id, None) if task_id else None
            if task_event is None:
                units.append(_make_unit("agent_result_orphan", [event], agent_result_summary(event)))
            else:
                units.append(_make_unit("agent_task_result_pair", [task_event, event], agent_pair_summary(task_event, event)))
            continue

        units.append(_make_unit(event.type, [event], generic_event_summary(event)))

    flush_messages()

    for event in sorted(pending_tool_calls.values(), key=lambda item: item.created_at):
        units.append(_make_unit("tool_call_orphan", [event], tool_call_summary(event)))
    for event in sorted(pending_agent_tasks.values(), key=lambda item: item.created_at):
        units.append(_make_unit("agent_task_orphan", [event], agent_task_summary(event)))

    units.sort(key=lambda unit: unit.created_at)
    return units


def collect_unique_events(units: list[SemanticUnit]) -> list[EventRecord]:
    output: list[EventRecord] = []
    seen: set[str] = set()
    for unit in units:
        for event in unit.events:
            if event.event_id in seen:
                continue
            output.append(event)
            seen.add(event.event_id)
    return output


def _make_unit(unit_type: str, events: list[EventRecord], summary: dict[str, Any]) -> SemanticUnit:
    event_ids = [event.event_id for event in events]
    payload = {
        "unit_type": unit_type,
        "event_ids": event_ids,
        "summary": summary,
        "events": [normalize_event_for_prompt(event) for event in events],
    }
    return SemanticUnit(
        unit_id=f"unit_{unit_type}_{event_ids[0]}",
        unit_type=unit_type,
        event_ids=event_ids,
        events=events,
        summary=summary,
        created_at=events[-1].created_at,
        estimated_tokens=estimate_tokens_from_object(payload),
    )
