"""Payload serializers for durable agent task storage."""

from __future__ import annotations

from typing import Any

from app.domain.agent_tasks import AgentTaskGroupRecord, AgentTaskRecord
from app.infra.storage.session_io import from_iso, to_iso

__all__ = [
    "task_from_payload",
    "task_group_from_payload",
    "task_group_to_payload",
    "task_to_payload",
]


def task_group_to_payload(record: AgentTaskGroupRecord) -> dict[str, Any]:
    return {
        "task_group_id": record.task_group_id,
        "session_id": record.session_id,
        "source_agent_id": record.source_agent_id,
        "source_run_id": record.source_run_id,
        "status": record.status,
        "max_concurrency": record.max_concurrency,
        "task_ids": record.task_ids,
        "created_at": to_iso(record.created_at),
        "updated_at": to_iso(record.updated_at),
    }


def task_group_from_payload(payload: dict[str, Any]) -> AgentTaskGroupRecord:
    return AgentTaskGroupRecord(
        task_group_id=str(payload["task_group_id"]),
        session_id=str(payload["session_id"]),
        source_agent_id=str(payload["source_agent_id"]),
        source_run_id=str(payload["source_run_id"]),
        status=str(payload["status"]),
        max_concurrency=int(payload["max_concurrency"]),
        task_ids=[str(item) for item in payload.get("task_ids", []) if str(item).strip()],
        created_at=from_iso(str(payload["created_at"])),
        updated_at=from_iso(str(payload["updated_at"])),
    )


def task_to_payload(record: AgentTaskRecord) -> dict[str, Any]:
    if record.created_at is None or record.updated_at is None:
        raise ValueError("task created_at/updated_at are required.")
    return {
        "task_id": record.task_id,
        "task_group_id": record.task_group_id,
        "session_id": record.session_id,
        "source_agent_id": record.source_agent_id,
        "source_run_id": record.source_run_id,
        "target_agent_id": record.target_agent_id,
        "instruction": record.instruction,
        "constraints": record.constraints,
        "artifact_refs": record.artifact_refs,
        "skill_names": record.skill_names,
        "max_tool_rounds": record.max_tool_rounds,
        "status": record.status,
        "child_run_id": record.child_run_id,
        "summary": record.summary,
        "answer": record.answer,
        "error": record.error,
        "created_at": to_iso(record.created_at),
        "started_at": None if record.started_at is None else to_iso(record.started_at),
        "completed_at": None if record.completed_at is None else to_iso(record.completed_at),
        "updated_at": to_iso(record.updated_at),
    }


def task_from_payload(payload: dict[str, Any]) -> AgentTaskRecord:
    return AgentTaskRecord(
        task_id=str(payload["task_id"]),
        task_group_id=str(payload["task_group_id"]),
        session_id=str(payload["session_id"]),
        source_agent_id=str(payload["source_agent_id"]),
        source_run_id=str(payload["source_run_id"]),
        target_agent_id=str(payload["target_agent_id"]),
        instruction=str(payload["instruction"]),
        constraints=[str(item) for item in payload.get("constraints", []) if str(item).strip()],
        artifact_refs=[str(item) for item in payload.get("artifact_refs", []) if str(item).strip()],
        skill_names=[str(item) for item in payload.get("skill_names", []) if str(item).strip()],
        max_tool_rounds=int(payload.get("max_tool_rounds", 10)),
        status=str(payload["status"]),
        child_run_id=_payload_optional_string(payload.get("child_run_id")),
        summary=_payload_optional_string(payload.get("summary")),
        answer=_payload_optional_string(payload.get("answer")),
        error=_payload_optional_string(payload.get("error")),
        created_at=from_iso(str(payload["created_at"])),
        started_at=None if payload.get("started_at") is None else from_iso(str(payload["started_at"])),
        completed_at=None if payload.get("completed_at") is None else from_iso(str(payload["completed_at"])),
        updated_at=from_iso(str(payload["updated_at"])),
    )


def _payload_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
