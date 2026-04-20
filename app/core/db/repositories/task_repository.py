from datetime import UTC, datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.core.db.models.entities import (
    AgentTask,
    EventLog,
    JobMatchResult,
    MatchTask,
    ResumeOptimizationResult,
    ResumeOptimizationTask,
)
from app.domain.models.matching import MatchResult
from app.domain.models.optimization import OptimizationDraft
from app.domain.models.review import ReviewReport

_UNSET = object()


def utcnow() -> datetime:
    return datetime.now(UTC)


class TaskRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_match_task(
        self,
        candidate_id: str,
        resume_id: str,
        input_json: dict,
        *,
        max_retries: int,
        stage_timeout_sec: int,
    ) -> MatchTask:
        task = MatchTask(
            candidate_id=candidate_id,
            resume_id=resume_id,
            input_json=input_json,
            task_status="queued",
            max_retries=max_retries,
            stage_timeout_sec=stage_timeout_sec,
        )
        self._db.add(task)
        self._db.flush()
        return task

    def get_match_task(self, task_id: str) -> MatchTask | None:
        return self._db.get(MatchTask, task_id)

    def update_match_task(
        self,
        task_id: str,
        *,
        task_status: str | None = None,
        stage: str | None = None,
        failure_reason: str | None | object = _UNSET,
        locked_at: datetime | None | object = _UNSET,
        locked_by: str | None | object = _UNSET,
        stage_started_at: datetime | None | object = _UNSET,
        retry_count: int | None = None,
    ) -> MatchTask:
        task = self.get_match_task(task_id)
        if task is None:
            raise ValueError(f"match_task_not_found: {task_id}")
        if task_status is not None:
            task.task_status = task_status
        if stage is not None:
            task.stage = stage
        if failure_reason is not _UNSET:
            task.failure_reason = failure_reason
        if retry_count is not None:
            task.retry_count = retry_count
        if locked_at is not _UNSET:
            task.locked_at = locked_at
        if locked_by is not _UNSET:
            task.locked_by = locked_by
        if stage_started_at is not _UNSET:
            task.stage_started_at = stage_started_at
        self._db.add(task)
        self._db.flush()
        return task

    def claim_next_match_task(self, *, worker_id: str, lock_timeout_sec: int) -> MatchTask | None:
        threshold = datetime.now(UTC).timestamp() - lock_timeout_sec
        stale_before = datetime.fromtimestamp(threshold, tz=UTC)
        stmt = (
            select(MatchTask)
            .where(
                or_(
                    MatchTask.task_status == "queued",
                    MatchTask.task_status == "running",
                )
            )
            .where(or_(MatchTask.locked_at.is_(None), MatchTask.locked_at < stale_before))
            .order_by(MatchTask.created_at)
            .with_for_update(skip_locked=True)
        )
        task = self._db.scalar(stmt)
        if task is None:
            return None
        now = utcnow()
        task.task_status = "running"
        task.locked_at = now
        task.locked_by = worker_id
        task.failure_reason = None
        if task.stage_started_at is None:
            task.stage_started_at = now
        self._db.add(task)
        self._db.flush()
        return task

    def replace_match_results(self, task_id: str, results: list[MatchResult]) -> None:
        self._db.execute(delete(JobMatchResult).where(JobMatchResult.task_id == task_id))
        rows = [
            JobMatchResult(
                task_id=task_id,
                job_posting_id=result.job_posting_id,
                overall_score=result.score_card.overall_score,
                skill_score=result.score_card.skill_score,
                experience_score=result.score_card.experience_score,
                project_score=result.score_card.project_score,
                education_score=result.score_card.education_score,
                preference_score=result.score_card.preference_score,
                explanation_json=result.explanation,
                gap_json=result.gap.to_dict(),
                rank_no=result.rank_no,
            )
            for result in results
        ]
        self._db.add_all(rows)
        self._db.flush()

    def list_match_results(self, task_id: str) -> list[JobMatchResult]:
        stmt = select(JobMatchResult).where(JobMatchResult.task_id == task_id).order_by(JobMatchResult.rank_no)
        return list(self._db.scalars(stmt))

    def create_optimization_task(
        self,
        candidate_id: str,
        resume_id: str,
        target_job_id: str,
        *,
        mode: str,
        max_retries: int,
        stage_timeout_sec: int,
    ) -> ResumeOptimizationTask:
        task = ResumeOptimizationTask(
            candidate_id=candidate_id,
            resume_id=resume_id,
            target_job_id=target_job_id,
            mode=mode,
            status="queued",
            max_retries=max_retries,
            stage_timeout_sec=stage_timeout_sec,
        )
        self._db.add(task)
        self._db.flush()
        return task

    def get_optimization_task(self, task_id: str) -> ResumeOptimizationTask | None:
        return self._db.get(ResumeOptimizationTask, task_id)

    def update_optimization_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        failure_reason: str | None | object = _UNSET,
        locked_at: datetime | None | object = _UNSET,
        locked_by: str | None | object = _UNSET,
        stage_started_at: datetime | None | object = _UNSET,
        retry_count: int | None = None,
    ) -> ResumeOptimizationTask:
        task = self.get_optimization_task(task_id)
        if task is None:
            raise ValueError(f"optimization_task_not_found: {task_id}")
        if status is not None:
            task.status = status
        if stage is not None:
            task.stage = stage
        if failure_reason is not _UNSET:
            task.failure_reason = failure_reason
        if retry_count is not None:
            task.retry_count = retry_count
        if locked_at is not _UNSET:
            task.locked_at = locked_at
        if locked_by is not _UNSET:
            task.locked_by = locked_by
        if stage_started_at is not _UNSET:
            task.stage_started_at = stage_started_at
        self._db.add(task)
        self._db.flush()
        return task

    def claim_next_optimization_task(self, *, worker_id: str, lock_timeout_sec: int) -> ResumeOptimizationTask | None:
        threshold = datetime.now(UTC).timestamp() - lock_timeout_sec
        stale_before = datetime.fromtimestamp(threshold, tz=UTC)
        stmt = (
            select(ResumeOptimizationTask)
            .where(
                or_(
                    ResumeOptimizationTask.status == "queued",
                    ResumeOptimizationTask.status == "running",
                )
            )
            .where(or_(ResumeOptimizationTask.locked_at.is_(None), ResumeOptimizationTask.locked_at < stale_before))
            .order_by(ResumeOptimizationTask.created_at)
            .with_for_update(skip_locked=True)
        )
        task = self._db.scalar(stmt)
        if task is None:
            return None
        now = utcnow()
        task.status = "running"
        task.locked_at = now
        task.locked_by = worker_id
        task.failure_reason = None
        if task.stage_started_at is None:
            task.stage_started_at = now
        self._db.add(task)
        self._db.flush()
        return task

    def save_optimization_result(
        self,
        optimization_task_id: str,
        draft: OptimizationDraft,
        review_report: ReviewReport,
    ) -> ResumeOptimizationResult:
        self._db.execute(
            delete(ResumeOptimizationResult).where(
                ResumeOptimizationResult.optimization_task_id == optimization_task_id
            )
        )
        result = ResumeOptimizationResult(
            optimization_task_id=optimization_task_id,
            optimized_resume_markdown=draft.optimized_resume_markdown,
            change_summary_json=[item.to_dict() for item in draft.change_summary],
            risk_note_json=[item.to_dict() for item in draft.risk_notes],
            review_report_json=review_report.to_dict(),
        )
        self._db.add(result)
        self._db.flush()
        return result

    def get_optimization_result(self, optimization_task_id: str) -> ResumeOptimizationResult | None:
        stmt = select(ResumeOptimizationResult).where(
            ResumeOptimizationResult.optimization_task_id == optimization_task_id
        )
        return self._db.scalar(stmt)

    def create_agent_task(
        self,
        parent_task_id: str,
        task_type: str,
        agent_role: str,
        input_json: dict,
        *,
        retry_count: int = 0,
        timeout_sec: int | None = None,
    ) -> AgentTask:
        task = AgentTask(
            parent_task_id=parent_task_id,
            task_type=task_type,
            agent_role=agent_role,
            status="running",
            retry_count=retry_count,
            timeout_sec=timeout_sec,
            input_json=input_json,
            started_at=utcnow(),
        )
        self._db.add(task)
        self._db.flush()
        return task

    def finalize_agent_task(
        self,
        agent_task_id: str,
        *,
        status: str,
        output_json: dict,
        failure_reason: str | None = None,
    ) -> AgentTask:
        task = self._db.get(AgentTask, agent_task_id)
        task.status = status
        task.output_json = output_json
        task.failure_reason = failure_reason
        task.ended_at = utcnow()
        self._db.add(task)
        self._db.flush()
        return task

    def log_event(self, task_id: str, event_type: str, payload: dict) -> EventLog:
        event = EventLog(task_id=task_id, event_type=event_type, event_payload_json=payload)
        self._db.add(event)
        self._db.flush()
        return event

    def list_events(self, task_id: str) -> list[EventLog]:
        stmt = select(EventLog).where(EventLog.task_id == task_id).order_by(EventLog.created_at)
        return list(self._db.scalars(stmt))
