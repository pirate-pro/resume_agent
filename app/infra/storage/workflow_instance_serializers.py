"""Serializers for workflow instance records."""

from __future__ import annotations

from typing import Any

from app.core.errors import ValidationError
from app.core.time import from_app_iso, to_app_iso
from app.domain.workflow_instances import WorkflowInstanceRecord

__all__ = ["workflow_instance_from_payload", "workflow_instance_to_payload"]


def workflow_instance_to_payload(record: WorkflowInstanceRecord) -> dict[str, Any]:
    if record.created_at is None or record.updated_at is None:
        raise ValidationError("workflow instance timestamps are required.")
    return {
        "workflow_instance_id": record.workflow_instance_id,
        "workflow_id": record.workflow_id,
        "session_id": record.session_id,
        "thread_id": record.thread_id,
        "status": record.status,
        "phase": record.phase,
        "run_id": record.run_id,
        "pending_interrupt_payload": record.pending_interrupt_payload,
        "output_refs": record.output_refs,
        "last_error": record.last_error,
        "state_snapshot": record.state_snapshot,
        "created_at": to_app_iso(record.created_at),
        "updated_at": to_app_iso(record.updated_at),
        "completed_at": to_app_iso(record.completed_at) if record.completed_at is not None else None,
        "version": record.version,
    }


def workflow_instance_from_payload(payload: dict[str, Any]) -> WorkflowInstanceRecord:
    return WorkflowInstanceRecord(
        workflow_instance_id=str(payload["workflow_instance_id"]),
        workflow_id=str(payload["workflow_id"]),
        session_id=str(payload["session_id"]),
        thread_id=str(payload["thread_id"]),
        status=str(payload["status"]),
        phase=str(payload["phase"]),
        run_id=None if payload.get("run_id") is None else str(payload["run_id"]),
        pending_interrupt_payload=_optional_dict(payload.get("pending_interrupt_payload")),
        output_refs=_dict(payload.get("output_refs")),
        last_error=_optional_dict(payload.get("last_error")),
        state_snapshot=_dict(payload.get("state_snapshot")),
        created_at=from_app_iso(str(payload["created_at"])),
        updated_at=from_app_iso(str(payload["updated_at"])),
        completed_at=None if payload.get("completed_at") is None else from_app_iso(str(payload["completed_at"])),
        version=int(payload.get("version", 1)),
    )


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _optional_dict(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None
