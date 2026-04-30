"""Tests for background mid-term flush worker."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from app.core.errors import ValidationError
from app.runtime.mid_term_flush_worker import MidTermFlushWorker
from app.runtime.mid_term_flusher import MidTermFlushJobMetrics, MidTermFlushJobProcessReport

__all__ = []


class _CountingFlusher:
    def __init__(self) -> None:
        self.calls = 0
        self.max_agents_seen: list[int] = []
        self.max_jobs_seen: list[int] = []

    def process_due_jobs_report(self, *, max_agents: int, max_jobs_per_agent: int) -> MidTermFlushJobProcessReport:
        self.calls += 1
        self.max_agents_seen.append(max_agents)
        self.max_jobs_seen.append(max_jobs_per_agent)
        return MidTermFlushJobProcessReport(
            processed_count=1,
            succeeded_count=1,
            retry_count=0,
            deferred_count=0,
            target_count=1,
            scanned_targets=1,
        )

    def collect_job_metrics(self) -> MidTermFlushJobMetrics:
        return MidTermFlushJobMetrics(
            total_jobs=1,
            pending_jobs=0,
            running_jobs=0,
            retry_jobs=0,
            deferred_jobs=0,
            succeeded_jobs=1,
            due_jobs=0,
            due_retry_jobs=0,
            due_deferred_jobs=0,
            target_count=1,
        )


class _FailingFlusher:
    def __init__(self) -> None:
        self.calls = 0

    def process_due_jobs_report(self, *, max_agents: int, max_jobs_per_agent: int) -> MidTermFlushJobProcessReport:
        _ = (max_agents, max_jobs_per_agent)
        self.calls += 1
        raise RuntimeError("boom")

    def collect_job_metrics(self) -> MidTermFlushJobMetrics:
        return MidTermFlushJobMetrics(
            total_jobs=0,
            pending_jobs=0,
            running_jobs=0,
            retry_jobs=0,
            deferred_jobs=0,
            succeeded_jobs=0,
            due_jobs=0,
            due_retry_jobs=0,
            due_deferred_jobs=0,
            target_count=0,
        )


def test_mid_term_flush_worker_validates_constructor_arguments() -> None:
    flusher = _CountingFlusher()
    try:
        MidTermFlushWorker(flusher=cast(Any, flusher), poll_interval_seconds=0)
    except ValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Expected ValidationError for invalid poll interval")


def test_mid_term_flush_worker_run_once_passes_limits() -> None:
    flusher = _CountingFlusher()
    worker = MidTermFlushWorker(
        flusher=cast(Any, flusher),
        poll_interval_seconds=0.01,
        max_agents_per_tick=7,
        max_jobs_per_agent=5,
    )

    report = asyncio.run(worker.run_once())

    assert report.processed_count == 1
    assert report.succeeded_count == 1
    assert flusher.calls == 1
    assert flusher.max_agents_seen == [7]
    assert flusher.max_jobs_seen == [5]


def test_mid_term_flush_worker_start_and_stop_runs_background_loop() -> None:
    flusher = _CountingFlusher()
    worker = MidTermFlushWorker(flusher=cast(Any, flusher), poll_interval_seconds=0.01)

    async def _exercise() -> int:
        await worker.start()
        await asyncio.sleep(0.04)
        await worker.stop()
        return flusher.calls

    calls = asyncio.run(_exercise())
    assert calls >= 1


def test_mid_term_flush_worker_handles_tick_errors_and_can_stop() -> None:
    flusher = _FailingFlusher()
    worker = MidTermFlushWorker(flusher=cast(Any, flusher), poll_interval_seconds=0.01)

    async def _exercise() -> int:
        await worker.start()
        await asyncio.sleep(0.03)
        await worker.stop()
        return flusher.calls

    calls = asyncio.run(_exercise())
    assert calls >= 1
