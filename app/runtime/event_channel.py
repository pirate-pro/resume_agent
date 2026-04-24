"""Async event channel for runtime streaming outputs."""

from __future__ import annotations

import asyncio
from datetime import UTC
from collections.abc import AsyncIterator
from typing import Any

from app.domain.models import EventRecord

__all__ = ["EventChannel", "serialize_event_record"]

_CLOSE_SENTINEL = object()


class EventChannel:
    """基于 asyncio.Queue 的事件推送通道。"""

    def __init__(self, maxsize: int = 512) -> None:
        if maxsize <= 0:
            raise ValueError("maxsize must be positive.")
        self._queue: asyncio.Queue[dict[str, Any] | object] = asyncio.Queue(maxsize=maxsize)
        self._closed = False

    async def emit(self, event: str, data: dict[str, Any]) -> None:
        if self._closed:
            return
        await self._queue.put({"event": event, "data": data})

    async def emit_run_event(self, record: EventRecord) -> None:
        await self.emit("run_event", serialize_event_record(record))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._queue.put(_CLOSE_SENTINEL)

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            item = await self.receive()
            if item is None:
                break
            yield item

    async def receive(self, timeout_seconds: float | None = None) -> dict[str, Any] | None:
        if timeout_seconds is None:
            item = await self._queue.get()
        else:
            if timeout_seconds <= 0:
                raise ValueError("timeout_seconds must be positive when provided.")
            item = await asyncio.wait_for(self._queue.get(), timeout=timeout_seconds)
        if item is _CLOSE_SENTINEL:
            return None
        if isinstance(item, dict):
            return item
        return None


def serialize_event_record(event: EventRecord) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "session_id": event.session_id,
        "agent_id": event.agent_id,
        "run_id": event.run_id,
        "parent_run_id": event.parent_run_id,
        "event_version": event.event_version,
        "type": event.type,
        "payload": event.payload,
        "created_at": event.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }
