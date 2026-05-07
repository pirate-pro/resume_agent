"""JSONL-backed durable agent task store."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import SessionNotFoundError, StorageError, ValidationError
from app.domain.agent_tasks import (
    AgentTaskGroupRecord,
    AgentTaskRecord,
    AgentTaskSpec,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_RUNNING,
    derive_group_status,
)
from app.infra.storage.agent_task_serializers import (
    task_from_payload,
    task_group_from_payload,
    task_group_to_payload,
    task_to_payload,
)
from app.infra.storage.session_io import utc_now

__all__ = ["JsonlAgentTaskStore"]


class JsonlAgentTaskStore:
    """Store session-scoped agent task groups and task records."""

    def __init__(self, data_dir: Path) -> None:
        if not isinstance(data_dir, Path):
            raise ValidationError("data_dir must be a pathlib.Path.")
        self._data_dir = data_dir
        self._sessions_dir = self._data_dir / "sessions"
        self._lock = threading.RLock()

    def create_group(
        self,
        *,
        session_id: str,
        source_agent_id: str,
        source_run_id: str,
        max_concurrency: int,
        specs: list[AgentTaskSpec],
    ) -> AgentTaskGroupRecord:
        session_id = self._validate_session_id(session_id)
        source_agent_id = self._validate_agent_id(source_agent_id)
        source_run_id = self._require_non_empty("source_run_id", source_run_id)
        if max_concurrency <= 0:
            raise ValidationError("max_concurrency must be positive.")
        if not isinstance(specs, list) or not specs:
            raise ValidationError("specs must be a non-empty list.")
        for spec in specs:
            if not isinstance(spec, AgentTaskSpec):
                raise ValidationError("specs entries must be AgentTaskSpec.")

        now = utc_now()
        group_id = f"task_group_{uuid4().hex[:12]}"
        task_ids = [f"task_{uuid4().hex[:12]}" for _ in specs]
        group = AgentTaskGroupRecord(
            task_group_id=group_id,
            session_id=session_id,
            source_agent_id=source_agent_id,
            source_run_id=source_run_id,
            status="queued",
            max_concurrency=max_concurrency,
            task_ids=task_ids,
            created_at=now,
            updated_at=now,
        )
        tasks = [
            AgentTaskRecord(
                task_id=task_id,
                task_group_id=group_id,
                session_id=session_id,
                source_agent_id=source_agent_id,
                source_run_id=source_run_id,
                target_agent_id=spec.target_agent_id,
                instruction=spec.instruction,
                constraints=list(spec.constraints),
                artifact_refs=list(spec.artifact_refs),
                skill_names=list(spec.skill_names),
                max_tool_rounds=spec.max_tool_rounds,
                status="queued",
                created_at=now,
                updated_at=now,
            )
            for task_id, spec in zip(task_ids, specs, strict=True)
        ]
        with self._lock:
            self._ensure_session_dir(session_id)
            groups = self._read_groups(session_id)
            existing_tasks = self._read_tasks(session_id)
            groups.append(group)
            existing_tasks.extend(tasks)
            self._write_groups(session_id, groups)
            self._write_tasks(session_id, existing_tasks)
        return group.copy()

    def get_group(self, session_id: str, task_group_id: str) -> AgentTaskGroupRecord | None:
        session_id = self._validate_session_id(session_id)
        task_group_id = self._validate_task_group_id(task_group_id)
        with self._lock:
            self._ensure_session_dir(session_id)
            for group in self._read_groups(session_id):
                if group.task_group_id == task_group_id:
                    return group.copy()
        return None

    def list_group_tasks(self, session_id: str, task_group_id: str) -> list[AgentTaskRecord]:
        session_id = self._validate_session_id(session_id)
        task_group_id = self._validate_task_group_id(task_group_id)
        with self._lock:
            self._ensure_session_dir(session_id)
            group = self.get_group(session_id, task_group_id)
            if group is None:
                raise ValidationError(f"Unknown task_group_id: {task_group_id}")
            task_by_id = {task.task_id: task for task in self._read_tasks(session_id)}
            missing_task_ids = [task_id for task_id in group.task_ids if task_id not in task_by_id]
            if missing_task_ids:
                raise StorageError(
                    f"Agent task group '{task_group_id}' references missing tasks: {', '.join(missing_task_ids)}"
                )
            return [task_by_id[task_id].copy() for task_id in group.task_ids]

    def get_task(self, session_id: str, task_id: str) -> AgentTaskRecord | None:
        session_id = self._validate_session_id(session_id)
        task_id = self._validate_task_id(task_id)
        with self._lock:
            self._ensure_session_dir(session_id)
            for task in self._read_tasks(session_id):
                if task.task_id == task_id:
                    return task.copy()
        return None

    def mark_running(self, session_id: str, task_id: str, *, child_run_id: str) -> AgentTaskRecord:
        child_run_id = self._require_non_empty("child_run_id", child_run_id)
        return self._update_task(
            session_id,
            task_id,
            status=TASK_STATUS_RUNNING,
            child_run_id=child_run_id,
            started=True,
        )

    def mark_completed(
        self,
        session_id: str,
        task_id: str,
        *,
        summary: str,
        answer: str,
        artifact_refs: list[str],
    ) -> AgentTaskRecord:
        return self._update_task(
            session_id,
            task_id,
            status=TASK_STATUS_COMPLETED,
            summary=self._require_non_empty("summary", summary),
            answer=self._require_non_empty("answer", answer),
            artifact_refs=artifact_refs,
            completed=True,
            clear_error=True,
        )

    def mark_failed(self, session_id: str, task_id: str, *, error: str) -> AgentTaskRecord:
        return self._update_task(
            session_id,
            task_id,
            status=TASK_STATUS_FAILED,
            error=self._require_non_empty("error", error),
            completed=True,
        )

    def _update_task(
        self,
        session_id: str,
        task_id: str,
        *,
        status: str,
        child_run_id: str | None = None,
        summary: str | None = None,
        answer: str | None = None,
        artifact_refs: list[str] | None = None,
        error: str | None = None,
        started: bool = False,
        completed: bool = False,
        clear_error: bool = False,
    ) -> AgentTaskRecord:
        session_id = self._validate_session_id(session_id)
        task_id = self._validate_task_id(task_id)
        now = utc_now()
        with self._lock:
            self._ensure_session_dir(session_id)
            tasks = self._read_tasks(session_id)
            updated: AgentTaskRecord | None = None
            output_tasks: list[AgentTaskRecord] = []
            for task in tasks:
                if task.task_id != task_id:
                    output_tasks.append(task)
                    continue
                updated = AgentTaskRecord(
                    task_id=task.task_id,
                    task_group_id=task.task_group_id,
                    session_id=task.session_id,
                    source_agent_id=task.source_agent_id,
                    source_run_id=task.source_run_id,
                    target_agent_id=task.target_agent_id,
                    instruction=task.instruction,
                    constraints=task.constraints,
                    artifact_refs=artifact_refs if artifact_refs is not None else task.artifact_refs,
                    skill_names=task.skill_names,
                    max_tool_rounds=task.max_tool_rounds,
                    status=status,
                    child_run_id=child_run_id if child_run_id is not None else task.child_run_id,
                    summary=summary if summary is not None else task.summary,
                    answer=answer if answer is not None else task.answer,
                    error=None if clear_error else (error if error is not None else task.error),
                    created_at=task.created_at,
                    started_at=now if started and task.started_at is None else task.started_at,
                    completed_at=now if completed else task.completed_at,
                    updated_at=now,
                )
                output_tasks.append(updated)
            if updated is None:
                raise ValidationError(f"Unknown task_id: {task_id}")

            groups = self._update_group_status(session_id=session_id, groups=self._read_groups(session_id), tasks=output_tasks)
            self._write_tasks(session_id, output_tasks)
            self._write_groups(session_id, groups)
            return updated.copy()

    def _update_group_status(
        self,
        *,
        session_id: str,
        groups: list[AgentTaskGroupRecord],
        tasks: list[AgentTaskRecord],
    ) -> list[AgentTaskGroupRecord]:
        now = utc_now()
        tasks_by_group: dict[str, list[AgentTaskRecord]] = {}
        for task in tasks:
            tasks_by_group.setdefault(task.task_group_id, []).append(task)
        output: list[AgentTaskGroupRecord] = []
        for group in groups:
            if group.session_id != session_id:
                output.append(group)
                continue
            group_tasks = tasks_by_group.get(group.task_group_id, [])
            status = derive_group_status(group_tasks)
            output.append(
                AgentTaskGroupRecord(
                    task_group_id=group.task_group_id,
                    session_id=group.session_id,
                    source_agent_id=group.source_agent_id,
                    source_run_id=group.source_run_id,
                    status=status,
                    max_concurrency=group.max_concurrency,
                    task_ids=group.task_ids,
                    created_at=group.created_at,
                    updated_at=now if status != group.status else group.updated_at,
                )
            )
        return output

    def _read_groups(self, session_id: str) -> list[AgentTaskGroupRecord]:
        return [task_group_from_payload(row) for row in self._read_jsonl(self._groups_path(session_id))]

    def _read_tasks(self, session_id: str) -> list[AgentTaskRecord]:
        return [task_from_payload(row) for row in self._read_jsonl(self._tasks_path(session_id))]

    def _write_groups(self, session_id: str, groups: list[AgentTaskGroupRecord]) -> None:
        self._write_jsonl(self._groups_path(session_id), [task_group_to_payload(group) for group in groups])

    def _write_tasks(self, session_id: str, tasks: list[AgentTaskRecord]) -> None:
        self._write_jsonl(self._tasks_path(session_id), [task_to_payload(task) for task in tasks])

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    payload = json.loads(stripped)
                    if not isinstance(payload, dict):
                        raise StorageError(f"Invalid JSONL row in '{path}': row must be object.")
                    rows.append(payload)
        except (json.JSONDecodeError, OSError) as exc:
            raise StorageError(f"Failed to read agent task file '{path}': {exc}") from exc
        return rows

    def _write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> None:
        temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with temp_path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            temp_path.replace(path)
        except OSError as exc:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            raise StorageError(f"Failed to write agent task file '{path}': {exc}") from exc

    def _ensure_session_dir(self, session_id: str) -> None:
        path = self._session_dir(session_id)
        if not path.exists() or not path.is_dir():
            raise SessionNotFoundError(f"Session not found: {session_id}")
        self._task_dir(session_id).mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        return self._sessions_dir / session_id

    def _task_dir(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "agent_tasks"

    def _groups_path(self, session_id: str) -> Path:
        return self._task_dir(session_id) / "task_groups.jsonl"

    def _tasks_path(self, session_id: str) -> Path:
        return self._task_dir(session_id) / "tasks.jsonl"

    def _validate_session_id(self, session_id: str) -> str:
        return self._require_non_empty("session_id", session_id)

    def _validate_agent_id(self, agent_id: str) -> str:
        return self._require_non_empty("agent_id", agent_id)

    def _validate_task_group_id(self, task_group_id: str) -> str:
        return self._require_non_empty("task_group_id", task_group_id)

    def _validate_task_id(self, task_id: str) -> str:
        return self._require_non_empty("task_id", task_id)

    def _require_non_empty(self, name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{name} must be a non-empty string.")
        return value.strip()
