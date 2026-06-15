"""Shared helpers for recoverable LangGraph write failures."""

from __future__ import annotations

from typing import Any, Literal, cast

from app.core.errors import ValidationError

WRITE_RETRY_INTERRUPT_TYPE = "workflow_write_retry"

WriteRetryAction = Literal["retry", "cancel"]


def write_failure_update(
    state: dict[str, Any],
    *,
    failed_node: str,
    error: str,
    retry_phase: str,
) -> dict[str, Any]:
    retry_counters = dict(state.get("retry_counters") or {})
    retry_counters[failed_node] = retry_counters.get(failed_node, 0) + 1
    return {
        "phase": retry_phase,
        "last_error": {
            "node": failed_node,
            "error": error[:500],
        },
        "retry_counters": retry_counters,
    }


def write_retry_interrupt_payload(
    state: dict[str, Any],
    *,
    question: str,
    operation_label: str,
) -> dict[str, Any]:
    raw_error = state.get("last_error")
    error = raw_error if isinstance(raw_error, dict) else {}
    failed_node = _string(error.get("node")) or "write"
    error_message = _string(error.get("error")) or "未知写入错误"
    retry_counters = state.get("retry_counters")
    counters = retry_counters if isinstance(retry_counters, dict) else {}
    retry_count = counters.get(failed_node, 1)
    return {
        "type": WRITE_RETRY_INTERRUPT_TYPE,
        "workflow_instance_id": state["workflow_instance_id"],
        "thread_id": state["thread_id"],
        "question": question,
        "failed_node": failed_node,
        "operation_label": operation_label,
        "error": error_message,
        "retry_count": retry_count if isinstance(retry_count, int) and retry_count > 0 else 1,
        "actions": ["retry", "cancel"],
    }


def parse_write_retry_action(answer: Any) -> WriteRetryAction:
    if not isinstance(answer, dict):
        raise ValidationError("write retry resume payload must be an object.")
    action = (_string(answer.get("action")) or "retry").lower()
    if action not in {"retry", "cancel"}:
        raise ValidationError("write retry action must be retry/cancel.")
    return cast(WriteRetryAction, action)


def failed_write_node(state: dict[str, Any]) -> str | None:
    raw_error = state.get("last_error")
    if not isinstance(raw_error, dict):
        return None
    return _string(raw_error.get("node"))


def _string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
