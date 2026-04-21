"""Tests for JSONL and markdown storage adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.domain.models import EventRecord, MemoryItem
from app.infra.storage.jsonl_memory_repository import JsonlMemoryRepository
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository

__all__ = []



def test_session_create_and_append_event(tmp_path: Path) -> None:
    repository = JsonlSessionRepository(data_dir=tmp_path)
    meta = repository.create_session("sess_test")

    assert meta.session_id == "sess_test"

    event = EventRecord(
        event_id="evt_1",
        session_id="sess_test",
        type="user_message",
        payload={"content": "hello"},
        created_at=datetime.now(UTC),
    )
    repository.append_event("sess_test", event)
    events = repository.list_events("sess_test")

    assert len(events) == 1
    assert events[0].payload["content"] == "hello"



def test_memory_write_and_search(tmp_path: Path) -> None:
    repository = JsonlMemoryRepository(data_dir=tmp_path)
    repository.add_memory(
        MemoryItem(
            memory_id="mem_1",
            session_id="sess_test",
            content="User prefers JSONL storage",
            tags=["preference", "storage"],
            created_at=datetime.now(UTC),
            source_event_id="evt_1",
        )
    )

    hits = repository.search(query="jsonl", limit=5)

    assert len(hits) == 1
    assert hits[0].memory_id == "mem_1"



def test_skill_file_read(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "base.md").write_text("# Base\n\ncontent", encoding="utf-8")

    repository = MarkdownSkillRepository(skills_dir=skills_dir)
    loaded = repository.load_skills(["base"])

    assert "base" in loaded
    assert "content" in loaded["base"]
