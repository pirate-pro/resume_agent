"""Data models for mid-term memory flushing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from app.core.errors import ValidationError
from app.runtime.mid_term.shared import (
    format_iso,
    optional_text,
    parse_iso_datetime,
    require_non_empty,
    require_non_negative_int,
    require_positive_int,
)


class MidTermFlushJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY = "retry"
    DEFERRED = "deferred"
    SUCCEEDED = "succeeded"


@dataclass(slots=True)
class MidTermFlushResult:
    flushed: bool
    reason: str
    session_id: str
    agent_id: str
    event_count: int
    signal_score: int
    daily_path: str | None = None
    last_event_id: str | None = None
    job_id: str | None = None
    job_status: str | None = None
    retry_count: int = 0


@dataclass(slots=True)
class MidTermFlushJobMetrics:
    total_jobs: int
    pending_jobs: int
    running_jobs: int
    retry_jobs: int
    deferred_jobs: int
    succeeded_jobs: int
    due_jobs: int
    due_retry_jobs: int
    due_deferred_jobs: int
    target_count: int


@dataclass(slots=True)
class MidTermFlushJobProcessReport:
    processed_count: int
    succeeded_count: int
    retry_count: int
    deferred_count: int
    target_count: int
    scanned_targets: int


@dataclass(slots=True)
class MidTermEventPack:
    session_id: str
    agent_id: str
    batch_index: int
    batch_total: int
    first_event_id: str
    last_event_id: str
    delta_event_count: int
    event_count: int
    selected_unit_count: int
    signal_score: int
    input_estimated_tokens: int
    input_budget_tokens: int
    events: list[dict[str, Any]]
    semantic_units: list[dict[str, Any]]
    created_at: datetime

    def to_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "batch_index": self.batch_index,
            "batch_total": self.batch_total,
            "first_event_id": self.first_event_id,
            "last_event_id": self.last_event_id,
            "delta_event_count": self.delta_event_count,
            "event_count": self.event_count,
            "selected_unit_count": self.selected_unit_count,
            "signal_score": self.signal_score,
            "input_estimated_tokens": self.input_estimated_tokens,
            "input_budget_tokens": self.input_budget_tokens,
            "created_at": format_iso(self.created_at),
            "events": self.events,
            "semantic_units": self.semantic_units,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "MidTermEventPack":
        events_raw = payload.get("events")
        if not isinstance(events_raw, list):
            raise ValidationError("event pack 'events' must be list.")
        semantic_units_raw = payload.get("semantic_units")
        if semantic_units_raw is None:
            semantic_units_raw = []
        if not isinstance(semantic_units_raw, list):
            raise ValidationError("event pack 'semantic_units' must be list.")
        normalized_events: list[dict[str, Any]] = []
        for row in events_raw:
            if isinstance(row, dict):
                normalized_events.append({str(k): v for k, v in row.items()})
        normalized_units: list[dict[str, Any]] = []
        for unit in semantic_units_raw:
            if isinstance(unit, dict):
                normalized_units.append({str(k): v for k, v in unit.items()})
        batch_index_raw = payload.get("batch_index")
        batch_total_raw = payload.get("batch_total")
        delta_event_count_raw = payload.get("delta_event_count")
        selected_unit_count_raw = payload.get("selected_unit_count")
        input_estimated_tokens_raw = payload.get("input_estimated_tokens")
        input_budget_tokens_raw = payload.get("input_budget_tokens")
        return cls(
            session_id=require_non_empty("session_id", payload.get("session_id")),
            agent_id=require_non_empty("agent_id", payload.get("agent_id")),
            batch_index=require_positive_int("batch_index", batch_index_raw if batch_index_raw is not None else 1),
            batch_total=require_positive_int("batch_total", batch_total_raw if batch_total_raw is not None else 1),
            first_event_id=require_non_empty("first_event_id", payload.get("first_event_id")),
            last_event_id=require_non_empty("last_event_id", payload.get("last_event_id")),
            delta_event_count=require_positive_int(
                "delta_event_count",
                delta_event_count_raw if delta_event_count_raw is not None else payload.get("event_count"),
            ),
            event_count=require_positive_int("event_count", payload.get("event_count")),
            selected_unit_count=require_positive_int(
                "selected_unit_count",
                selected_unit_count_raw if selected_unit_count_raw is not None else 1,
            ),
            signal_score=require_non_negative_int("signal_score", payload.get("signal_score")),
            input_estimated_tokens=require_positive_int(
                "input_estimated_tokens",
                input_estimated_tokens_raw if input_estimated_tokens_raw is not None else 1,
            ),
            input_budget_tokens=require_positive_int(
                "input_budget_tokens",
                input_budget_tokens_raw if input_budget_tokens_raw is not None else 1,
            ),
            events=normalized_events,
            semantic_units=normalized_units,
            created_at=parse_iso_datetime(payload.get("created_at")) or datetime.now(UTC),
        )


@dataclass(slots=True)
class MidTermFlushJob:
    job_id: str
    session_id: str
    agent_id: str
    status: MidTermFlushJobStatus
    retry_count: int
    next_attempt_at: datetime
    created_at: datetime
    updated_at: datetime
    event_pack: MidTermEventPack
    daily_path: str
    last_error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "next_attempt_at": format_iso(self.next_attempt_at),
            "created_at": format_iso(self.created_at),
            "updated_at": format_iso(self.updated_at),
            "event_pack": self.event_pack.to_payload(),
            "daily_path": self.daily_path,
            "last_error": self.last_error,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "MidTermFlushJob":
        raw_status = str(payload.get("status", "")).strip().lower()
        try:
            status = MidTermFlushJobStatus(raw_status)
        except ValueError as exc:
            raise ValidationError(f"invalid flush job status: {raw_status}") from exc
        event_pack_raw = payload.get("event_pack")
        if not isinstance(event_pack_raw, dict):
            raise ValidationError("flush job 'event_pack' must be object.")
        return cls(
            job_id=require_non_empty("job_id", payload.get("job_id")),
            session_id=require_non_empty("session_id", payload.get("session_id")),
            agent_id=require_non_empty("agent_id", payload.get("agent_id")),
            status=status,
            retry_count=require_non_negative_int("retry_count", payload.get("retry_count")),
            next_attempt_at=parse_iso_datetime(payload.get("next_attempt_at")) or datetime.now(UTC),
            created_at=parse_iso_datetime(payload.get("created_at")) or datetime.now(UTC),
            updated_at=parse_iso_datetime(payload.get("updated_at")) or datetime.now(UTC),
            event_pack=MidTermEventPack.from_payload(event_pack_raw),
            daily_path=require_non_empty("daily_path", payload.get("daily_path")),
            last_error=optional_text(payload.get("last_error")),
        )


@dataclass(slots=True)
class FlushCursor:
    last_event_id: str | None
    last_flushed_at: datetime | None
