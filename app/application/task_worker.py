from __future__ import annotations

import time
import uuid

from sqlalchemy.orm import Session, sessionmaker

from app.agents.orchestrator.orchestrator import StageExecutionError, WorkflowOrchestrator
from app.core.config.settings import get_settings
from app.core.db.session import SessionLocal
from app.core.db.repositories.task_repository import TaskRepository


class DatabaseTaskWorker:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | None = None,
        worker_id: str | None = None,
    ) -> None:
        self._session_factory = session_factory or SessionLocal
        self._settings = get_settings()
        self._worker_id = worker_id or f"worker-{uuid.uuid4()}"

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def run_forever(self, *, task_type: str = "all") -> None:
        while True:
            processed = self.process_next_task(task_type=task_type)
            if not processed:
                time.sleep(self._settings.task_worker_poll_interval_sec)

    def run_until_idle(self, *, task_type: str = "all", max_cycles: int = 100) -> int:
        processed = 0
        for _ in range(max_cycles):
            did_work = self.process_next_task(task_type=task_type)
            if not did_work:
                break
            processed += 1
        return processed

    def process_next_task(self, *, task_type: str = "all") -> bool:
        if task_type in {"all", "match"} and self._process_match_task():
            return True
        if task_type in {"all", "optimization"} and self._process_optimization_task():
            return True
        return False

    def _process_match_task(self) -> bool:
        with self._session_factory() as db:
            repo = TaskRepository(db)
            task = repo.claim_next_match_task(
                worker_id=self._worker_id,
                lock_timeout_sec=self._settings.task_lock_timeout_sec,
            )
            if task is None:
                db.commit()
                return False
            repo.log_event(
                task.id,
                "task.claimed",
                {"worker_id": self._worker_id, "task_status": task.task_status, "stage": task.stage},
            )
            db.commit()
            orchestrator = WorkflowOrchestrator(db)
            try:
                orchestrator.run_match_task(task.id)
                return True
            except Exception as exc:
                self._handle_match_failure(db, task_id=task.id, error=exc)
                return True

    def _process_optimization_task(self) -> bool:
        with self._session_factory() as db:
            repo = TaskRepository(db)
            task = repo.claim_next_optimization_task(
                worker_id=self._worker_id,
                lock_timeout_sec=self._settings.task_lock_timeout_sec,
            )
            if task is None:
                db.commit()
                return False
            repo.log_event(
                task.id,
                "task.claimed",
                {"worker_id": self._worker_id, "task_status": task.status, "stage": task.stage},
            )
            db.commit()
            orchestrator = WorkflowOrchestrator(db)
            try:
                orchestrator.run_optimization_task(task.id)
                return True
            except Exception as exc:
                self._handle_optimization_failure(db, task_id=task.id, error=exc)
                return True

    def _handle_match_failure(self, db: Session, *, task_id: str, error: Exception) -> None:
        repo = TaskRepository(db)
        task = repo.get_match_task(task_id)
        if task is None:
            return
        stage = task.stage
        retry_count = task.retry_count + 1
        terminal_status = "failed" if retry_count > task.max_retries else "queued"
        failure_reason = self._format_error(stage, error)
        repo.update_match_task(
            task.id,
            task_status=terminal_status,
            stage=stage,
            failure_reason=failure_reason,
            retry_count=retry_count,
            locked_at=None,
            locked_by=None,
            stage_started_at=None,
        )
        repo.log_event(
            task.id,
            "task.failed" if terminal_status == "failed" else "task.retry_scheduled",
            {
                "stage": stage,
                "retry_count": retry_count,
                "max_retries": task.max_retries,
                "failure_reason": failure_reason,
            },
        )
        db.commit()

    def _handle_optimization_failure(self, db: Session, *, task_id: str, error: Exception) -> None:
        repo = TaskRepository(db)
        task = repo.get_optimization_task(task_id)
        if task is None:
            return
        stage = task.stage
        retry_count = task.retry_count + 1
        terminal_status = "failed" if retry_count > task.max_retries else "queued"
        failure_reason = self._format_error(stage, error)
        repo.update_optimization_task(
            task.id,
            status=terminal_status,
            stage=stage,
            failure_reason=failure_reason,
            retry_count=retry_count,
            locked_at=None,
            locked_by=None,
            stage_started_at=None,
        )
        repo.log_event(
            task.id,
            "task.failed" if terminal_status == "failed" else "task.retry_scheduled",
            {
                "stage": stage,
                "retry_count": retry_count,
                "max_retries": task.max_retries,
                "failure_reason": failure_reason,
            },
        )
        db.commit()

    def _format_error(self, stage: str, error: Exception) -> str:
        if isinstance(error, StageExecutionError):
            return f"{error.stage}: {error.message}"
        return f"{stage}: {error}"
