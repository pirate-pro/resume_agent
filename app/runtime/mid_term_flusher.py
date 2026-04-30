"""Mid-term daily flush orchestration based on structured model output."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.models import EventRecord, RunContext
from app.domain.protocols import ChatModelClient, ModelResponse, SessionRepository, StreamChunk
from app.memory.models import MemoryScope
from app.memory.policies import normalize_memory_tags
from app.memory.file_store import FileMemoryStore
from app.memory.write_plan import MemoryWritePlan, build_memory_write_plan

__all__ = [
    "MidTermFlushJobMetrics",
    "MidTermFlushJobProcessReport",
    "MidTermFlushJob",
    "MidTermFlushJobStatus",
    "MidTermFlushResult",
    "MidTermFlusher",
]

_logger = logging.getLogger(__name__)

_DELTA_EVENT_THRESHOLD = 10
_SIGNAL_SCORE_THRESHOLD = 6
_MIN_DELTA_WITH_STALE_CURSOR = 4
_STALE_CURSOR_WINDOW = timedelta(minutes=360)
_MAX_LIST_LINES = 8
_MAX_TEXT_LEN = 1200
_MAX_TOOL_TEXT_LEN = 1600
_MIN_INPUT_BUDGET_TOKENS = 512
_RETRY_BACKOFF_SECONDS = (5, 20, 60)
_DEFERRED_RETRY_SECONDS = 180
_FLUSH_LONG_TERM_MIN_CONFIDENCE = 0.55

_SUMMARIZER_SYSTEM_PROMPT = (
    "You are a rigorous mid-term memory distillation engine.\n"
    "You must reason internally in steps, but do not reveal chain-of-thought.\n"
    "Internal reasoning protocol:\n"
    "1) Reconstruct the event timeline from old to new.\n"
    "2) Validate semantic units, especially tool CALL/RESULT pairs.\n"
    "3) Extract reusable context, decisions, progress, open questions, and candidate long-term memories.\n"
    "4) Bind every extracted statement to evidence_event_ids.\n"
    "5) Calibrate confidence conservatively when evidence is weak or conflicting.\n"
    "Hard constraints:\n"
    "- Use only facts supported by provided events.\n"
    "- Never fabricate missing tool results or user intent.\n"
    "- If uncertainty exists, keep lower confidence and explicit open_questions.\n"
    "- Output one strict JSON object only. No markdown and no extra text."
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
            "created_at": _format_iso(self.created_at),
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
            session_id=_require_non_empty("session_id", payload.get("session_id")),
            agent_id=_require_non_empty("agent_id", payload.get("agent_id")),
            batch_index=_require_positive_int("batch_index", batch_index_raw if batch_index_raw is not None else 1),
            batch_total=_require_positive_int("batch_total", batch_total_raw if batch_total_raw is not None else 1),
            first_event_id=_require_non_empty("first_event_id", payload.get("first_event_id")),
            last_event_id=_require_non_empty("last_event_id", payload.get("last_event_id")),
            delta_event_count=_require_positive_int(
                "delta_event_count",
                delta_event_count_raw if delta_event_count_raw is not None else payload.get("event_count"),
            ),
            event_count=_require_positive_int("event_count", payload.get("event_count")),
            selected_unit_count=_require_positive_int(
                "selected_unit_count",
                selected_unit_count_raw if selected_unit_count_raw is not None else 1,
            ),
            signal_score=_require_non_negative_int("signal_score", payload.get("signal_score")),
            input_estimated_tokens=_require_positive_int(
                "input_estimated_tokens",
                input_estimated_tokens_raw if input_estimated_tokens_raw is not None else 1,
            ),
            input_budget_tokens=_require_positive_int(
                "input_budget_tokens",
                input_budget_tokens_raw if input_budget_tokens_raw is not None else 1,
            ),
            events=normalized_events,
            semantic_units=normalized_units,
            created_at=_parse_iso_datetime(payload.get("created_at")) or datetime.now(UTC),
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
            "next_attempt_at": _format_iso(self.next_attempt_at),
            "created_at": _format_iso(self.created_at),
            "updated_at": _format_iso(self.updated_at),
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
            job_id=_require_non_empty("job_id", payload.get("job_id")),
            session_id=_require_non_empty("session_id", payload.get("session_id")),
            agent_id=_require_non_empty("agent_id", payload.get("agent_id")),
            status=status,
            retry_count=_require_non_negative_int("retry_count", payload.get("retry_count")),
            next_attempt_at=_parse_iso_datetime(payload.get("next_attempt_at")) or datetime.now(UTC),
            created_at=_parse_iso_datetime(payload.get("created_at")) or datetime.now(UTC),
            updated_at=_parse_iso_datetime(payload.get("updated_at")) or datetime.now(UTC),
            event_pack=MidTermEventPack.from_payload(event_pack_raw),
            daily_path=_require_non_empty("daily_path", payload.get("daily_path")),
            last_error=_optional_text(payload.get("last_error")),
        )


@dataclass(slots=True)
class _FlushCursor:
    last_event_id: str | None
    last_flushed_at: datetime | None


@dataclass(slots=True)
class _PreparedSemanticUnit:
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
            "created_at": _format_iso(self.created_at),
            "summary": self.summary,
            "events": self.events,
            "estimated_tokens": self.estimated_tokens,
        }


class MidTermEventPackBuilder:
    """Build incremental event packs for flush jobs with semantic units and token budgets."""

    def __init__(
        self,
        session_repository: SessionRepository,
        *,
        model_context_window_tokens: int,
        model_input_ratio: float,
        model_output_reserve_tokens: int,
        prompt_overhead_tokens: int,
        max_input_tokens: int,
    ) -> None:
        self._session_repository = session_repository
        self._model_context_window_tokens = model_context_window_tokens
        self._model_input_ratio = model_input_ratio
        self._model_output_reserve_tokens = model_output_reserve_tokens
        self._prompt_overhead_tokens = prompt_overhead_tokens
        self._max_input_tokens = max_input_tokens

    def build(
        self,
        *,
        context: RunContext,
        cursor: _FlushCursor,
    ) -> tuple[list[MidTermEventPack] | None, str]:
        events = self._session_repository.list_events(context.session_id)
        agent_events = [event for event in events if event.agent_id == context.agent_id]
        if not agent_events:
            return None, "no_agent_events"

        delta_events = _slice_events_after_cursor(agent_events, cursor.last_event_id)
        if not delta_events:
            return None, "no_new_events"

        signal_score = _signal_score(delta_events)
        now = delta_events[-1].created_at
        if not _should_flush(
            delta_events=delta_events,
            signal_score=signal_score,
            last_flushed_at=cursor.last_flushed_at,
            now=now,
        ):
            return None, "threshold_not_met"

        budget_tokens = self._compute_input_budget_tokens()
        semantic_units = self._build_semantic_units(delta_events)
        if not semantic_units:
            return None, "empty_semantic_units"

        unit_batches = self._split_units_into_batches(semantic_units, budget_tokens=budget_tokens)
        packs: list[MidTermEventPack] = []
        total_batches = len(unit_batches)
        for index, batch_units in enumerate(unit_batches, start=1):
            normalized_events = self._collect_unique_events_from_units(batch_units)
            if not normalized_events:
                continue
            input_estimated_tokens = sum(unit.estimated_tokens for unit in batch_units)
            raw_event_count = len(normalized_events)
            first_event_id = str(normalized_events[0].get("event_id", "")).strip()
            last_event_id = str(normalized_events[-1].get("event_id", "")).strip()
            if not first_event_id or not last_event_id:
                continue
            packs.append(
                MidTermEventPack(
                    session_id=context.session_id,
                    agent_id=context.agent_id,
                    batch_index=index,
                    batch_total=total_batches,
                    first_event_id=first_event_id,
                    last_event_id=last_event_id,
                    delta_event_count=len(delta_events),
                    event_count=raw_event_count,
                    selected_unit_count=len(batch_units),
                    signal_score=_signal_score(delta_events),
                    input_estimated_tokens=max(1, input_estimated_tokens),
                    input_budget_tokens=budget_tokens,
                    events=normalized_events,
                    semantic_units=[unit.to_payload() for unit in batch_units],
                    created_at=now,
                )
            )
        if not packs:
            return None, "empty_event_batch"
        return packs, "ready"

    def _compute_input_budget_tokens(self) -> int:
        dynamic_budget = int(self._model_context_window_tokens * self._model_input_ratio)
        candidate = dynamic_budget - self._model_output_reserve_tokens - self._prompt_overhead_tokens
        capped_candidate = min(candidate, self._max_input_tokens)
        return max(_MIN_INPUT_BUDGET_TOKENS, capped_candidate)

    def _build_semantic_units(self, events: list[EventRecord]) -> list[_PreparedSemanticUnit]:
        message_types = {"user_message", "assistant_message", "assistant_thinking"}
        normalized_cache = {event.event_id: _normalize_event_for_pack(event) for event in events}
        buffered_messages: list[EventRecord] = []
        pending_calls: dict[str, EventRecord] = {}
        units: list[_PreparedSemanticUnit] = []

        def flush_messages() -> None:
            nonlocal buffered_messages
            if not buffered_messages:
                return
            message_events = [normalized_cache[item.event_id] for item in buffered_messages]
            event_ids = [item.event_id for item in buffered_messages]
            user_text = [
                _safe_text(item.payload.get("content")) for item in buffered_messages if item.type == "user_message"
            ]
            assistant_text = [
                _safe_text(item.payload.get("content"))
                for item in buffered_messages
                if item.type in {"assistant_message", "assistant_thinking"}
            ]
            summary = {
                "user_messages": [text for text in user_text if text],
                "assistant_messages": [text for text in assistant_text if text],
            }
            unit_payload = {
                "unit_type": "message_turn",
                "event_ids": event_ids,
                "summary": summary,
                "events": message_events,
            }
            units.append(
                _PreparedSemanticUnit(
                    unit_id=f"unit_msg_{event_ids[0]}",
                    unit_type="message_turn",
                    event_ids=event_ids,
                    events=message_events,
                    summary=summary,
                    created_at=buffered_messages[-1].created_at,
                    estimated_tokens=_estimate_tokens_from_object(unit_payload),
                )
            )
            buffered_messages = []

        def append_single_event_unit(
            *,
            event: EventRecord,
            unit_type: str,
            summary: dict[str, Any],
        ) -> None:
            normalized_event = normalized_cache[event.event_id]
            unit_payload = {
                "unit_type": unit_type,
                "event_ids": [event.event_id],
                "summary": summary,
                "events": [normalized_event],
            }
            units.append(
                _PreparedSemanticUnit(
                    unit_id=f"unit_{unit_type}_{event.event_id}",
                    unit_type=unit_type,
                    event_ids=[event.event_id],
                    events=[normalized_event],
                    summary=summary,
                    created_at=event.created_at,
                    estimated_tokens=_estimate_tokens_from_object(unit_payload),
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
                tool_call_id = _tool_call_id(event.payload)
                if tool_call_id is not None:
                    pending_calls[tool_call_id] = event
                else:
                    append_single_event_unit(
                        event=event,
                        unit_type="tool_call_orphan",
                        summary={
                            "tool_name": _safe_text(event.payload.get("name"), max_len=80),
                            "arguments": _compact_json(event.payload.get("arguments"), max_len=_MAX_TOOL_TEXT_LEN),
                        },
                    )
                continue

            if event.type == "tool_result":
                tool_call_id = _tool_call_id(event.payload)
                call_event = pending_calls.pop(tool_call_id, None) if tool_call_id is not None else None
                if call_event is not None:
                    call_normalized = normalized_cache[call_event.event_id]
                    result_normalized = normalized_cache[event.event_id]
                    event_ids = [call_event.event_id, event.event_id]
                    summary = {
                        "tool_name": _safe_text(call_event.payload.get("name"), max_len=80)
                        or _safe_text(event.payload.get("tool_name"), max_len=80),
                        "call_arguments": _compact_json(call_event.payload.get("arguments"), max_len=_MAX_TOOL_TEXT_LEN),
                        "result_success": bool(event.payload.get("success")),
                        "result_content": _safe_text(event.payload.get("content"), max_len=_MAX_TOOL_TEXT_LEN),
                    }
                    unit_payload = {
                        "unit_type": "tool_pair",
                        "event_ids": event_ids,
                        "summary": summary,
                        "events": [call_normalized, result_normalized],
                    }
                    units.append(
                        _PreparedSemanticUnit(
                            unit_id=f"unit_tool_pair_{call_event.event_id}_{event.event_id}",
                            unit_type="tool_pair",
                            event_ids=event_ids,
                            events=[call_normalized, result_normalized],
                            summary=summary,
                            created_at=event.created_at,
                            estimated_tokens=_estimate_tokens_from_object(unit_payload),
                        )
                    )
                else:
                    append_single_event_unit(
                        event=event,
                        unit_type="tool_result_orphan",
                        summary={
                            "tool_name": _safe_text(event.payload.get("tool_name"), max_len=80),
                            "result_success": bool(event.payload.get("success")),
                            "result_content": _safe_text(event.payload.get("content"), max_len=_MAX_TOOL_TEXT_LEN),
                        },
                    )
                continue

            if event.type == "memory_write":
                args = event.payload.get("arguments") if isinstance(event.payload, dict) else {}
                if not isinstance(args, dict):
                    args = {}
                append_single_event_unit(
                    event=event,
                    unit_type="memory_write",
                    summary={
                        "content": _safe_text(args.get("content")),
                        "tags": [tag for tag in args.get("tags", []) if isinstance(tag, str)] if isinstance(args.get("tags"), list) else [],
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
                    "payload": _compact_json(event.payload, max_len=_MAX_TOOL_TEXT_LEN),
                },
            )

        flush_messages()

        if pending_calls:
            for call_event in sorted(pending_calls.values(), key=lambda item: item.created_at):
                append_single_event_unit(
                    event=call_event,
                    unit_type="tool_call_orphan",
                    summary={
                        "tool_name": _safe_text(call_event.payload.get("name"), max_len=80),
                        "arguments": _compact_json(call_event.payload.get("arguments"), max_len=_MAX_TOOL_TEXT_LEN),
                    },
                )

        units.sort(key=lambda unit: unit.created_at)
        return units

    def _split_units_into_batches(
        self,
        units: list[_PreparedSemanticUnit],
        *,
        budget_tokens: int,
    ) -> list[list[_PreparedSemanticUnit]]:
        if not units:
            return []
        reversed_chunks: list[list[_PreparedSemanticUnit]] = []
        current_reversed: list[_PreparedSemanticUnit] = []
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

        batches: list[list[_PreparedSemanticUnit]] = []
        for chunk in reversed(reversed_chunks):
            batches.append(list(reversed(chunk)))
        return batches

    def _collect_unique_events_from_units(self, units: list[_PreparedSemanticUnit]) -> list[dict[str, Any]]:
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


class MidTermSummarizer:
    """Summarize event packs into structured sections using model output."""

    def __init__(self, model_client: ChatModelClient) -> None:
        self._model_client = model_client

    def summarize(self, pack: MidTermEventPack) -> dict[str, Any]:
        prompt = _build_user_prompt(pack)
        response = self._model_client.generate(
            system_prompt=_SUMMARIZER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            tools=[],
        )
        if not isinstance(response, ModelResponse):
            raise ValidationError("summarizer model response type is invalid.")
        text = (response.content or "").strip()
        if not text:
            raise ValidationError("summarizer model returned empty content.")
        payload = _parse_json_object(text)
        if not isinstance(payload, dict):
            raise ValidationError("summarizer output is not JSON object.")
        return payload

    async def summarize_async(self, pack: MidTermEventPack) -> dict[str, Any]:
        chunks: list[str] = []
        async for chunk in self._model_client.generate_stream(
            system_prompt=_SUMMARIZER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(pack)}],
            tools=[],
        ):
            if not isinstance(chunk, StreamChunk):
                continue
            if chunk.delta:
                chunks.append(chunk.delta)
        payload = _parse_json_object("".join(chunks).strip())
        if not isinstance(payload, dict):
            raise ValidationError("summarizer stream output is not JSON object.")
        return payload


class MidTermSummaryValidator:
    """Validate summarizer JSON against schema and evidence constraints."""

    _REQUIRED_KEYS = (
        "active_context",
        "decisions",
        "progress",
        "open_questions",
        "candidate_long_term",
        "artifact_refs",
    )

    def validate(self, summary: dict[str, Any], pack: MidTermEventPack) -> dict[str, Any]:
        for key in self._REQUIRED_KEYS:
            if key not in summary:
                raise ValidationError(f"summarizer output missing key: {key}")
            if not isinstance(summary[key], list):
                raise ValidationError(f"summarizer key '{key}' must be list.")

        valid_event_ids = {str(item.get("event_id", "")).strip() for item in pack.events}
        if "" in valid_event_ids:
            valid_event_ids.remove("")

        normalized: dict[str, Any] = {}
        normalized["active_context"] = self._normalize_active_context(summary["active_context"], valid_event_ids)
        normalized["decisions"] = self._normalize_decisions(summary["decisions"], valid_event_ids)
        normalized["progress"] = self._normalize_progress(summary["progress"], valid_event_ids)
        normalized["open_questions"] = self._normalize_open_questions(summary["open_questions"], valid_event_ids)
        normalized["candidate_long_term"] = self._normalize_candidates(summary["candidate_long_term"], valid_event_ids)
        normalized["artifact_refs"] = self._normalize_artifact_refs(summary["artifact_refs"], valid_event_ids)
        return normalized

    def _normalize_active_context(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in items[:_MAX_LIST_LINES]:
            if not isinstance(raw, dict):
                continue
            summary = _optional_text(raw.get("summary"))
            evidence = _normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            if summary is None or not evidence:
                continue
            confidence = _normalize_score(raw.get("confidence"), default=0.7)
            output.append({"summary": summary, "evidence_event_ids": evidence, "confidence": confidence})
        return output

    def _normalize_decisions(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in items[:_MAX_LIST_LINES]:
            if not isinstance(raw, dict):
                continue
            summary = _optional_text(raw.get("summary"))
            evidence = _normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            if summary is None or not evidence:
                continue
            stability = _optional_text(raw.get("stability")) or "tentative"
            output.append({"summary": summary, "evidence_event_ids": evidence, "stability": stability})
        return output

    def _normalize_progress(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in items[:_MAX_LIST_LINES]:
            if not isinstance(raw, dict):
                continue
            tool_name = _optional_text(raw.get("tool_name"))
            call_summary = _optional_text(raw.get("call_summary"))
            result_summary = _optional_text(raw.get("result_summary"))
            evidence = _normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            if tool_name is None or call_summary is None or result_summary is None or not evidence:
                continue
            success = bool(raw.get("success"))
            output.append(
                {
                    "tool_name": tool_name,
                    "call_summary": call_summary,
                    "result_summary": result_summary,
                    "success": success,
                    "evidence_event_ids": evidence,
                }
            )
        return output

    def _normalize_open_questions(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in items[:_MAX_LIST_LINES]:
            if not isinstance(raw, dict):
                continue
            question = _optional_text(raw.get("question"))
            evidence = _normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            if question is None or not evidence:
                continue
            output.append({"question": question, "evidence_event_ids": evidence})
        return output

    def _normalize_candidates(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in items[:_MAX_LIST_LINES]:
            if not isinstance(raw, dict):
                continue
            content = _optional_text(raw.get("content"))
            why = _optional_text(raw.get("why_reusable"))
            evidence = _normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            tags_raw = raw.get("tags")
            tags = [tag.strip() for tag in tags_raw if isinstance(tag, str) and tag.strip()] if isinstance(tags_raw, list) else []
            if content is None or why is None or not evidence:
                continue
            confidence = _normalize_score(raw.get("confidence"), default=0.7)
            output.append(
                {
                    "content": content,
                    "tags": tags,
                    "confidence": confidence,
                    "why_reusable": why,
                    "evidence_event_ids": evidence,
                }
            )
        return output

    def _normalize_artifact_refs(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in items[:_MAX_LIST_LINES]:
            if not isinstance(raw, dict):
                continue
            path_or_file_id = _optional_text(raw.get("path_or_file_id"))
            reason = _optional_text(raw.get("reason"))
            evidence = _normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            if path_or_file_id is None or reason is None or not evidence:
                continue
            output.append({"path_or_file_id": path_or_file_id, "reason": reason, "evidence_event_ids": evidence})
        return output


class MidTermDailyRenderer:
    """Render validated summary JSON into markdown blocks."""

    def render(self, *, summary: dict[str, Any], pack: MidTermEventPack, flushed_at: datetime) -> str:
        flush_id = _flush_id_for_pack(pack)
        lines: list[str] = [
            f"## Flush {_format_iso(flushed_at)}",
            f"<!-- flush_id: {flush_id} -->",
            "",
            "### Meta",
            f"- session_id: {pack.session_id}",
            f"- agent_id: {pack.agent_id}",
            f"- batch: {pack.batch_index}/{pack.batch_total}",
            f"- event_range: {pack.first_event_id}..{pack.last_event_id}",
            f"- event_count: {pack.event_count}",
            f"- delta_event_count: {pack.delta_event_count}",
            f"- semantic_units: {pack.selected_unit_count}",
            f"- signal_score: {pack.signal_score}",
            f"- input_estimated_tokens: {pack.input_estimated_tokens}",
            f"- input_budget_tokens: {pack.input_budget_tokens}",
            "",
            "### Active Context",
        ]
        lines.extend(_render_active_context(summary["active_context"]))
        lines.extend(["", "### Decisions"])
        lines.extend(_render_decisions(summary["decisions"]))
        lines.extend(["", "### Progress"])
        lines.extend(_render_progress(summary["progress"]))
        lines.extend(["", "### Open Questions"])
        lines.extend(_render_open_questions(summary["open_questions"]))
        lines.extend(["", "### Candidate Long-Term Memories"])
        lines.extend(_render_candidates(summary["candidate_long_term"]))
        lines.extend(["", "### Artifact References"])
        lines.extend(_render_artifact_refs(summary["artifact_refs"]))
        lines.extend(["", ""])
        return "\n".join(lines)


class MidTermFlushJobStore:
    """Persist and query flush jobs by session + agent."""

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir

    def create_job(self, job: MidTermFlushJob) -> None:
        self._write_job(job)

    def update_job(self, job: MidTermFlushJob) -> None:
        self._write_job(job)

    def get_job(self, *, session_id: str, agent_id: str, job_id: str) -> MidTermFlushJob | None:
        path = self._job_path(session_id=session_id, agent_id=agent_id, job_id=job_id)
        if not path.exists():
            return None
        payload = _read_json(path)
        return MidTermFlushJob.from_payload(payload)

    def list_jobs(self, *, session_id: str, agent_id: str) -> list[MidTermFlushJob]:
        base = self._job_dir(session_id=session_id, agent_id=agent_id)
        if not base.exists():
            return []
        jobs: list[MidTermFlushJob] = []
        for path in sorted(base.glob("*.json")):
            try:
                payload = _read_json(path)
                jobs.append(MidTermFlushJob.from_payload(payload))
            except ValidationError as exc:
                _logger.warning("skip invalid mid-term job payload: path=%s error=%s", path, exc)
        jobs.sort(key=lambda item: item.created_at)
        return jobs

    def find_duplicate_job(
        self,
        *,
        session_id: str,
        agent_id: str,
        first_event_id: str,
        last_event_id: str,
    ) -> MidTermFlushJob | None:
        for job in self.list_jobs(session_id=session_id, agent_id=agent_id):
            if job.event_pack.first_event_id != first_event_id:
                continue
            if job.event_pack.last_event_id != last_event_id:
                continue
            if job.status in {
                MidTermFlushJobStatus.PENDING,
                MidTermFlushJobStatus.RUNNING,
                MidTermFlushJobStatus.RETRY,
                MidTermFlushJobStatus.DEFERRED,
                MidTermFlushJobStatus.SUCCEEDED,
            }:
                return job
        return None

    def list_job_targets(self) -> list[tuple[str, str]]:
        """Return `(session_id, agent_id)` pairs that have persisted flush jobs."""
        agents_root = self._root_dir / "agents"
        if not agents_root.exists():
            return []
        pairs: list[tuple[str, str]] = []
        for agent_dir in sorted(agents_root.iterdir()):
            if not agent_dir.is_dir():
                continue
            agent_id = agent_dir.name.strip()
            if not agent_id:
                continue
            jobs_root = agent_dir / "mid_term" / "flush_jobs"
            if not jobs_root.exists():
                continue
            for session_dir in sorted(jobs_root.iterdir()):
                if not session_dir.is_dir():
                    continue
                session_id = session_dir.name.strip()
                if not session_id:
                    continue
                has_job_file = any(path.is_file() and path.suffix == ".json" for path in session_dir.iterdir())
                if not has_job_file:
                    continue
                pairs.append((session_id, agent_id))
        return pairs

    def list_all_jobs(self) -> list[MidTermFlushJob]:
        """Return all persisted jobs across agents/sessions."""
        jobs: list[MidTermFlushJob] = []
        for session_id, agent_id in self.list_job_targets():
            jobs.extend(self.list_jobs(session_id=session_id, agent_id=agent_id))
        return jobs

    def _job_dir(self, *, session_id: str, agent_id: str) -> Path:
        path = self._root_dir / "agents" / agent_id / "mid_term" / "flush_jobs" / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _job_path(self, *, session_id: str, agent_id: str, job_id: str) -> Path:
        return self._job_dir(session_id=session_id, agent_id=agent_id) / f"{job_id}.json"

    def _write_job(self, job: MidTermFlushJob) -> None:
        path = self._job_path(session_id=job.session_id, agent_id=job.agent_id, job_id=job.job_id)
        _write_json_atomic(path, job.to_payload())


class MidTermFlusher:
    """Queue, process, and persist mid-term flush jobs."""

    def __init__(
        self,
        session_repository: SessionRepository,
        memory_store: FileMemoryStore,
        model_client: ChatModelClient,
        *,
        model_context_window_tokens: int = 32768,
        model_input_ratio: float = 0.35,
        model_output_reserve_tokens: int = 1200,
        prompt_overhead_tokens: int = 900,
        max_input_tokens: int = 5200,
    ) -> None:
        if model_context_window_tokens <= 0:
            raise ValidationError("model_context_window_tokens must be positive.")
        if model_input_ratio <= 0 or model_input_ratio >= 1:
            raise ValidationError("model_input_ratio must be in (0,1).")
        if model_output_reserve_tokens <= 0:
            raise ValidationError("model_output_reserve_tokens must be positive.")
        if prompt_overhead_tokens <= 0:
            raise ValidationError("prompt_overhead_tokens must be positive.")
        if max_input_tokens < _MIN_INPUT_BUDGET_TOKENS:
            raise ValidationError(f"max_input_tokens must be at least {_MIN_INPUT_BUDGET_TOKENS}.")
        self._session_repository = session_repository
        self._memory_store = memory_store
        self._job_store = MidTermFlushJobStore(memory_store.root_dir)
        self._event_pack_builder = MidTermEventPackBuilder(
            session_repository,
            model_context_window_tokens=model_context_window_tokens,
            model_input_ratio=model_input_ratio,
            model_output_reserve_tokens=model_output_reserve_tokens,
            prompt_overhead_tokens=prompt_overhead_tokens,
            max_input_tokens=max_input_tokens,
        )
        self._summarizer = MidTermSummarizer(model_client)
        self._validator = MidTermSummaryValidator()
        self._renderer = MidTermDailyRenderer()

    def flush_for_run_finished(self, context: RunContext) -> MidTermFlushResult:
        if not isinstance(context, RunContext):
            raise ValidationError("context must be RunContext.")
        cursor = self._load_cursor(session_id=context.session_id, agent_id=context.agent_id)
        packs, reason = self._event_pack_builder.build(context=context, cursor=cursor)
        if not packs:
            return MidTermFlushResult(
                flushed=False,
                reason=reason,
                session_id=context.session_id,
                agent_id=context.agent_id,
                event_count=0,
                signal_score=0,
                last_event_id=cursor.last_event_id,
            )

        jobs: list[MidTermFlushJob] = []
        for pack in packs:
            duplicate = self._job_store.find_duplicate_job(
                session_id=context.session_id,
                agent_id=context.agent_id,
                first_event_id=pack.first_event_id,
                last_event_id=pack.last_event_id,
            )
            if duplicate is None:
                job = self._create_job(context=context, pack=pack)
                self._job_store.create_job(job)
            else:
                job = duplicate
            jobs.append(job)

        focus_job = jobs[-1]
        processed = self._process_due_jobs(
            session_id=context.session_id,
            agent_id=context.agent_id,
            max_jobs=max(3, len(packs) + 2),
        )
        processed_by_id = {item.job_id: item for item in processed}
        if focus_job.job_id in processed_by_id:
            focus_job = processed_by_id[focus_job.job_id]
        else:
            refreshed = self._job_store.get_job(
                session_id=context.session_id,
                agent_id=context.agent_id,
                job_id=focus_job.job_id,
            )
            if refreshed is not None:
                focus_job = refreshed

        total_event_count = sum(pack.event_count for pack in packs)
        total_signal_score = sum(pack.signal_score for pack in packs)
        return MidTermFlushResult(
            flushed=focus_job.status == MidTermFlushJobStatus.SUCCEEDED,
            reason=focus_job.status.value,
            session_id=context.session_id,
            agent_id=context.agent_id,
            event_count=total_event_count,
            signal_score=total_signal_score,
            daily_path=focus_job.daily_path,
            last_event_id=focus_job.event_pack.last_event_id,
            job_id=focus_job.job_id,
            job_status=focus_job.status.value,
            retry_count=focus_job.retry_count,
        )

    def process_due_jobs(
        self,
        *,
        max_agents: int = 24,
        max_jobs_per_agent: int = 2,
    ) -> int:
        """Process due retry/deferred jobs across all agents."""
        report = self.process_due_jobs_report(
            max_agents=max_agents,
            max_jobs_per_agent=max_jobs_per_agent,
        )
        return report.processed_count

    def process_due_jobs_report(
        self,
        *,
        max_agents: int = 24,
        max_jobs_per_agent: int = 2,
    ) -> MidTermFlushJobProcessReport:
        """Process due jobs and return structured outcome counters."""
        if max_agents <= 0:
            raise ValidationError("max_agents must be positive.")
        if max_jobs_per_agent <= 0:
            raise ValidationError("max_jobs_per_agent must be positive.")
        processed_count = 0
        succeeded_count = 0
        retry_count = 0
        deferred_count = 0
        job_targets = self._job_store.list_job_targets()
        scanned_targets = 0
        for session_id, agent_id in job_targets[:max_agents]:
            scanned_targets += 1
            processed = self._process_due_jobs(
                session_id=session_id,
                agent_id=agent_id,
                max_jobs=max_jobs_per_agent,
            )
            processed_count += len(processed)
            for job in processed:
                if job.status == MidTermFlushJobStatus.SUCCEEDED:
                    succeeded_count += 1
                elif job.status == MidTermFlushJobStatus.RETRY:
                    retry_count += 1
                elif job.status == MidTermFlushJobStatus.DEFERRED:
                    deferred_count += 1
        return MidTermFlushJobProcessReport(
            processed_count=processed_count,
            succeeded_count=succeeded_count,
            retry_count=retry_count,
            deferred_count=deferred_count,
            target_count=len(job_targets),
            scanned_targets=scanned_targets,
        )

    def collect_job_metrics(self) -> MidTermFlushJobMetrics:
        """Collect queue-level metrics for logging/observability."""
        jobs = self._job_store.list_all_jobs()
        now = datetime.now(UTC)
        pending_jobs = 0
        running_jobs = 0
        retry_jobs = 0
        deferred_jobs = 0
        succeeded_jobs = 0
        due_jobs = 0
        due_retry_jobs = 0
        due_deferred_jobs = 0
        for job in jobs:
            if job.status == MidTermFlushJobStatus.PENDING:
                pending_jobs += 1
            elif job.status == MidTermFlushJobStatus.RUNNING:
                running_jobs += 1
            elif job.status == MidTermFlushJobStatus.RETRY:
                retry_jobs += 1
            elif job.status == MidTermFlushJobStatus.DEFERRED:
                deferred_jobs += 1
            elif job.status == MidTermFlushJobStatus.SUCCEEDED:
                succeeded_jobs += 1
            if job.status in {MidTermFlushJobStatus.PENDING, MidTermFlushJobStatus.RETRY, MidTermFlushJobStatus.DEFERRED}:
                if job.next_attempt_at <= now:
                    due_jobs += 1
                    if job.status == MidTermFlushJobStatus.RETRY:
                        due_retry_jobs += 1
                    elif job.status == MidTermFlushJobStatus.DEFERRED:
                        due_deferred_jobs += 1

        return MidTermFlushJobMetrics(
            total_jobs=len(jobs),
            pending_jobs=pending_jobs,
            running_jobs=running_jobs,
            retry_jobs=retry_jobs,
            deferred_jobs=deferred_jobs,
            succeeded_jobs=succeeded_jobs,
            due_jobs=due_jobs,
            due_retry_jobs=due_retry_jobs,
            due_deferred_jobs=due_deferred_jobs,
            target_count=len(self._job_store.list_job_targets()),
        )

    def _create_job(self, *, context: RunContext, pack: MidTermEventPack) -> MidTermFlushJob:
        now = datetime.now(UTC)
        path = self._daily_path(agent_id=context.agent_id, now=pack.created_at)
        return MidTermFlushJob(
            job_id=f"job_{uuid4().hex[:12]}",
            session_id=context.session_id,
            agent_id=context.agent_id,
            status=MidTermFlushJobStatus.PENDING,
            retry_count=0,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
            event_pack=pack,
            daily_path=str(path),
            last_error=None,
        )

    def _process_due_jobs(self, *, session_id: str, agent_id: str, max_jobs: int) -> list[MidTermFlushJob]:
        now = datetime.now(UTC)
        output: list[MidTermFlushJob] = []
        jobs = self._job_store.list_jobs(session_id=session_id, agent_id=agent_id)
        for job in jobs:
            if len(output) >= max_jobs:
                break
            if job.status == MidTermFlushJobStatus.SUCCEEDED:
                continue
            if job.status == MidTermFlushJobStatus.RUNNING:
                continue
            if job.next_attempt_at > now:
                continue
            updated = self._process_one_job(job)
            output.append(updated)
        return output

    def _process_one_job(self, job: MidTermFlushJob) -> MidTermFlushJob:
        running = MidTermFlushJob(
            job_id=job.job_id,
            session_id=job.session_id,
            agent_id=job.agent_id,
            status=MidTermFlushJobStatus.RUNNING,
            retry_count=job.retry_count,
            next_attempt_at=job.next_attempt_at,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            event_pack=job.event_pack,
            daily_path=job.daily_path,
            last_error=job.last_error,
        )
        self._job_store.update_job(running)
        try:
            raw_summary = self._summarizer.summarize(running.event_pack)
            validated = self._validator.validate(raw_summary, running.event_pack)
            flushed_at = datetime.now(UTC)
            block = self._renderer.render(summary=validated, pack=running.event_pack, flushed_at=flushed_at)
            self._append_daily_block(Path(running.daily_path), running.event_pack, block)
            facts_written, facts_skipped = self._materialize_candidate_long_term_facts(
                job=running,
                summary=validated,
                flushed_at=flushed_at,
            )
            self._save_cursor(
                session_id=running.session_id,
                agent_id=running.agent_id,
                cursor=_FlushCursor(last_event_id=running.event_pack.last_event_id, last_flushed_at=flushed_at),
            )
            succeeded = MidTermFlushJob(
                job_id=running.job_id,
                session_id=running.session_id,
                agent_id=running.agent_id,
                status=MidTermFlushJobStatus.SUCCEEDED,
                retry_count=running.retry_count,
                next_attempt_at=flushed_at,
                created_at=running.created_at,
                updated_at=flushed_at,
                event_pack=running.event_pack,
                daily_path=running.daily_path,
                last_error=None,
            )
            self._job_store.update_job(succeeded)
            if facts_written > 0 or facts_skipped > 0:
                _logger.debug(
                    "mid-term candidate facts materialized: session_id=%s agent_id=%s job_id=%s written=%s skipped=%s",
                    running.session_id,
                    running.agent_id,
                    running.job_id,
                    facts_written,
                    facts_skipped,
                )
            return succeeded
        except Exception as exc:  # noqa: BLE001
            retried = self._mark_retry_or_deferred(running, error=str(exc))
            self._job_store.update_job(retried)
            _logger.warning(
                "mid-term job failed: job_id=%s session_id=%s agent_id=%s status=%s retry=%s error=%s",
                retried.job_id,
                retried.session_id,
                retried.agent_id,
                retried.status.value,
                retried.retry_count,
                retried.last_error,
            )
            return retried

    def _mark_retry_or_deferred(self, job: MidTermFlushJob, *, error: str) -> MidTermFlushJob:
        now = datetime.now(UTC)
        next_retry_count = job.retry_count + 1
        if next_retry_count <= len(_RETRY_BACKOFF_SECONDS):
            backoff = timedelta(seconds=_RETRY_BACKOFF_SECONDS[next_retry_count - 1])
            status = MidTermFlushJobStatus.RETRY
            next_attempt_at = now + backoff
        else:
            status = MidTermFlushJobStatus.DEFERRED
            next_attempt_at = now + timedelta(seconds=_DEFERRED_RETRY_SECONDS)
        return MidTermFlushJob(
            job_id=job.job_id,
            session_id=job.session_id,
            agent_id=job.agent_id,
            status=status,
            retry_count=next_retry_count,
            next_attempt_at=next_attempt_at,
            created_at=job.created_at,
            updated_at=now,
            event_pack=job.event_pack,
            daily_path=job.daily_path,
            last_error=_safe_text(error, max_len=400),
        )

    def _daily_path(self, *, agent_id: str, now: datetime) -> Path:
        base = self._memory_store.root_dir / "agents" / agent_id / "mid_term" / "daily"
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{now.astimezone(UTC).date().isoformat()}.md"

    def _append_daily_block(self, path: Path, pack: MidTermEventPack, block: str) -> None:
        flush_id = _flush_id_for_pack(pack)
        marker = f"<!-- flush_id: {flush_id} -->"
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if marker in existing:
                _logger.debug(
                    "mid-term daily append skipped (duplicate flush_id): session_id=%s agent_id=%s path=%s flush_id=%s",
                    pack.session_id,
                    pack.agent_id,
                    path,
                    flush_id,
                )
                return
            if not existing.strip():
                path.write_text(f"# {path.stem}\n\n", encoding="utf-8")
        else:
            path.write_text(f"# {path.stem}\n\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(block)
        _logger.debug(
            "mid-term daily appended: session_id=%s agent_id=%s path=%s event_count=%s",
            pack.session_id,
            pack.agent_id,
            path,
            pack.event_count,
        )

    def _materialize_candidate_long_term_facts(
        self,
        *,
        job: MidTermFlushJob,
        summary: dict[str, Any],
        flushed_at: datetime,
    ) -> tuple[int, int]:
        raw_candidates = summary.get("candidate_long_term")
        if not isinstance(raw_candidates, list) or not raw_candidates:
            return (0, 0)
        written = 0
        skipped = 0
        valid_event_ids = {
            str(item.get("event_id", "")).strip()
            for item in job.event_pack.events
            if isinstance(item, dict) and str(item.get("event_id", "")).strip()
        }
        for index, raw in enumerate(raw_candidates):
            if not isinstance(raw, dict):
                skipped += 1
                continue
            content = _optional_text(raw.get("content"))
            if content is None:
                skipped += 1
                continue
            evidence_ids = _normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            # validator 已校验 evidence_event_ids，这里保留同样容错逻辑：无 evidence 仍跳过落库，避免弱证据污染。
            if not evidence_ids:
                raw_evidence = raw.get("evidence_event_ids")
                if isinstance(raw_evidence, list):
                    evidence_ids = [str(item).strip() for item in raw_evidence if isinstance(item, str) and str(item).strip()]
            if not evidence_ids:
                skipped += 1
                continue
            candidate_tags = _flush_candidate_tags(raw.get("tags"))
            source_event_id = evidence_ids[0]
            plan = build_memory_write_plan(
                agent_id=job.agent_id,
                session_id=job.session_id,
                content=content,
                tags=candidate_tags,
                source_event_id=source_event_id,
                source="mid_term_flush",
            )
            origin_key = _candidate_origin_key(
                job=job,
                candidate_index=index,
                content=content,
                tags=candidate_tags,
            )
            if self._memory_store.has_active_fact_with_metadata(
                scope=MemoryScope.AGENT_LONG,
                agent_id=job.agent_id,
                metadata_key="origin_key",
                metadata_value=origin_key,
            ):
                skipped += 1
                continue
            if self._memory_store.find_active_fact_by_content(
                scope=MemoryScope.AGENT_LONG,
                agent_id=job.agent_id,
                content=content,
            ) is not None:
                skipped += 1
                continue
            if self._memory_store.has_archived_fact_by_content(
                scope=MemoryScope.AGENT_LONG,
                agent_id=job.agent_id,
                content=content,
            ):
                skipped += 1
                continue
            if plan.canonical_key:
                active_same_key = self._memory_store.find_active_fact_by_canonical_key(
                    scope=MemoryScope.AGENT_LONG,
                    agent_id=job.agent_id,
                    canonical_key=plan.canonical_key,
                )
                if active_same_key is not None:
                    skipped += 1
                    continue
            confidence = _flush_candidate_confidence(raw.get("confidence"), fallback=plan.confidence)
            metadata = _flush_memory_metadata_from_plan(plan=plan, source_agent_id=job.agent_id, target_agent_id=job.agent_id)
            metadata.update(
                {
                    "source": "mid_term_flush",
                    "origin": "mid_term_flush",
                    "origin_key": origin_key,
                    "flush_job_id": job.job_id,
                    "flush_id": _flush_id_for_pack(job.event_pack),
                    "flush_batch": f"{job.event_pack.batch_index}/{job.event_pack.batch_total}",
                    "flush_at": _format_iso(flushed_at),
                    "why_reusable": _safe_text(raw.get("why_reusable"), max_len=300) or "reusable_context",
                    "evidence_event_ids": ",".join(evidence_ids),
                }
            )
            self._memory_store.append_fact(
                content=plan.content,
                category=plan.category,
                confidence=confidence,
                scope=MemoryScope.AGENT_LONG,
                owner_agent_id=job.agent_id,
                session_id=job.session_id,
                source_event_id=source_event_id,
                source_type="mid_term_flush",
                tags=plan.tags,
                inject_policy=plan.inject_policy,
                metadata=metadata,
            )
            written += 1
        if written > 0:
            try:
                self._memory_store.refresh_long_term_summary_from_facts(
                    scope=MemoryScope.AGENT_LONG,
                    agent_id=job.agent_id,
                )
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "mid-term flush refresh long-term summary failed (ignored): session_id=%s agent_id=%s error=%s",
                    job.session_id,
                    job.agent_id,
                    exc,
                )
        return (written, skipped)

    def _cursor_path(self, *, session_id: str, agent_id: str) -> Path:
        base = self._memory_store.root_dir / "agents" / agent_id / "mid_term" / "flush_cursors"
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{session_id}.json"

    def _load_cursor(self, *, session_id: str, agent_id: str) -> _FlushCursor:
        path = self._cursor_path(session_id=session_id, agent_id=agent_id)
        if not path.exists():
            return _FlushCursor(last_event_id=None, last_flushed_at=None)
        try:
            payload = _read_json(path)
        except (OSError, json.JSONDecodeError):
            return _FlushCursor(last_event_id=None, last_flushed_at=None)
        raw_event_id = payload.get("last_event_id")
        raw_flushed_at = payload.get("last_flushed_at")
        last_event_id = str(raw_event_id).strip() if isinstance(raw_event_id, str) and raw_event_id.strip() else None
        last_flushed_at = _parse_iso_datetime(raw_flushed_at)
        return _FlushCursor(last_event_id=last_event_id, last_flushed_at=last_flushed_at)

    def _save_cursor(self, *, session_id: str, agent_id: str, cursor: _FlushCursor) -> None:
        path = self._cursor_path(session_id=session_id, agent_id=agent_id)
        payload = {
            "last_event_id": cursor.last_event_id,
            "last_flushed_at": _format_iso(cursor.last_flushed_at) if cursor.last_flushed_at is not None else None,
        }
        _write_json_atomic(path, payload)


def _build_user_prompt(pack: MidTermEventPack) -> str:
    schema = {
        "active_context": [
            {"summary": "string", "evidence_event_ids": ["evt_xxx"], "confidence": 0.7}
        ],
        "decisions": [
            {"summary": "string", "evidence_event_ids": ["evt_xxx"], "stability": "tentative|stable"}
        ],
        "progress": [
            {
                "tool_name": "string",
                "call_summary": "string",
                "result_summary": "string",
                "success": True,
                "evidence_event_ids": ["evt_call", "evt_result"],
            }
        ],
        "open_questions": [{"question": "string", "evidence_event_ids": ["evt_xxx"]}],
        "candidate_long_term": [
            {
                "content": "string",
                "tags": ["preference"],
                "confidence": 0.7,
                "why_reusable": "string",
                "evidence_event_ids": ["evt_xxx"],
            }
        ],
        "artifact_refs": [
            {"path_or_file_id": "string", "reason": "string", "evidence_event_ids": ["evt_xxx"]}
        ],
    }
    input_payload = {
        "timeline_order": "old_to_new",
        "batch": {
            "index": pack.batch_index,
            "total": pack.batch_total,
        },
        "budget": {
            "input_budget_tokens": pack.input_budget_tokens,
            "input_estimated_tokens": pack.input_estimated_tokens,
        },
        "range": {
            "first_event_id": pack.first_event_id,
            "last_event_id": pack.last_event_id,
            "event_count": pack.event_count,
            "delta_event_count": pack.delta_event_count,
            "selected_unit_count": pack.selected_unit_count,
        },
        "semantic_units": pack.semantic_units,
        "events": pack.events,
    }
    return (
        "Task: distill this batch into structured mid-term memory JSON.\n"
        "Execution requirements:\n"
        "1) Rebuild timeline in provided old-to-new order.\n"
        "2) Treat each semantic unit as atomic, especially tool_pair units.\n"
        "3) Keep only reusable, evidence-backed information.\n"
        "4) Every output item must include evidence_event_ids from provided events.\n"
        "5) Use conservative confidence when evidence is weak.\n"
        "6) Output strict JSON object only.\n"
        f"Required schema:\n{json.dumps(schema, ensure_ascii=False)}\n"
        f"Event pack:\n{json.dumps(input_payload, ensure_ascii=False)}\n"
    )


def _parse_json_object(text: str) -> dict[str, Any]:
    if not text:
        raise ValidationError("summarizer output is empty.")
    candidates = [text]
    fence_start = text.find("```")
    if fence_start != -1:
        fence_end = text.rfind("```")
        if fence_end > fence_start:
            body = text[fence_start + 3 : fence_end].strip()
            if body.lower().startswith("json"):
                body = body[4:].strip()
            candidates.append(body)
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidates.append(text[first : last + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return {str(k): v for k, v in payload.items()}
    raise ValidationError("summarizer output is not valid JSON object.")


def _flush_id_for_pack(pack: MidTermEventPack) -> str:
    return f"{pack.session_id}|{pack.agent_id}|{pack.first_event_id}..{pack.last_event_id}"


def _flush_candidate_tags(raw_tags: Any) -> list[str]:
    tags = [tag for tag in raw_tags if isinstance(tag, str)] if isinstance(raw_tags, list) else []
    normalized = normalize_memory_tags(tags + ["long_term", "mid_term_flush_candidate"])
    disallowed = {"shared", "global", "cross_agent", "agent_short", "short", "session_state", "working_state"}
    filtered = [tag for tag in normalized if tag not in disallowed]
    if "long_term" not in filtered:
        filtered.append("long_term")
    return normalize_memory_tags(filtered)


def _flush_candidate_confidence(raw_confidence: Any, *, fallback: float) -> float:
    if isinstance(raw_confidence, (int, float)):
        value = float(raw_confidence)
        if 0 <= value <= 1:
            return round(max(_FLUSH_LONG_TERM_MIN_CONFIDENCE, value), 3)
    return fallback


def _candidate_origin_key(
    *,
    job: MidTermFlushJob,
    candidate_index: int,
    content: str,
    tags: list[str],
) -> str:
    base = "|".join(
        [
            "mid_term_flush",
            job.job_id,
            job.session_id,
            job.agent_id,
            job.event_pack.first_event_id,
            job.event_pack.last_event_id,
            str(candidate_index),
            content.strip(),
            ",".join(tags),
        ]
    )
    digest = sha256(base.encode("utf-8")).hexdigest()
    return f"flush:{digest}"


def _flush_memory_metadata_from_plan(
    *,
    plan: MemoryWritePlan,
    source_agent_id: str,
    target_agent_id: str,
) -> dict[str, str]:
    metadata: dict[str, str] = {
        "source_agent_id": source_agent_id,
        "target_agent_id": target_agent_id,
        "memory_type": plan.memory_type.value,
        "memory_scope": MemoryScope.AGENT_LONG.value,
        "kind": plan.kind,
        "source_kind": plan.source_kind,
        "subject_kind": plan.subject_kind,
        "classification_version": plan.classification_version,
        "write_key": plan.write_key,
    }
    if plan.canonical_key:
        metadata["canonical_key"] = plan.canonical_key
    if plan.normalized_value:
        metadata["normalized_value"] = plan.normalized_value
    raw_source = plan.metadata.get("source") if isinstance(plan.metadata, dict) else None
    if isinstance(raw_source, str) and raw_source.strip():
        metadata["source"] = raw_source.strip()
    return metadata


def _normalize_event_for_pack(event: EventRecord) -> dict[str, Any]:
    payload = event.payload if isinstance(event.payload, dict) else {}
    base: dict[str, Any] = {
        "event_id": event.event_id,
        "type": event.type,
        "created_at": _format_iso(event.created_at),
        "run_id": event.run_id,
    }
    if event.type in {"user_message", "assistant_message", "assistant_thinking"}:
        base["text"] = _safe_text(payload.get("content"))
        return base
    if event.type == "tool_call":
        base["tool_name"] = _safe_text(payload.get("name"), max_len=80)
        base["tool_call_id"] = _optional_text(payload.get("tool_call_id"))
        base["arguments"] = _compact_json(payload.get("arguments"), max_len=_MAX_TOOL_TEXT_LEN)
        return base
    if event.type == "tool_result":
        base["tool_name"] = _safe_text(payload.get("tool_name"), max_len=80)
        base["tool_call_id"] = _optional_text(payload.get("tool_call_id"))
        base["success"] = bool(payload.get("success"))
        base["result"] = _safe_text(payload.get("content"), max_len=_MAX_TOOL_TEXT_LEN)
        return base
    if event.type == "memory_write":
        args = payload.get("arguments")
        if isinstance(args, dict):
            base["content"] = _safe_text(args.get("content"))
            tags = args.get("tags")
            if isinstance(tags, list):
                base["tags"] = [tag for tag in tags if isinstance(tag, str) and tag.strip()]
        return base
    if event.type == "run_finished":
        base["answer_length"] = payload.get("answer_length")
        base["tool_calls"] = payload.get("tool_calls")
        return base
    base["payload"] = _compact_json(payload, max_len=_MAX_TOOL_TEXT_LEN)
    return base


def _render_active_context(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- (none)"]
    output: list[str] = []
    for item in items:
        output.append(
            f"- {item['summary']} [confidence={item['confidence']}] [evidence={','.join(item['evidence_event_ids'])}]"
        )
    return output


def _render_decisions(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- (none)"]
    return [
        f"- {item['summary']} [stability={item['stability']}] [evidence={','.join(item['evidence_event_ids'])}]"
        for item in items
    ]


def _render_progress(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- (none)"]
    output: list[str] = []
    for item in items:
        output.append(
            "- "
            + f"[CALL] {item['tool_name']} {item['call_summary']} | "
            + f"[RESULT] success={item['success']} {item['result_summary']} "
            + f"[evidence={','.join(item['evidence_event_ids'])}]"
        )
    return output


def _render_open_questions(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- (none)"]
    return [f"- {item['question']} [evidence={','.join(item['evidence_event_ids'])}]" for item in items]


def _render_candidates(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- (none)"]
    output: list[str] = []
    for item in items:
        tags = ",".join(item["tags"]) if item["tags"] else "-"
        output.append(
            f"- {item['content']} [tags={tags}] [confidence={item['confidence']}] "
            + f"[why={item['why_reusable']}] [evidence={','.join(item['evidence_event_ids'])}]"
        )
    return output


def _render_artifact_refs(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- (none)"]
    return [
        f"- {item['path_or_file_id']} [reason={item['reason']}] [evidence={','.join(item['evidence_event_ids'])}]"
        for item in items
    ]


def _slice_events_after_cursor(events: list[EventRecord], last_event_id: str | None) -> list[EventRecord]:
    if last_event_id is None:
        return list(events)
    for index, event in enumerate(events):
        if event.event_id == last_event_id:
            return events[index + 1 :]
    return list(events)


def _signal_score(events: list[EventRecord]) -> int:
    tool_pairs: set[str] = set()
    score = 0
    for event in events:
        if event.type == "memory_write":
            score += 3
        elif event.type in {"user_message", "assistant_message"}:
            score += 1
        elif event.type == "tool_call":
            tool_call_id = _tool_call_id(event.payload)
            if tool_call_id is None:
                score += 1
            else:
                tool_pairs.add(tool_call_id)
        elif event.type == "tool_result":
            tool_call_id = _tool_call_id(event.payload)
            if tool_call_id is None or tool_call_id not in tool_pairs:
                score += 1
        elif event.type == "run_finished":
            score += 1
    return score


def _should_flush(
    *,
    delta_events: list[EventRecord],
    signal_score: int,
    last_flushed_at: datetime | None,
    now: datetime,
) -> bool:
    if len(delta_events) >= _DELTA_EVENT_THRESHOLD:
        return True
    if signal_score >= _SIGNAL_SCORE_THRESHOLD:
        return True
    if last_flushed_at is None:
        return len(delta_events) >= _MIN_DELTA_WITH_STALE_CURSOR
    return now - last_flushed_at >= _STALE_CURSOR_WINDOW and len(delta_events) >= _MIN_DELTA_WITH_STALE_CURSOR


def _tool_call_id(payload: dict[str, Any]) -> str | None:
    raw = payload.get("tool_call_id")
    return _optional_text(raw)


def _normalize_evidence(raw: Any, valid_event_ids: set[str]) -> list[str]:
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        event_id = item.strip()
        if not event_id or event_id in seen:
            continue
        if event_id not in valid_event_ids:
            continue
        seen.add(event_id)
        output.append(event_id)
    return output


def _normalize_score(raw: Any, *, default: float) -> float:
    if isinstance(raw, (int, float)):
        value = float(raw)
        if 0 <= value <= 1:
            return round(value, 3)
    return default


def _safe_text(raw: Any, *, max_len: int = _MAX_TEXT_LEN) -> str:
    if raw is None:
        return ""
    text = str(raw).strip().replace("\n", " ")
    if not text:
        return ""
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _compact_json(raw: Any, *, max_len: int = _MAX_TOOL_TEXT_LEN) -> str:
    try:
        text = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(raw)
    return _safe_text(text, max_len=max_len)


_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _estimate_tokens_from_text(text: str) -> int:
    if not text:
        return 0
    cjk_count = len(_CJK_PATTERN.findall(text))
    non_cjk_len = max(0, len(text) - cjk_count)
    ascii_token_estimate = (non_cjk_len + 3) // 4
    return max(1, cjk_count + ascii_token_estimate)


def _estimate_tokens_from_object(value: Any) -> int:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(value)
    return _estimate_tokens_from_text(text)


def _require_non_empty(field_name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _require_positive_int(field_name: str, value: Any) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValidationError(f"{field_name} must be a positive integer.")
    return value


def _require_non_negative_int(field_name: str, value: Any) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValidationError(f"{field_name} must be a non-negative integer.")
    return value


def _optional_text(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    return text or None


def _parse_iso_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    normalized = raw.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _format_iso(value: datetime) -> str:
    normalized = value.astimezone(UTC).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValidationError(f"json object expected: {path}")
    return {str(k): v for k, v in payload.items()}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)
