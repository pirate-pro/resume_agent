"""Short-term session event compaction.

Context compaction rewrites a session event stream into one model-generated
summary event plus recent raw events. It runs after mid-term flush so durable
memory has a chance to consume the raw events before they are compacted.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.models import EventRecord, RunContext
from app.domain.protocols import ChatModelClient, ModelResponse, SessionRepository
from app.prompts.context_compaction import CONTEXT_COMPACTOR_SYSTEM_PROMPT, build_context_compaction_prompt
from app.runtime.context_compaction import (
    CONTEXT_SUMMARY_EVENT,
    ContextCompactionConfig,
    ContextCompactionResult,
    RetentionStrategy,
    SemanticUnit,
)
from app.runtime.context_compaction.event_projection import estimate_tokens_from_events
from app.runtime.context_compaction.payload_validation import validate_compaction_payload
from app.runtime.context_compaction.retention import select_retained_units
from app.runtime.context_compaction.semantic_units import build_semantic_units, collect_unique_events
from app.runtime.context_compaction.text_utils import format_iso, parse_json_object

__all__ = [
    "CONTEXT_SUMMARY_EVENT",
    "ContextCompactionConfig",
    "ContextCompactionResult",
    "ContextCompactor",
    "RetentionStrategy",
]

_logger = logging.getLogger(__name__)


class ContextCompactor:
    """Compact session events after flush has consumed raw history."""

    def __init__(
        self,
        *,
        session_repository: SessionRepository,
        model_client: ChatModelClient,
        config: ContextCompactionConfig | None = None,
    ) -> None:
        self._session_repository = session_repository
        self._model_client = model_client
        self._config = config or ContextCompactionConfig()

    def compact_after_flush(self, context: RunContext) -> ContextCompactionResult:
        if not isinstance(context, RunContext):
            raise ValidationError("context must be RunContext.")
        events = self._session_repository.list_events(context.session_id)
        return self.compact_events(context=context, events=events)

    def compact_events(self, *, context: RunContext, events: list[EventRecord]) -> ContextCompactionResult:
        if not self._config.enabled:
            return self._result(context=context, events=events, reason="disabled", compacted=False)
        if not events:
            return self._result(context=context, events=events, reason="no_events", compacted=False)

        original_tokens = estimate_tokens_from_events(events)
        if not self._should_compact(event_count=len(events), estimated_tokens=original_tokens):
            return ContextCompactionResult(
                compacted=False,
                reason="threshold_not_met",
                session_id=context.session_id,
                agent_id=context.agent_id,
                original_event_count=len(events),
                original_estimated_tokens=original_tokens,
            )

        units = build_semantic_units(events)
        if len(units) < 2:
            return self._result(context=context, events=events, reason="not_enough_units", compacted=False)

        retained_units = select_retained_units(units, self._config)
        retained_ids = {unit.unit_id for unit in retained_units}
        compressed_units = [unit for unit in units if unit.unit_id not in retained_ids]
        if not compressed_units:
            return self._result(context=context, events=events, reason="nothing_to_compress", compacted=False)

        compressed_events = collect_unique_events(compressed_units)
        retained_events = collect_unique_events(retained_units)
        if not compressed_events or not retained_events:
            return self._result(context=context, events=events, reason="invalid_compaction_split", compacted=False)

        summary_payload = self._summarize(
            context=context,
            compressed_units=compressed_units,
            retained_units=retained_units,
            original_event_count=len(events),
            original_estimated_tokens=original_tokens,
        )
        summary_event = self._build_summary_event(
            context=context,
            summary_payload=summary_payload,
            compressed_events=compressed_events,
            retained_events=retained_events,
        )
        new_events = [summary_event] + retained_events
        replaced = self._session_repository.replace_events_if_unchanged(
            context.session_id,
            new_events,
            expected_last_event_id=events[-1].event_id,
        )
        if not replaced:
            return ContextCompactionResult(
                compacted=False,
                reason="events_changed_during_compaction",
                session_id=context.session_id,
                agent_id=context.agent_id,
                original_event_count=len(events),
                original_estimated_tokens=original_tokens,
            )
        _logger.info(
            "context compaction completed: session_id=%s agent_id=%s original_events=%s compressed=%s retained=%s summary=%s",
            context.session_id,
            context.agent_id,
            len(events),
            len(compressed_events),
            len(retained_events),
            summary_event.event_id,
        )
        return ContextCompactionResult(
            compacted=True,
            reason="compacted",
            session_id=context.session_id,
            agent_id=context.agent_id,
            original_event_count=len(events),
            original_estimated_tokens=original_tokens,
            compressed_event_count=len(compressed_events),
            retained_event_count=len(retained_events),
            summary_event_id=summary_event.event_id,
        )

    def _result(
        self,
        *,
        context: RunContext,
        events: list[EventRecord],
        reason: str,
        compacted: bool,
    ) -> ContextCompactionResult:
        return ContextCompactionResult(
            compacted=compacted,
            reason=reason,
            session_id=context.session_id,
            agent_id=context.agent_id,
            original_event_count=len(events),
            original_estimated_tokens=estimate_tokens_from_events(events),
        )

    def _should_compact(self, *, event_count: int, estimated_tokens: int) -> bool:
        if event_count > self._config.trigger_event_count:
            return True
        if estimated_tokens > self._config.trigger_token_count:
            return True
        ratio_threshold = int(self._config.model_context_window_tokens * self._config.trigger_context_window_ratio)
        return estimated_tokens >= ratio_threshold

    def _summarize(
        self,
        *,
        context: RunContext,
        compressed_units: list[SemanticUnit],
        retained_units: list[SemanticUnit],
        original_event_count: int,
        original_estimated_tokens: int,
    ) -> dict[str, Any]:
        prompt = build_context_compaction_prompt(
            context=context,
            compressed_units=[unit.to_prompt_payload() for unit in compressed_units],
            retained_units_preview=[unit.to_prompt_payload() for unit in retained_units[-6:]],
            original_event_count=original_event_count,
            original_estimated_tokens=original_estimated_tokens,
            input_budget_tokens=self._input_budget_tokens(),
        )
        response = self._model_client.generate(
            system_prompt=CONTEXT_COMPACTOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            tools=[],
        )
        if not isinstance(response, ModelResponse):
            raise ValidationError("context compactor model response type is invalid.")
        payload = parse_json_object((response.content or "").strip())
        return validate_compaction_payload(payload, compressed_units=compressed_units)

    def _input_budget_tokens(self) -> int:
        dynamic_budget = int(self._config.model_context_window_tokens * self._config.model_input_ratio)
        return max(1024, dynamic_budget - self._config.model_output_reserve_tokens - self._config.prompt_overhead_tokens)

    def _build_summary_event(
        self,
        *,
        context: RunContext,
        summary_payload: dict[str, Any],
        compressed_events: list[EventRecord],
        retained_events: list[EventRecord],
    ) -> EventRecord:
        summary = str(summary_payload["summary"]).strip()
        payload = {
            "content": summary,
            "summary": summary,
            "structured": summary_payload,
            "compressed_event_count": len(compressed_events),
            "retained_event_count": len(retained_events),
            "compressed_event_ids": [event.event_id for event in compressed_events],
            "retained_event_ids": [event.event_id for event in retained_events],
            "first_compressed_event_id": compressed_events[0].event_id,
            "last_compressed_event_id": compressed_events[-1].event_id,
            "compacted_at": format_iso(datetime.now(UTC)),
        }
        return EventRecord(
            event_id=f"evt_{uuid4().hex[:12]}",
            session_id=context.session_id,
            type=CONTEXT_SUMMARY_EVENT,
            payload=payload,
            created_at=datetime.now(UTC),
            agent_id=context.agent_id,
            run_id=context.run_id,
            parent_run_id=context.parent_run_id,
            event_version=2,
        )
