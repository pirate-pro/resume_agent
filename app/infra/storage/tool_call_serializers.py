"""Payload serializers for durable tool call storage."""

from __future__ import annotations

from typing import Any

from app.domain.tool_calls import ToolCallRecord
from app.infra.storage.session_io import from_iso, to_iso

__all__ = ["tool_call_from_payload", "tool_call_to_payload"]


def tool_call_to_payload(record: ToolCallRecord) -> dict[str, Any]:
    if record.created_at is None or record.updated_at is None:
        raise ValueError("tool call created_at/updated_at are required.")
    return {
        "tool_call_record_id": record.tool_call_record_id,
        "session_id": record.session_id,
        "run_id": record.run_id,
        "agent_id": record.agent_id,
        "task_id": record.task_id,
        "tool_name": record.tool_name,
        "tool_call_id": record.tool_call_id,
        "input_hash": record.input_hash,
        "idempotency_key": record.idempotency_key,
        "status": record.status,
        "arguments": record.arguments,
        "result_content": record.result_content,
        "result_refs": record.result_refs,
        "error": record.error,
        "created_at": to_iso(record.created_at),
        "updated_at": to_iso(record.updated_at),
        "completed_at": None if record.completed_at is None else to_iso(record.completed_at),
    }


def tool_call_from_payload(payload: dict[str, Any]) -> ToolCallRecord:
    raw_arguments = payload.get("arguments")
    raw_result_refs = payload.get("result_refs")
    return ToolCallRecord(
        tool_call_record_id=str(payload["tool_call_record_id"]),
        session_id=str(payload["session_id"]),
        run_id=str(payload["run_id"]),
        agent_id=str(payload["agent_id"]),
        task_id=_optional_string(payload.get("task_id")),
        tool_name=str(payload["tool_name"]),
        tool_call_id=_optional_string(payload.get("tool_call_id")),
        input_hash=_optional_string(payload.get("input_hash")),
        idempotency_key=_optional_string(payload.get("idempotency_key")),
        status=str(payload["status"]),
        arguments=raw_arguments if isinstance(raw_arguments, dict) else {},
        result_content=_optional_string(payload.get("result_content")),
        result_refs=raw_result_refs if isinstance(raw_result_refs, dict) else {},
        error=_optional_string(payload.get("error")),
        created_at=from_iso(str(payload["created_at"])),
        updated_at=from_iso(str(payload["updated_at"])),
        completed_at=None if payload.get("completed_at") is None else from_iso(str(payload["completed_at"])),
    )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
