"""Short-term session event compaction.

Context compaction rewrites a session event stream into one model-generated
summary event plus recent raw events. It runs after mid-term flush so durable
memory has a chance to consume the raw events before they are compacted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
import json
import logging
import re
from typing import Any
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.models import EventRecord, RunContext
from app.domain.protocols import ChatModelClient, ModelResponse, SessionRepository
from app.runtime.agent_events import AGENT_RESULT_SUMMARY_EVENT, AGENT_TASK_ASSIGNED_EVENT

__all__ = [
    "CONTEXT_SUMMARY_EVENT",
    "ContextCompactionConfig",
    "ContextCompactionResult",
    "ContextCompactor",
    "RetentionStrategy",
]

_logger = logging.getLogger(__name__)
CONTEXT_SUMMARY_EVENT = "context_summary"
_MAX_TOOL_TEXT_LEN = 1200
_SUMMARY_MAX_CHARS = 6000
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_COMPACTOR_SYSTEM_PROMPT = """You are a session context compactor.
Your job is to compress old short-term runtime events into a faithful summary for future turns.

Rules:
1. Reconstruct the timeline in old-to-new order.
2. Treat semantic units as atomic. Tool call/result pairs must stay semantically paired.
3. Preserve user intent, agent decisions, unresolved questions, tool outcomes, file/artifact references, and memory-relevant facts.
4. Do not invent facts. If evidence is unclear, omit it.
5. Keep the summary concise but operationally useful for continuing the same session.
6. Output strict JSON only, with no Markdown fence.
"""


class RetentionStrategy(str, Enum):
    EVENT_COUNT = "event_count"
    TOKEN_COUNT = "token_count"
    CONTEXT_RATIO = "context_ratio"


@dataclass(slots=True)
class ContextCompactionConfig:
    enabled: bool = True
    trigger_event_count: int = 60
    trigger_token_count: int = 12000
    trigger_context_window_ratio: float = 0.45
    model_context_window_tokens: int = 32768
    retention_strategy: RetentionStrategy = RetentionStrategy.EVENT_COUNT
    retain_event_count: int = 32
    retain_token_count: int = 7000
    retain_context_window_ratio: float = 0.25
    model_input_ratio: float = 0.45
    model_output_reserve_tokens: int = 1600
    prompt_overhead_tokens: int = 900

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValidationError("context compaction enabled must be bool.")
        for name in (
            "trigger_event_count",
            "trigger_token_count",
            "model_context_window_tokens",
            "retain_event_count",
            "retain_token_count",
            "model_output_reserve_tokens",
            "prompt_overhead_tokens",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or value <= 0:
                raise ValidationError(f"{name} must be a positive integer.")
        for name in ("trigger_context_window_ratio", "retain_context_window_ratio", "model_input_ratio"):
            value = getattr(self, name)
            if not isinstance(value, float) and not isinstance(value, int):
                raise ValidationError(f"{name} must be numeric.")
            if float(value) <= 0 or float(value) >= 1:
                raise ValidationError(f"{name} must be in (0,1).")
            setattr(self, name, float(value))
        if not isinstance(self.retention_strategy, RetentionStrategy):
            try:
                self.retention_strategy = RetentionStrategy(str(self.retention_strategy))
            except ValueError as exc:
                raise ValidationError("retention_strategy is invalid.") from exc


@dataclass(slots=True)
class ContextCompactionResult:
    compacted: bool
    reason: str
    session_id: str
    agent_id: str
    original_event_count: int
    original_estimated_tokens: int
    compressed_event_count: int = 0
    retained_event_count: int = 0
    summary_event_id: str | None = None


@dataclass(slots=True)
class _SemanticUnit:
    unit_id: str
    unit_type: str
    event_ids: list[str]
    events: list[EventRecord]
    summary: dict[str, Any]
    created_at: datetime
    estimated_tokens: int

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "unit_type": self.unit_type,
            "event_ids": self.event_ids,
            "summary": self.summary,
            "events": [_normalize_event_for_prompt(event) for event in self.events],
            "estimated_tokens": self.estimated_tokens,
        }


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

        original_tokens = _estimate_tokens_from_events(events)
        if not self._should_compact(event_count=len(events), estimated_tokens=original_tokens):
            return ContextCompactionResult(
                compacted=False,
                reason="threshold_not_met",
                session_id=context.session_id,
                agent_id=context.agent_id,
                original_event_count=len(events),
                original_estimated_tokens=original_tokens,
            )

        units = _build_semantic_units(events)
        if len(units) < 2:
            return self._result(context=context, events=events, reason="not_enough_units", compacted=False)

        retained_units = self._select_retained_units(units)
        retained_ids = {unit.unit_id for unit in retained_units}
        compressed_units = [unit for unit in units if unit.unit_id not in retained_ids]
        if not compressed_units:
            return self._result(context=context, events=events, reason="nothing_to_compress", compacted=False)

        compressed_events = _collect_unique_events(compressed_units)
        retained_events = _collect_unique_events(retained_units)
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
            original_estimated_tokens=_estimate_tokens_from_events(events),
        )

    def _should_compact(self, *, event_count: int, estimated_tokens: int) -> bool:
        if event_count > self._config.trigger_event_count:
            return True
        if estimated_tokens > self._config.trigger_token_count:
            return True
        ratio_threshold = int(self._config.model_context_window_tokens * self._config.trigger_context_window_ratio)
        return estimated_tokens >= ratio_threshold

    def _select_retained_units(self, units: list[_SemanticUnit]) -> list[_SemanticUnit]:
        if self._config.retention_strategy == RetentionStrategy.EVENT_COUNT:
            return _retain_units_by_event_count(units, max_events=self._config.retain_event_count)
        if self._config.retention_strategy == RetentionStrategy.TOKEN_COUNT:
            return _retain_units_by_tokens(units, max_tokens=self._config.retain_token_count)
        max_tokens = int(self._config.model_context_window_tokens * self._config.retain_context_window_ratio)
        return _retain_units_by_tokens(units, max_tokens=max(1, max_tokens))

    def _summarize(
        self,
        *,
        context: RunContext,
        compressed_units: list[_SemanticUnit],
        retained_units: list[_SemanticUnit],
        original_event_count: int,
        original_estimated_tokens: int,
    ) -> dict[str, Any]:
        prompt = _build_compaction_prompt(
            context=context,
            compressed_units=compressed_units,
            retained_units=retained_units,
            original_event_count=original_event_count,
            original_estimated_tokens=original_estimated_tokens,
            input_budget_tokens=self._input_budget_tokens(),
        )
        response = self._model_client.generate(
            system_prompt=_COMPACTOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            tools=[],
        )
        if not isinstance(response, ModelResponse):
            raise ValidationError("context compactor model response type is invalid.")
        payload = _parse_json_object((response.content or "").strip())
        return _validate_compaction_payload(payload, compressed_units=compressed_units)

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
            "compacted_at": _format_iso(datetime.now(UTC)),
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


def _build_semantic_units(events: list[EventRecord]) -> list[_SemanticUnit]:
    message_types = {"user_message", "assistant_message", "assistant_thinking"}
    units: list[_SemanticUnit] = []
    buffered_messages: list[EventRecord] = []
    pending_tool_calls: dict[str, EventRecord] = {}
    pending_agent_tasks: dict[str, EventRecord] = {}

    def flush_messages() -> None:
        nonlocal buffered_messages
        if not buffered_messages:
            return
        event_ids = [event.event_id for event in buffered_messages]
        summary = {
            "user_messages": [
                _safe_text(event.payload.get("content"))
                for event in buffered_messages
                if event.type == "user_message" and _safe_text(event.payload.get("content"))
            ],
            "assistant_messages": [
                _safe_text(event.payload.get("content"))
                for event in buffered_messages
                if event.type in {"assistant_message", "assistant_thinking"}
                and _safe_text(event.payload.get("content"))
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
            tool_call_id = _payload_text(event.payload, "tool_call_id")
            if tool_call_id:
                pending_tool_calls[tool_call_id] = event
            else:
                units.append(_make_unit("tool_call_orphan", [event], _tool_call_summary(event)))
            continue

        if event.type == "tool_result":
            tool_call_id = _payload_text(event.payload, "tool_call_id")
            call_event = pending_tool_calls.pop(tool_call_id, None) if tool_call_id else None
            if call_event is None:
                units.append(_make_unit("tool_result_orphan", [event], _tool_result_summary(event)))
            else:
                units.append(_make_unit("tool_pair", [call_event, event], _tool_pair_summary(call_event, event)))
            continue

        if event.type == AGENT_TASK_ASSIGNED_EVENT:
            task_id = _payload_text(event.payload, "task_id")
            if task_id:
                pending_agent_tasks[task_id] = event
            else:
                units.append(_make_unit("agent_task_orphan", [event], _agent_task_summary(event)))
            continue

        if event.type == AGENT_RESULT_SUMMARY_EVENT:
            task_id = _payload_text(event.payload, "task_id")
            task_event = pending_agent_tasks.pop(task_id, None) if task_id else None
            if task_event is None:
                units.append(_make_unit("agent_result_orphan", [event], _agent_result_summary(event)))
            else:
                units.append(_make_unit("agent_task_result_pair", [task_event, event], _agent_pair_summary(task_event, event)))
            continue

        units.append(_make_unit(event.type, [event], _generic_event_summary(event)))

    flush_messages()

    for event in sorted(pending_tool_calls.values(), key=lambda item: item.created_at):
        units.append(_make_unit("tool_call_orphan", [event], _tool_call_summary(event)))
    for event in sorted(pending_agent_tasks.values(), key=lambda item: item.created_at):
        units.append(_make_unit("agent_task_orphan", [event], _agent_task_summary(event)))

    units.sort(key=lambda unit: unit.created_at)
    return units


def _make_unit(unit_type: str, events: list[EventRecord], summary: dict[str, Any]) -> _SemanticUnit:
    event_ids = [event.event_id for event in events]
    payload = {
        "unit_type": unit_type,
        "event_ids": event_ids,
        "summary": summary,
        "events": [_normalize_event_for_prompt(event) for event in events],
    }
    return _SemanticUnit(
        unit_id=f"unit_{unit_type}_{event_ids[0]}",
        unit_type=unit_type,
        event_ids=event_ids,
        events=events,
        summary=summary,
        created_at=events[-1].created_at,
        estimated_tokens=_estimate_tokens_from_object(payload),
    )


def _retain_units_by_event_count(units: list[_SemanticUnit], *, max_events: int) -> list[_SemanticUnit]:
    retained_reversed: list[_SemanticUnit] = []
    event_count = 0
    for unit in reversed(units):
        unit_event_count = len(unit.events)
        if retained_reversed and event_count + unit_event_count > max_events:
            break
        retained_reversed.append(unit)
        event_count += unit_event_count
    if not retained_reversed:
        retained_reversed.append(units[-1])
    return list(reversed(retained_reversed))


def _retain_units_by_tokens(units: list[_SemanticUnit], *, max_tokens: int) -> list[_SemanticUnit]:
    retained_reversed: list[_SemanticUnit] = []
    token_count = 0
    for unit in reversed(units):
        estimated = max(1, unit.estimated_tokens)
        if retained_reversed and token_count + estimated > max_tokens:
            break
        retained_reversed.append(unit)
        token_count += estimated
    if not retained_reversed:
        retained_reversed.append(units[-1])
    return list(reversed(retained_reversed))


def _collect_unique_events(units: list[_SemanticUnit]) -> list[EventRecord]:
    output: list[EventRecord] = []
    seen: set[str] = set()
    for unit in units:
        for event in unit.events:
            if event.event_id in seen:
                continue
            output.append(event)
            seen.add(event.event_id)
    return output


def _build_compaction_prompt(
    *,
    context: RunContext,
    compressed_units: list[_SemanticUnit],
    retained_units: list[_SemanticUnit],
    original_event_count: int,
    original_estimated_tokens: int,
    input_budget_tokens: int,
) -> str:
    schema = {
        "summary": "string",
        "timeline": ["string"],
        "decisions": ["string"],
        "open_threads": ["string"],
        "tool_progress": [
            {
                "tool_name": "string",
                "call_summary": "string",
                "result_summary": "string",
                "success": True,
                "evidence_event_ids": ["evt_call", "evt_result"],
            }
        ],
        "agent_activity": ["string"],
        "memory_relevant": ["string"],
        "evidence_event_ids": ["evt_xxx"],
    }
    payload = {
        "task": "Compress only compressed_units. retained_units stay as raw events after the summary.",
        "session_id": context.session_id,
        "agent_id": context.agent_id,
        "timeline_order": "old_to_new",
        "original_event_count": original_event_count,
        "original_estimated_tokens": original_estimated_tokens,
        "input_budget_tokens": input_budget_tokens,
        "required_schema": schema,
        "compressed_units": [unit.to_prompt_payload() for unit in compressed_units],
        "retained_units_preview": [unit.to_prompt_payload() for unit in retained_units[-6:]],
    }
    return (
        "Compress these old session events into one structured context summary.\n"
        "Think through the timeline internally, but output only the required JSON object.\n"
        "The summary will be prepended before retained raw events, so avoid duplicating recent retained details.\n"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )


def _validate_compaction_payload(payload: dict[str, Any], *, compressed_units: list[_SemanticUnit]) -> dict[str, Any]:
    summary = _optional_text(payload.get("summary"), max_len=_SUMMARY_MAX_CHARS)
    if summary is None:
        raise ValidationError("compaction output missing summary.")
    valid_ids = {event_id for unit in compressed_units for event_id in unit.event_ids}
    evidence = _normalize_event_ids(payload.get("evidence_event_ids"), valid_ids)
    if not evidence:
        evidence = sorted(valid_ids)
    return {
        "summary": summary,
        "timeline": _string_list(payload.get("timeline"), max_items=12),
        "decisions": _string_list(payload.get("decisions"), max_items=12),
        "open_threads": _string_list(payload.get("open_threads"), max_items=12),
        "tool_progress": _tool_progress_list(payload.get("tool_progress"), valid_ids),
        "agent_activity": _string_list(payload.get("agent_activity"), max_items=12),
        "memory_relevant": _string_list(payload.get("memory_relevant"), max_items=12),
        "evidence_event_ids": evidence,
    }


def _tool_progress_list(raw: Any, valid_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    output: list[dict[str, Any]] = []
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        tool_name = _optional_text(item.get("tool_name"), max_len=120)
        call_summary = _optional_text(item.get("call_summary"), max_len=400)
        result_summary = _optional_text(item.get("result_summary"), max_len=500)
        evidence = _normalize_event_ids(item.get("evidence_event_ids"), valid_ids)
        if tool_name is None or call_summary is None or result_summary is None or not evidence:
            continue
        output.append(
            {
                "tool_name": tool_name,
                "call_summary": call_summary,
                "result_summary": result_summary,
                "success": bool(item.get("success")),
                "evidence_event_ids": evidence,
            }
        )
    return output


def _normalize_event_for_prompt(event: EventRecord) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_id": event.event_id,
        "type": event.type,
        "agent_id": event.agent_id,
        "run_id": event.run_id,
        "parent_run_id": event.parent_run_id,
        "created_at": _format_iso(event.created_at),
    }
    payload = event.payload
    if event.type in {"user_message", "assistant_message", "assistant_thinking"}:
        base["text"] = _safe_text(payload.get("content"))
    elif event.type == "tool_call":
        base["tool_name"] = _safe_text(payload.get("name"), max_len=120)
        base["tool_call_id"] = _payload_text(payload, "tool_call_id")
        base["arguments"] = _compact_json(payload.get("arguments"), max_len=_MAX_TOOL_TEXT_LEN)
    elif event.type == "tool_result":
        base["tool_name"] = _safe_text(payload.get("tool_name"), max_len=120)
        base["tool_call_id"] = _payload_text(payload, "tool_call_id")
        base["success"] = bool(payload.get("success"))
        base["result"] = _safe_text(payload.get("content"), max_len=_MAX_TOOL_TEXT_LEN)
    elif event.type == CONTEXT_SUMMARY_EVENT:
        base["summary"] = _safe_text(payload.get("summary") or payload.get("content"), max_len=_SUMMARY_MAX_CHARS)
    else:
        base["payload"] = _compact_json(payload, max_len=_MAX_TOOL_TEXT_LEN)
    return base


def _tool_call_summary(event: EventRecord) -> dict[str, Any]:
    return {
        "tool_name": _safe_text(event.payload.get("name"), max_len=120),
        "arguments": _compact_json(event.payload.get("arguments"), max_len=_MAX_TOOL_TEXT_LEN),
    }


def _tool_result_summary(event: EventRecord) -> dict[str, Any]:
    return {
        "tool_name": _safe_text(event.payload.get("tool_name"), max_len=120),
        "success": bool(event.payload.get("success")),
        "result": _safe_text(event.payload.get("content"), max_len=_MAX_TOOL_TEXT_LEN),
    }


def _tool_pair_summary(call_event: EventRecord, result_event: EventRecord) -> dict[str, Any]:
    return {
        "tool_name": _safe_text(call_event.payload.get("name"), max_len=120)
        or _safe_text(result_event.payload.get("tool_name"), max_len=120),
        "call_arguments": _compact_json(call_event.payload.get("arguments"), max_len=_MAX_TOOL_TEXT_LEN),
        "result_success": bool(result_event.payload.get("success")),
        "result_content": _safe_text(result_event.payload.get("content"), max_len=_MAX_TOOL_TEXT_LEN),
    }


def _agent_task_summary(event: EventRecord) -> dict[str, Any]:
    return {
        "task_id": _payload_text(event.payload, "task_id"),
        "source_agent_id": _payload_text(event.payload, "source_agent_id"),
        "target_agent_id": _payload_text(event.payload, "target_agent_id"),
        "instruction": _safe_text(event.payload.get("instruction"), max_len=800),
    }


def _agent_result_summary(event: EventRecord) -> dict[str, Any]:
    return {
        "task_id": _payload_text(event.payload, "task_id"),
        "source_agent_id": _payload_text(event.payload, "source_agent_id"),
        "target_agent_id": _payload_text(event.payload, "target_agent_id"),
        "status": _payload_text(event.payload, "status"),
        "summary": _safe_text(event.payload.get("summary"), max_len=800),
    }


def _agent_pair_summary(task_event: EventRecord, result_event: EventRecord) -> dict[str, Any]:
    return {
        "task": _agent_task_summary(task_event),
        "result": _agent_result_summary(result_event),
    }


def _generic_event_summary(event: EventRecord) -> dict[str, Any]:
    return {"type": event.type, "payload": _compact_json(event.payload, max_len=_MAX_TOOL_TEXT_LEN)}


def _payload_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _string_list(raw: Any, *, max_items: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    for item in raw[:max_items]:
        text = _optional_text(item, max_len=600)
        if text is not None:
            output.append(text)
    return output


def _normalize_event_ids(raw: Any, valid_ids: set[str]) -> list[str]:
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        event_id = item.strip()
        if not event_id or event_id not in valid_ids or event_id in seen:
            continue
        output.append(event_id)
        seen.add(event_id)
    return output


def _parse_json_object(text: str) -> dict[str, Any]:
    if not text:
        raise ValidationError("compaction output is empty.")
    candidates = [text]
    fence_start = text.find("```")
    fence_end = text.rfind("```")
    if fence_start != -1 and fence_end > fence_start:
        fenced = text[fence_start + 3 : fence_end].strip()
        if fenced.lower().startswith("json"):
            fenced = fenced[4:].strip()
        candidates.append(fenced)
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return {str(key): value for key, value in payload.items()}
    raise ValidationError("compaction output is not valid JSON object.")


def _estimate_tokens_from_events(events: list[EventRecord]) -> int:
    return sum(_estimate_tokens_from_object(_normalize_event_for_prompt(event)) for event in events)


def _estimate_tokens_from_object(value: Any) -> int:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(value)
    return _estimate_tokens_from_text(text)


def _estimate_tokens_from_text(text: str) -> int:
    if not text:
        return 0
    cjk_count = len(_CJK_PATTERN.findall(text))
    non_cjk_len = max(0, len(text) - cjk_count)
    ascii_token_estimate = (non_cjk_len + 3) // 4
    return max(1, cjk_count + ascii_token_estimate)


def _compact_json(raw: Any, *, max_len: int) -> str:
    try:
        text = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(raw)
    return _safe_text(text, max_len=max_len) or ""


def _safe_text(raw: Any, *, max_len: int = 2000) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _optional_text(raw: Any, *, max_len: int = 2000) -> str | None:
    return _safe_text(raw, max_len=max_len)


def _format_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
