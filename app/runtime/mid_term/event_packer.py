"""Build semantically safe event packs for mid-term flushing."""

from __future__ import annotations

from app.core.errors import ValidationError
from app.domain.models import RunContext
from app.domain.protocols import SessionRepository
from app.runtime.mid_term.flush_rules import (
    DELTA_EVENT_THRESHOLD,
    MIN_DELTA_WITH_STALE_CURSOR,
    SIGNAL_SCORE_THRESHOLD,
    STALE_CURSOR_WINDOW,
    score_flush_signals,
    should_flush,
    slice_events_after_cursor,
)
from app.runtime.mid_term.models import FlushCursor, MidTermEventPack
from app.runtime.mid_term.semantic_units import (
    build_semantic_units,
    collect_unique_events_from_units,
    split_units_into_batches,
)
from app.runtime.mid_term.shared import MIN_INPUT_BUDGET_TOKENS


class MidTermEventPackBuilder:
    """Build incremental event packs with semantic units and token budgets."""

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
        cursor: FlushCursor,
    ) -> tuple[list[MidTermEventPack] | None, str]:
        events = self._session_repository.list_events(context.session_id)
        agent_events = [event for event in events if event.agent_id == context.agent_id]
        if not agent_events:
            return None, "no_agent_events"

        delta_events = slice_events_after_cursor(agent_events, cursor.last_event_id)
        if not delta_events:
            return None, "no_new_events"

        signal_score = score_flush_signals(delta_events)
        now = delta_events[-1].created_at
        if not should_flush(
            delta_events=delta_events,
            signal_score=signal_score,
            last_flushed_at=cursor.last_flushed_at,
            now=now,
        ):
            return None, "threshold_not_met"

        budget_tokens = self._compute_input_budget_tokens()
        semantic_units = build_semantic_units(delta_events)
        if not semantic_units:
            return None, "empty_semantic_units"

        unit_batches = split_units_into_batches(semantic_units, budget_tokens=budget_tokens)
        packs: list[MidTermEventPack] = []
        total_batches = len(unit_batches)
        for index, batch_units in enumerate(unit_batches, start=1):
            normalized_events = collect_unique_events_from_units(batch_units)
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
                    signal_score=score_flush_signals(delta_events),
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
        return max(MIN_INPUT_BUDGET_TOKENS, capped_candidate)
