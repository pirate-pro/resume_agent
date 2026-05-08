"""Mid-term daily flush orchestration based on structured model output."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.core.errors import ValidationError
from app.core.time import app_now
from app.domain.models import EventRecord, RunContext
from app.domain.protocols import ChatModelClient, SessionRepository
from app.memory.file_store import FileMemoryStore
from app.runtime.context_compaction.models import CONTEXT_SUMMARY_EVENT
from app.runtime.context_compaction.coverage import CompactionCoverageResult
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
_DEFAULT_RUNNING_JOB_STALE_AFTER_SECONDS = 600


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
        running_job_stale_after_seconds: int = _DEFAULT_RUNNING_JOB_STALE_AFTER_SECONDS,
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
        if running_job_stale_after_seconds <= 0:
            raise ValidationError("running_job_stale_after_seconds must be positive.")
        self._running_job_stale_after = timedelta(seconds=running_job_stale_after_seconds)
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
        unfinished = self._find_unfinished_job(session_id=context.session_id, agent_id=context.agent_id)
        if unfinished is not None:
            dirty_job = self._mark_job_dirty(unfinished)
            processed = self._process_due_jobs(
                session_id=context.session_id,
                agent_id=context.agent_id,
                max_jobs=1,
            )
            focus_job = processed[-1] if processed else self._refresh_job(dirty_job)
            remaining = self._find_unfinished_job(session_id=context.session_id, agent_id=context.agent_id)
            if remaining is not None:
                focus_job = remaining
            return MidTermFlushResult(
                flushed=remaining is None and focus_job.status == MidTermFlushJobStatus.SUCCEEDED,
                reason=focus_job.status.value if remaining is None else "active_job_exists",
                session_id=context.session_id,
                agent_id=context.agent_id,
                event_count=focus_job.event_pack.event_count,
                signal_score=focus_job.event_pack.signal_score,
                daily_path=focus_job.daily_path,
                last_event_id=focus_job.event_pack.last_event_id,
                job_id=focus_job.job_id,
                job_status=focus_job.status.value,
                retry_count=focus_job.retry_count,
            )

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
            max_jobs=1,
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
        now = app_now()
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

    def check_compaction_coverage(
        self,
        *,
        context: RunContext,
        all_events: list[EventRecord],
        compressed_events: list[EventRecord],
    ) -> CompactionCoverageResult:
        """Check whether compressed events are covered by cursor or job snapshots."""
        required_ids: list[str] = []
        for event in compressed_events:
            event_id = self._event_id(event)
            if event_id is not None and self._requires_coverage(event, event_id):
                required_ids.append(event_id)
        if not required_ids:
            return CompactionCoverageResult(covered=True, reason="no_raw_events_to_cover")

        covered_ids = self._cursor_covered_event_ids(context=context, all_events=all_events)
        covered_ids.update(self._snapshot_covered_event_ids(session_id=context.session_id, agent_id=context.agent_id))

        missing = [event_id for event_id in required_ids if event_id not in covered_ids]
        if missing:
            return CompactionCoverageResult(
                covered=False,
                reason="missing_flush_snapshot",
                missing_event_ids=missing,
            )
        return CompactionCoverageResult(covered=True, reason="covered_by_cursor_or_snapshot")

    def _ensure_jobs(self, *, context: RunContext, packs: list[MidTermEventPack]) -> list[MidTermFlushJob]:
        jobs: list[MidTermFlushJob] = []
        for pack in packs[:1]:
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

    def _find_unfinished_job(self, *, session_id: str, agent_id: str) -> MidTermFlushJob | None:
        for job in self._job_store.list_jobs(session_id=session_id, agent_id=agent_id):
            if job.status != MidTermFlushJobStatus.SUCCEEDED:
                return job
        return None

    def _mark_job_dirty(self, job: MidTermFlushJob) -> MidTermFlushJob:
        refreshed = self._refresh_job(job)
        if refreshed.status == MidTermFlushJobStatus.SUCCEEDED or refreshed.dirty:
            return refreshed
        dirty = MidTermFlushJob(
            job_id=refreshed.job_id,
            session_id=refreshed.session_id,
            agent_id=refreshed.agent_id,
            status=refreshed.status,
            retry_count=refreshed.retry_count,
            next_attempt_at=refreshed.next_attempt_at,
            created_at=refreshed.created_at,
            updated_at=app_now(),
            event_pack=refreshed.event_pack,
            daily_path=refreshed.daily_path,
            last_error=refreshed.last_error,
            dirty=True,
        )
        self._job_store.update_job(dirty)
        return dirty

    def _refresh_job(self, job: MidTermFlushJob) -> MidTermFlushJob:
        refreshed = self._job_store.get_job(
            session_id=job.session_id,
            agent_id=job.agent_id,
            job_id=job.job_id,
        )
        return refreshed if refreshed is not None else job

    def _create_job(self, *, context: RunContext, pack: MidTermEventPack) -> MidTermFlushJob:
        now = app_now()
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
        now = app_now()
        output: list[MidTermFlushJob] = []
        jobs = self._job_store.list_jobs(session_id=session_id, agent_id=agent_id)
        for job in jobs:
            if len(output) >= max_jobs:
                break
            if job.status == MidTermFlushJobStatus.SUCCEEDED:
                continue
            if job.status == MidTermFlushJobStatus.RUNNING:
                if not self._is_stale_running_job(job, now):
                    continue
                job = self._recover_stale_running_job(job, now)
            if job.next_attempt_at > now:
                continue
            updated = self._process_one_job(job)
            output.append(updated)
        return output

    def _is_stale_running_job(self, job: MidTermFlushJob, now: datetime) -> bool:
        return now - job.updated_at >= self._running_job_stale_after

    def _recover_stale_running_job(self, job: MidTermFlushJob, now: datetime) -> MidTermFlushJob:
        recovered = MidTermFlushJob(
            job_id=job.job_id,
            session_id=job.session_id,
            agent_id=job.agent_id,
            status=MidTermFlushJobStatus.RETRY,
            retry_count=job.retry_count + 1,
            next_attempt_at=now,
            created_at=job.created_at,
            updated_at=now,
            event_pack=job.event_pack,
            daily_path=job.daily_path,
            last_error="stale running job recovered for retry",
            dirty=job.dirty,
        )
        self._job_store.update_job(recovered)
        _logger.warning(
            "recovered stale mid-term running job: job_id=%s session_id=%s agent_id=%s retry=%s",
            recovered.job_id,
            recovered.session_id,
            recovered.agent_id,
            recovered.retry_count,
        )
        return recovered

    def _process_one_job(self, job: MidTermFlushJob) -> MidTermFlushJob:
        running = self._copy_job_with_status(job, status=MidTermFlushJobStatus.RUNNING)
        self._job_store.update_job(running)
        try:
            raw_summary = self._summarizer.summarize(running.event_pack)
            validated = self._validator.validate(raw_summary, running.event_pack)
            flushed_at = app_now()
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
            if running.dirty:
                self._create_next_job_if_ready(running)
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
            updated_at=updated_at if updated_at is not None else app_now(),
            event_pack=job.event_pack,
            daily_path=job.daily_path,
            last_error=resolved_last_error,
            dirty=job.dirty if status != MidTermFlushJobStatus.SUCCEEDED else False,
        )

    def _mark_retry_or_deferred(self, job: MidTermFlushJob, *, error: str) -> MidTermFlushJob:
        now = app_now()
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
            dirty=job.dirty,
        )

    def _create_next_job_if_ready(self, job: MidTermFlushJob) -> None:
        context = RunContext(
            session_id=job.session_id,
            run_id=f"flush_{job.job_id}",
            agent_id=job.agent_id,
            turn_id=f"flush_{job.job_id}",
            entry_agent_id=job.agent_id,
            parent_run_id=None,
            trace_flags={},
        )
        cursor = self._cursor_store.load_cursor(session_id=job.session_id, agent_id=job.agent_id)
        packs, reason = self._event_pack_builder.build(context=context, cursor=cursor)
        if not packs:
            _logger.debug(
                "mid-term dirty stream recheck produced no new job: session_id=%s agent_id=%s reason=%s",
                job.session_id,
                job.agent_id,
                reason,
            )
            return
        self._ensure_jobs(context=context, packs=packs)

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

    def _cursor_covered_event_ids(self, *, context: RunContext, all_events: list[EventRecord]) -> set[str]:
        cursor = self._cursor_store.load_cursor(session_id=context.session_id, agent_id=context.agent_id)
        if cursor.last_event_id is None:
            return set()

        covered: set[str] = set()
        for event in all_events:
            event_id = self._event_id(event)
            if not event_id:
                continue
            covered.add(event_id)
            if event_id == cursor.last_event_id:
                return covered
        return set()

    def _snapshot_covered_event_ids(self, *, session_id: str, agent_id: str) -> set[str]:
        covered: set[str] = set()
        for job in self._job_store.list_jobs(session_id=session_id, agent_id=agent_id):
            for row in job.event_pack.events:
                event_id = str(row.get("event_id", "")).strip() if isinstance(row, dict) else ""
                if event_id:
                    covered.add(event_id)
        return covered

    def _requires_coverage(self, event: EventRecord, event_id: str) -> bool:
        event_type = getattr(event, "type", None)
        return event_type != CONTEXT_SUMMARY_EVENT

    def _event_id(self, event: EventRecord) -> str | None:
        normalized = event.event_id.strip()
        return normalized or None
