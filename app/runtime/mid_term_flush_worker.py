"""Background polling worker for mid-term flush retries."""

from __future__ import annotations

import asyncio
import logging

from app.core.errors import ValidationError
from app.runtime.mid_term_flusher import MidTermFlusher, MidTermFlushJobMetrics, MidTermFlushJobProcessReport

__all__ = ["MidTermFlushWorker"]

_logger = logging.getLogger(__name__)


class MidTermFlushWorker:
    """Run periodic due-job processing in background."""

    def __init__(
        self,
        *,
        flusher: MidTermFlusher,
        poll_interval_seconds: float = 8.0,
        max_agents_per_tick: int = 24,
        max_jobs_per_agent: int = 2,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValidationError("poll_interval_seconds must be positive.")
        if max_agents_per_tick <= 0:
            raise ValidationError("max_agents_per_tick must be positive.")
        if max_jobs_per_agent <= 0:
            raise ValidationError("max_jobs_per_agent must be positive.")
        self._flusher = flusher
        self._poll_interval_seconds = poll_interval_seconds
        self._max_agents_per_tick = max_agents_per_tick
        self._max_jobs_per_agent = max_jobs_per_agent
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="mid-term-flush-worker")
        _logger.info(
            "mid-term flush worker started: poll=%ss max_agents=%s max_jobs_per_agent=%s",
            self._poll_interval_seconds,
            self._max_agents_per_tick,
            self._max_jobs_per_agent,
        )

    async def stop(self) -> None:
        task = self._task
        stop_event = self._stop_event
        if task is None:
            return
        if stop_event is not None:
            stop_event.set()
        try:
            await task
        finally:
            self._task = None
            self._stop_event = None
            _logger.info("mid-term flush worker stopped")

    async def run_once(self) -> MidTermFlushJobProcessReport:
        return await asyncio.to_thread(
            self._flusher.process_due_jobs_report,
            max_agents=self._max_agents_per_tick,
            max_jobs_per_agent=self._max_jobs_per_agent,
        )

    async def collect_metrics(self) -> MidTermFlushJobMetrics:
        return await asyncio.to_thread(self._flusher.collect_job_metrics)

    async def _run_loop(self) -> None:
        stop_event = self._stop_event
        if stop_event is None:
            return
        while not stop_event.is_set():
            try:
                before = await self.collect_metrics()
                report = await self.run_once()
                after = await self.collect_metrics()
                if report.processed_count > 0 or after.due_jobs > 0 or after.retry_jobs > 0 or after.deferred_jobs > 0:
                    _logger.info(
                        "mid-term flush worker tick: processed=%s succeeded=%s retry=%s deferred=%s "
                        "targets_scanned=%s/%s queue_total=%s queue_due=%s retry_jobs=%s deferred_jobs=%s",
                        report.processed_count,
                        report.succeeded_count,
                        report.retry_count,
                        report.deferred_count,
                        report.scanned_targets,
                        report.target_count,
                        after.total_jobs,
                        after.due_jobs,
                        after.retry_jobs,
                        after.deferred_jobs,
                    )
                elif before.total_jobs != after.total_jobs:
                    _logger.debug(
                        "mid-term flush queue changed without due work: before_total=%s after_total=%s",
                        before.total_jobs,
                        after.total_jobs,
                    )
            except Exception as exc:  # noqa: BLE001
                _logger.warning("mid-term flush worker tick failed: %s", exc)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                continue
