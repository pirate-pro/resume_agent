"""Contracts for the state subsystem."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.state.models import StateRecord, StateScope

__all__ = ["StateStore"]


class StateStore(Protocol):
    def upsert_record(self, record: StateRecord) -> None: ...

    def get_record(
        self,
        *,
        scope: StateScope,
        session_id: str,
        key: str,
        agent_id: str | None = None,
        include_archived: bool = False,
    ) -> StateRecord | None: ...

    def list_records(
        self,
        *,
        scope: StateScope,
        session_id: str,
        agent_id: str | None = None,
        include_archived: bool = False,
    ) -> list[StateRecord]: ...

    def archive_records(
        self,
        *,
        scope: StateScope,
        session_id: str,
        keys: list[str] | None,
        now: datetime,
        agent_id: str | None = None,
    ) -> int: ...
