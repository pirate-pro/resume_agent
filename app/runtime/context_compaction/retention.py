"""Retention strategies for context compaction."""

from __future__ import annotations

from app.runtime.context_compaction.models import ContextCompactionConfig, RetentionStrategy, SemanticUnit

__all__ = [
    "select_retained_units",
]


def select_retained_units(units: list[SemanticUnit], config: ContextCompactionConfig) -> list[SemanticUnit]:
    if config.retention_strategy == RetentionStrategy.EVENT_COUNT:
        return _retain_units_by_event_count(units, max_events=config.retain_event_count)
    if config.retention_strategy == RetentionStrategy.TOKEN_COUNT:
        return _retain_units_by_tokens(units, max_tokens=config.retain_token_count)
    max_tokens = int(config.model_context_window_tokens * config.retain_context_window_ratio)
    return _retain_units_by_tokens(units, max_tokens=max(1, max_tokens))


def _retain_units_by_event_count(units: list[SemanticUnit], *, max_events: int) -> list[SemanticUnit]:
    retained_reversed: list[SemanticUnit] = []
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


def _retain_units_by_tokens(units: list[SemanticUnit], *, max_tokens: int) -> list[SemanticUnit]:
    retained_reversed: list[SemanticUnit] = []
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
