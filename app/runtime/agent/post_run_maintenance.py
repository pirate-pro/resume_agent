"""Single-flight post-run maintenance scheduling."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from app.domain.models import RunContext
from app.runtime.context_compactor import ContextCompactor
from app.runtime.mid_term_flusher import MidTermFlusher

__all__ = ["PostRunMaintenanceScheduler"]

_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _MaintenanceState:
    active: bool = False
    pending: bool = False
    latest_context: RunContext | None = None


class PostRunMaintenanceScheduler:
    """Run mid-term flush and context compaction in a per session/agent single-flight worker."""

    def __init__(
        self,
        *,
        mid_term_flusher_provider: Callable[[], MidTermFlusher | None],
        context_compactor_provider: Callable[[], ContextCompactor | None],
    ) -> None:
        self._mid_term_flusher_provider = mid_term_flusher_provider
        self._context_compactor_provider = context_compactor_provider
        self._lock = threading.Lock()
        self._states: dict[tuple[str, str], _MaintenanceState] = {}

    def dispatch_sync(self, context: RunContext) -> None:
        if not self._has_maintenance_work():
            return
        if not self._schedule(context):
            return
        thread = threading.Thread(
            target=self._run_worker,
            args=(context,),
            daemon=True,
            name=f"post-run-maintenance:{context.session_id}:{context.agent_id}",
        )
        thread.start()

    def dispatch_async(self, context: RunContext) -> None:
        if not self._has_maintenance_work():
            return
        if not self._schedule(context):
            return
        try:
            asyncio.create_task(
                self._run_async(context),
                name=f"post-run-maintenance:{context.session_id}:{context.agent_id}",
            )
        except RuntimeError:
            # 没有活动事件循环时回退到后台线程，避免丢失维护任务。
            thread = threading.Thread(
                target=self._run_worker,
                args=(context,),
                daemon=True,
                name=f"post-run-maintenance:{context.session_id}:{context.agent_id}",
            )
            thread.start()

    def _has_maintenance_work(self) -> bool:
        return self._mid_term_flusher_provider() is not None or self._context_compactor_provider() is not None

    def _schedule(self, context: RunContext) -> bool:
        key = self._key(context)
        with self._lock:
            state = self._states.get(key)
            if state is None:
                state = _MaintenanceState()
                self._states[key] = state

            state.latest_context = context
            if state.active:
                state.pending = True
                return False

            state.active = True
            state.pending = False
            return True

    def _run_worker(self, initial_context: RunContext) -> None:
        context = initial_context
        while True:
            try:
                self._run_once(context)
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "post-run maintenance crashed: session_id=%s agent_id=%s",
                    context.session_id,
                    context.agent_id,
                )

            key = self._key(context)
            with self._lock:
                state = self._states.get(key)
                if state is None:
                    return
                if state.pending and state.latest_context is not None:
                    context = state.latest_context
                    state.pending = False
                    continue
                del self._states[key]
                return

    def _run_once(self, context: RunContext) -> None:
        self._flush_mid_term_after_run_finished(context)
        self._compact_context_after_flush(context)

    async def _run_async(self, context: RunContext) -> None:
        await asyncio.to_thread(self._run_worker, context)

    def _flush_mid_term_after_run_finished(self, context: RunContext) -> None:
        flusher = self._mid_term_flusher_provider()
        if flusher is None:
            return
        try:
            result = flusher.flush_for_run_finished(context)
            _logger.debug(
                "mid-term flush: session_id=%s agent_id=%s flushed=%s reason=%s events=%s score=%s path=%s",
                context.session_id,
                context.agent_id,
                result.flushed,
                result.reason,
                result.event_count,
                result.signal_score,
                result.daily_path,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "mid-term flush failed: session_id=%s agent_id=%s error=%s",
                context.session_id,
                context.agent_id,
                exc,
            )

    def _compact_context_after_flush(self, context: RunContext) -> None:
        compactor = self._context_compactor_provider()
        if compactor is None:
            return
        try:
            result = compactor.compact_after_flush(context)
            _logger.debug(
                "context compaction: session_id=%s agent_id=%s compacted=%s reason=%s original_events=%s compressed=%s retained=%s summary=%s",
                context.session_id,
                context.agent_id,
                result.compacted,
                result.reason,
                result.original_event_count,
                result.compressed_event_count,
                result.retained_event_count,
                result.summary_event_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "context compaction failed: session_id=%s agent_id=%s error=%s",
                context.session_id,
                context.agent_id,
                exc,
            )

    def _key(self, context: RunContext) -> tuple[str, str]:
        return (context.session_id, context.agent_id)
