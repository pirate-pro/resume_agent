"""Small data models for runtime memory operations."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import MemoryItem
from app.memory.models import MemoryScope


@dataclass(slots=True)
class MemoryWriteResult:
    memory: MemoryItem
    write_id: str
    written_records: int
    written_memory_ids: list[str]


@dataclass(slots=True)
class ReadPlan:
    include_scopes: list[MemoryScope]
    short_session_id: str | None
