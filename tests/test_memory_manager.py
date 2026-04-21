"""Tests for memory manager."""

from __future__ import annotations

from pathlib import Path

from app.infra.storage.jsonl_memory_repository import JsonlMemoryRepository
from app.runtime.memory_manager import MemoryManager

__all__ = []



def test_memory_manager_write_and_search(tmp_path: Path) -> None:
    repository = JsonlMemoryRepository(data_dir=tmp_path)
    manager = MemoryManager(memory_repository=repository)

    written = manager.write_memory(
        content="Prefer JSONL storage",
        tags=["preference", "storage"],
        session_id="sess_1",
        source_event_id="evt_1",
    )
    hits = manager.search(query="jsonl", limit=5)

    assert written.memory_id
    assert len(hits) == 1
    assert hits[0].content == "Prefer JSONL storage"
