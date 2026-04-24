"""Tests for JSONL and markdown storage adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.models import EventRecord, MemoryItem, SessionFile
from app.core.errors import SessionNotFoundError, StorageError
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



def test_skill_file_read_standard_layout(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "base"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: base",
                "description: Base behavior skill",
                "---",
                "# Base",
                "",
                "content",
            ]
        ),
        encoding="utf-8",
    )

    repository = MarkdownSkillRepository(skills_dir=skills_dir)
    loaded = repository.load_skills(["base"])

    assert "base" in loaded
    assert "content" in loaded["base"]

    listed = repository.list_skills()
    assert len(listed) == 1
    assert listed[0].name == "base"
    assert listed[0].description == "Base behavior skill"


def test_skill_file_read_legacy_layout_is_rejected(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "base.md").write_text("# Base\n\nlegacy-content", encoding="utf-8")

    repository = MarkdownSkillRepository(skills_dir=skills_dir)
    with pytest.raises(StorageError):
        repository.load_skills(["base"])


def test_session_file_manifest_and_active_files(tmp_path: Path) -> None:
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session("sess_file")
    workspace = repository.get_workspace_path("sess_file")
    text_path = workspace / ".parsed" / "file_1.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text("hello file", encoding="utf-8")

    file_record = SessionFile(
        file_id="file_1",
        session_id="sess_file",
        filename="a.txt",
        media_type="text/plain",
        size_bytes=10,
        status="ready",
        uploaded_at=datetime.now(UTC),
        storage_relpath="workspace/uploads/file_1_a.txt",
        text_relpath="workspace/.parsed/file_1.txt",
        error=None,
    )
    repository.add_or_update_session_file(file_record)

    files = repository.list_session_files("sess_file")
    active = repository.set_active_file_ids("sess_file", ["file_1"])
    text = repository.read_session_file_text("sess_file", "file_1")

    assert len(files) == 1
    assert files[0].file_id == "file_1"
    assert active == ["file_1"]
    assert "hello file" in text


def test_skill_file_invalid_frontmatter_raises(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "bad-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: bad-skill",
                "---",
                "body",
            ]
        ),
        encoding="utf-8",
    )

    repository = MarkdownSkillRepository(skills_dir=skills_dir)
    with pytest.raises(StorageError):
        repository.load_skills(["bad-skill"])


def test_session_delete_removes_session_directory(tmp_path: Path) -> None:
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session("sess_delete")
    repository.append_event(
        "sess_delete",
        EventRecord(
            event_id="evt_delete",
            session_id="sess_delete",
            type="user_message",
            payload={"content": "hello"},
            created_at=datetime.now(UTC),
        ),
    )

    repository.delete_session("sess_delete")

    assert repository.get_session("sess_delete") is None
    with pytest.raises(SessionNotFoundError):
        repository.list_events("sess_delete")
