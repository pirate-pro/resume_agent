"""Data models for short-term context compaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from app.core.errors import ValidationError
from app.domain.models import EventRecord

__all__ = [
    "CONTEXT_SUMMARY_EVENT",
    "ContextCompactionConfig",
    "ContextCompactionResult",
    "RetentionStrategy",
    "SemanticUnit",
]

CONTEXT_SUMMARY_EVENT = "context_summary"


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
class SemanticUnit:
    unit_id: str
    unit_type: str
    event_ids: list[str]
    events: list[EventRecord]
    summary: dict[str, Any]
    created_at: datetime
    estimated_tokens: int

    def to_prompt_payload(self) -> dict[str, Any]:
        from app.runtime.context_compaction.event_projection import normalize_event_for_prompt

        return {
            "unit_id": self.unit_id,
            "unit_type": self.unit_type,
            "event_ids": self.event_ids,
            "summary": self.summary,
            "events": [normalize_event_for_prompt(event) for event in self.events],
            "estimated_tokens": self.estimated_tokens,
        }
