"""Flush trigger rules for mid-term memory event packs."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.models import EventRecord
from app.runtime.mid_term.shared import tool_call_id

__all__ = [
    "DELTA_EVENT_THRESHOLD",
    "MIN_DELTA_WITH_STALE_CURSOR",
    "SIGNAL_SCORE_THRESHOLD",
    "STALE_CURSOR_WINDOW",
    "score_flush_signals",
    "should_flush",
    "slice_events_after_cursor",
]

DELTA_EVENT_THRESHOLD = 10
SIGNAL_SCORE_THRESHOLD = 6
MIN_DELTA_WITH_STALE_CURSOR = 4
STALE_CURSOR_WINDOW = timedelta(minutes=360)


def slice_events_after_cursor(events: list[EventRecord], last_event_id: str | None) -> list[EventRecord]:
    if last_event_id is None:
        return list(events)
    for index, event in enumerate(events):
        if event.event_id == last_event_id:
            return events[index + 1 :]
    return list(events)


def score_flush_signals(events: list[EventRecord]) -> int:
    tool_pairs: set[str] = set()
    score = 0
    for event in events:
        if event.type == "memory_write":
            score += 3
        elif event.type in {"user_message", "assistant_message"}:
            score += 1
        elif event.type == "tool_call":
            call_id = tool_call_id(event.payload)
            if call_id is None:
                score += 1
            else:
                tool_pairs.add(call_id)
        elif event.type == "tool_result":
            call_id = tool_call_id(event.payload)
            if call_id is None or call_id not in tool_pairs:
                score += 1
        elif event.type == "run_finished":
            score += 1
    return score


def should_flush(
    *,
    delta_events: list[EventRecord],
    signal_score: int,
    last_flushed_at: datetime | None,
    now: datetime,
) -> bool:
    if len(delta_events) >= DELTA_EVENT_THRESHOLD:
        return True
    if signal_score >= SIGNAL_SCORE_THRESHOLD:
        return True
    if last_flushed_at is None:
        return len(delta_events) >= MIN_DELTA_WITH_STALE_CURSOR
    return now - last_flushed_at >= STALE_CURSOR_WINDOW and len(delta_events) >= MIN_DELTA_WITH_STALE_CURSOR
