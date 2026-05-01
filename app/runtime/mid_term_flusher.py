"""Mid-term daily flush orchestration based on structured model output."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.models import RunContext
from app.domain.protocols import ChatModelClient, SessionRepository
from app.memory.file_store import FileMemoryStore
from app.runtime.mid_term.cursors import MidTermFlushCursorStore
from app.runtime.mid_term.daily import MidTermDailyRenderer, MidTermDailyWriter
from app.runtime.mid_term.event_packer import MidTermEventPackBuilder
from app.runtime.mid_term.jobs import MidTermFlushJobStore
from app.runtime.mid_term.materializer import MidTermCandidateFactMaterializer
from app.runtime.mid_term.models import (
    FlushCursor,
    MidTermEventPack,
    MidTermFlushJob,
    MidTermFlushJobMetrics,
    MidTermFlushJobProcessReport,
    MidTermFlushJobStatus,
    MidTermFlushResult,
)
from app.runtime.mid_term.shared import MIN_INPUT_BUDGET_TOKENS, safe_text
from app.runtime.mid_term.summary import MidTermSummarizer, MidTermSummaryValidator

__all__ = [
    "MidTermFlushJobMetrics",
    "MidTermFlushJobProcessReport",
    "MidTermFlushJob",
    "MidTermFlushJobStatus",
    "MidTermFlushResult",
    "MidTermFlusher",
]

_logger = logging.getLogger(__name__)

_RETRY_BACKOFF_SECONDS = (5, 20, 60)
_DEFERRED_RETRY_SECONDS = 180


class MidTermFlusher:
    """Queue, process, and persist mid-term flush jobs."""

    def __init__(
        self,
        session_repository: SessionRepository,
        memory_store: FileMemoryStore,
        model_client: ChatModelClient,
        *,
        model_context_window_tokens: int = 32768,
        model_input_ratio: float = 0.35,
        model_output_reserve_tokens: int = 1200,
        prompt_overhead_tokens: int = 900,
        max_input_tokens: int = 5200,
    ) -> None:
        if model_context_window_tokens <= 0:
            raise ValidationError("model_context_window_tokens must be positive.")
        if model_input_ratio <= 0 or model_input_ratio >= 1:
            raise ValidationError("model_input_ratio must be in (0,1).")
        if model_output_reserve_tokens <= 0:
            raise ValidationError("model_output_reserve_tokens must be positive.")
        if prompt_overhead_tokens <= 0:
            raise ValidationError("prompt_overhead_tokens must be positive.")
        if max_input_tokens < MIN_INPUT_BUDGET_TOKENS:
            raise ValidationError(f"max_input_tokens must be at least {MIN_INPUT_BUDGET_TOKENS}.")
        self._job_store = MidTermFlushJobStore(memory_store.root_dir)
        self._cursor_store = MidTermFlushCursorStore(memory_store.root_dir)
        self._event_pack_builder = MidTermEventPackBuilder(
            session_repository,
            model_context_window_tokens=model_context_window_tokens,
            model_input_ratio=model_input_ratio,
            model_output_reserve_tokens=model_output_reserve_tokens,
            prompt_overhead_tokens=prompt_overhead_tokens,
            max_input_tokens=max_input_tokens,
        )
        self._summarizer = MidTermSummarizer(model_client)
        self._validator = MidTermSummaryValidator()
        self._renderer = MidTermDailyRenderer()
        self._daily_writer = MidTermDailyWriter(memory_store)
        self._candidate_materializer = MidTermCandidateFactMaterializer(memory_store)

    def flush_for_run_finished(self, context: RunContext) -> MidTermFlushResult:
        if not isinstance(context, RunContext):
            raise ValidationError("context must be RunContext.")
        cursor = self._cursor_store.load_cursor(session_id=context.session_id, agent_id=context.agent_id)
        packs, reason = self._event_pack_builder.build(context=context, cursor=cursor)
        if not packs:
            return MidTermFlushResult(
                flushed=False,
                reason=reason,
                session_id=context.session_id,
                agent_id=context.agent_id,
                event_count=0,
                signal_score=0,
                last_event_id=cursor.last_event_id,
            )

        jobs = self._ensure_jobs(context=context, packs=packs)
        focus_job = jobs[-1]
        processed = self._process_due_jobs(
            session_id=context.session_id,
            agent_id=context.agent_id,
            max_jobs=max(3, len(packs) + 2),
        )
        processed_by_id = {item.job_id: item for item in processed}
        if focus_job.job_id in processed_by_id:
            focus_job = processed_by_id[focus_job.job_id]
        else:
            focus_job = self._refresh_job(focus_job)

        total_event_count = sum(pack.event_count for pack in packs)
        total_signal_score = sum(pack.signal_score for pack in packs)
        return MidTermFlushResult(
            flushed=focus_job.status == MidTermFlushJobStatus.SUCCEEDED,
            reason=focus_job.status.value,
            session_id=context.session_id,
            agent_id=context.agent_id,
            event_count=total_event_count,
            signal_score=total_signal_score,
            daily_path=focus_job.daily_path,
            last_event_id=focus_job.event_pack.last_event_id,
            job_id=focus_job.job_id,
            job_status=focus_job.status.value,
            retry_count=focus_job.retry_count,
        )

    def process_due_jobs(
        self,
        *,
        max_agents: int = 24,
        max_jobs_per_agent: int = 2,
    ) -> int:
        """Process due retry/deferred jobs across all agents."""
        report = self.process_due_jobs_report(
            max_agents=max_agents,
            max_jobs_per_agent=max_jobs_per_agent,
        )
        return report.processed_count

    def process_due_jobs_report(
        self,
        *,
        max_agents: int = 24,
        max_jobs_per_agent: int = 2,
    ) -> MidTermFlushJobProcessReport:
        """Process due jobs and return structured outcome counters."""
        if max_agents <= 0:
            raise ValidationError("max_agents must be positive.")
        if max_jobs_per_agent <= 0:
            raise ValidationError("max_jobs_per_agent must be positive.")
        processed_count = 0
        succeeded_count = 0
        retry_count = 0
        deferred_count = 0
        job_targets = self._job_store.list_job_targets()
        scanned_targets = 0
        for session_id, agent_id in job_targets[:max_agents]:
            scanned_targets += 1
            processed = self._process_due_jobs(
                session_id=session_id,
                agent_id=agent_id,
                max_jobs=max_jobs_per_agent,
            )
            processed_count += len(processed)
            for job in processed:
                if job.status == MidTermFlushJobStatus.SUCCEEDED:
                    succeeded_count += 1
                elif job.status == MidTermFlushJobStatus.RETRY:
                    retry_count += 1
                elif job.status == MidTermFlushJobStatus.DEFERRED:
                    deferred_count += 1
        return MidTermFlushJobProcessReport(
            processed_count=processed_count,
            succeeded_count=succeeded_count,
            retry_count=retry_count,
            deferred_count=deferred_count,
            target_count=len(job_targets),
            scanned_targets=scanned_targets,
        )

    def collect_job_metrics(self) -> MidTermFlushJobMetrics:
        """Collect queue-level metrics for logging/observability."""
        jobs = self._job_store.list_all_jobs()
        now = datetime.now(UTC)
        pending_jobs = 0
        running_jobs = 0
        retry_jobs = 0
        deferred_jobs = 0
        succeeded_jobs = 0
        due_jobs = 0
        due_retry_jobs = 0
        due_deferred_jobs = 0
        for job in jobs:
            if job.status == MidTermFlushJobStatus.PENDING:
                pending_jobs += 1
            elif job.status == MidTermFlushJobStatus.RUNNING:
                running_jobs += 1
            elif job.status == MidTermFlushJobStatus.RETRY:
                retry_jobs += 1
            elif job.status == MidTermFlushJobStatus.DEFERRED:
                deferred_jobs += 1
            elif job.status == MidTermFlushJobStatus.SUCCEEDED:
                succeeded_jobs += 1
            if job.status in {MidTermFlushJobStatus.PENDING, MidTermFlushJobStatus.RETRY, MidTermFlushJobStatus.DEFERRED}:
                if job.next_attempt_at <= now:
                    due_jobs += 1
                    if job.status == MidTermFlushJobStatus.RETRY:
                        due_retry_jobs += 1
                    elif job.status == MidTermFlushJobStatus.DEFERRED:
                        due_deferred_jobs += 1

        return MidTermFlushJobMetrics(
            total_jobs=len(jobs),
            pending_jobs=pending_jobs,
            running_jobs=running_jobs,
            retry_jobs=retry_jobs,
            deferred_jobs=deferred_jobs,
            succeeded_jobs=succeeded_jobs,
            due_jobs=due_jobs,
            due_retry_jobs=due_retry_jobs,
            due_deferred_jobs=due_deferred_jobs,
            target_count=len(self._job_store.list_job_targets()),
        )

    def _ensure_jobs(self, *, context: RunContext, packs: list[MidTermEventPack]) -> list[MidTermFlushJob]:
        jobs: list[MidTermFlushJob] = []
        for pack in packs:
            duplicate = self._job_store.find_duplicate_job(
                session_id=context.session_id,
                agent_id=context.agent_id,
                first_event_id=pack.first_event_id,
                last_event_id=pack.last_event_id,
            )
            if duplicate is None:
                job = self._create_job(context=context, pack=pack)
                self._job_store.create_job(job)
            else:
                job = duplicate
            jobs.append(job)
        return jobs

    def _refresh_job(self, job: MidTermFlushJob) -> MidTermFlushJob:
        refreshed = self._job_store.get_job(
            session_id=job.session_id,
            agent_id=job.agent_id,
            job_id=job.job_id,
        )
        return refreshed if refreshed is not None else job

    def _create_job(self, *, context: RunContext, pack: MidTermEventPack) -> MidTermFlushJob:
        now = datetime.now(UTC)
        path = self._daily_writer.daily_path(agent_id=context.agent_id, now=pack.created_at)
        return MidTermFlushJob(
            job_id=f"job_{uuid4().hex[:12]}",
            session_id=context.session_id,
            agent_id=context.agent_id,
            status=MidTermFlushJobStatus.PENDING,
            retry_count=0,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
            event_pack=pack,
            daily_path=str(path),
            last_error=None,
        )

    def _process_due_jobs(self, *, session_id: str, agent_id: str, max_jobs: int) -> list[MidTermFlushJob]:
        now = datetime.now(UTC)
        output: list[MidTermFlushJob] = []
        jobs = self._job_store.list_jobs(session_id=session_id, agent_id=agent_id)
        for job in jobs:
            if len(output) >= max_jobs:
                break
            if job.status == MidTermFlushJobStatus.SUCCEEDED:
                continue
            if job.status == MidTermFlushJobStatus.RUNNING:
                continue
            if job.next_attempt_at > now:
                continue
            updated = self._process_one_job(job)
            output.append(updated)
        return output

    def _process_one_job(self, job: MidTermFlushJob) -> MidTermFlushJob:
        running = self._copy_job_with_status(job, status=MidTermFlushJobStatus.RUNNING)
        self._job_store.update_job(running)
        try:
            raw_summary = self._summarizer.summarize(running.event_pack)
            validated = self._validator.validate(raw_summary, running.event_pack)
            flushed_at = datetime.now(UTC)
            block = self._renderer.render(summary=validated, pack=running.event_pack, flushed_at=flushed_at)
            self._daily_writer.append_daily_block(Path(running.daily_path), running.event_pack, block)
            facts_written, facts_skipped = self._candidate_materializer.materialize(
                job=running,
                summary=validated,
                flushed_at=flushed_at,
            )
            self._cursor_store.save_cursor(
                session_id=running.session_id,
                agent_id=running.agent_id,
                cursor=FlushCursor(last_event_id=running.event_pack.last_event_id, last_flushed_at=flushed_at),
            )
            succeeded = self._copy_job_with_status(
                running,
                status=MidTermFlushJobStatus.SUCCEEDED,
                next_attempt_at=flushed_at,
                updated_at=flushed_at,
                clear_last_error=True,
            )
            self._job_store.update_job(succeeded)
            self._log_materialized_facts(running, facts_written=facts_written, facts_skipped=facts_skipped)
            return succeeded
        except Exception as exc:  # noqa: BLE001
            retried = self._mark_retry_or_deferred(running, error=str(exc))
            self._job_store.update_job(retried)
            _logger.warning(
                "mid-term job failed: job_id=%s session_id=%s agent_id=%s status=%s retry=%s error=%s",
                retried.job_id,
                retried.session_id,
                retried.agent_id,
                retried.status.value,
                retried.retry_count,
                retried.last_error,
            )
            return retried

    def _copy_job_with_status(
        self,
        job: MidTermFlushJob,
        *,
        status: MidTermFlushJobStatus,
        next_attempt_at: datetime | None = None,
        updated_at: datetime | None = None,
        last_error: str | None = None,
        clear_last_error: bool = False,
    ) -> MidTermFlushJob:
        if clear_last_error:
            resolved_last_error = None
        else:
            resolved_last_error = last_error if last_error is not None else job.last_error
        return MidTermFlushJob(
            job_id=job.job_id,
            session_id=job.session_id,
            agent_id=job.agent_id,
            status=status,
            retry_count=job.retry_count,
            next_attempt_at=next_attempt_at if next_attempt_at is not None else job.next_attempt_at,
            created_at=job.created_at,
            updated_at=updated_at if updated_at is not None else datetime.now(UTC),
            event_pack=job.event_pack,
            daily_path=job.daily_path,
            last_error=resolved_last_error,
        )

    def _mark_retry_or_deferred(self, job: MidTermFlushJob, *, error: str) -> MidTermFlushJob:
        now = datetime.now(UTC)
        next_retry_count = job.retry_count + 1
        if next_retry_count <= len(_RETRY_BACKOFF_SECONDS):
            backoff = timedelta(seconds=_RETRY_BACKOFF_SECONDS[next_retry_count - 1])
            status = MidTermFlushJobStatus.RETRY
            next_attempt_at = now + backoff
        else:
            status = MidTermFlushJobStatus.DEFERRED
            next_attempt_at = now + timedelta(seconds=_DEFERRED_RETRY_SECONDS)
        return MidTermFlushJob(
            job_id=job.job_id,
            session_id=job.session_id,
            agent_id=job.agent_id,
            status=status,
            retry_count=next_retry_count,
            next_attempt_at=next_attempt_at,
            created_at=job.created_at,
            updated_at=now,
            event_pack=job.event_pack,
            daily_path=job.daily_path,
            last_error=safe_text(error, max_len=400),
        )

    def _log_materialized_facts(
        self,
        job: MidTermFlushJob,
        *,
        facts_written: int,
        facts_skipped: int,
    ) -> None:
        if facts_written <= 0 and facts_skipped <= 0:
            return
        _logger.debug(
            "mid-term candidate facts materialized: session_id=%s agent_id=%s job_id=%s written=%s skipped=%s",
            job.session_id,
            job.agent_id,
            job.job_id,
            facts_written,
            facts_skipped,
        )
