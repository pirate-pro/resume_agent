"""Tests for context assembly."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.domain.models import EventRecord, MemoryItem
from app.infra.storage.jsonl_memory_repository import JsonlMemoryRepository
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.runtime.context_assembler import ContextAssembler
from app.runtime.memory_manager import MemoryManager
from app.tools.builtins import MemorySearchTool
from app.tools.registry import ToolRegistry

__all__ = []



def test_context_assembler_loads_skills_events_and_memory(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    memory_repo = JsonlMemoryRepository(data_dir=tmp_path)
    skill_repo = MarkdownSkillRepository(skills_dir=Path("app/skills"))

    session_repo.create_session("sess_1")
    session_repo.append_event(
        "sess_1",
        EventRecord(
            event_id="evt_1",
            session_id="sess_1",
            type="user_message",
            payload={"content": "remember storage"},
            created_at=datetime.now(UTC),
        ),
    )
    session_repo.append_event(
        "sess_1",
        EventRecord(
            event_id="evt_2",
            session_id="sess_1",
            type="assistant_message",
            payload={"content": "I will remember"},
            created_at=datetime.now(UTC),
        ),
    )
    memory_repo.add_memory(
        MemoryItem(
            memory_id="mem_1",
            session_id="sess_1",
            content="Use JSONL storage",
            tags=["storage"],
            created_at=datetime.now(UTC),
            source_event_id="evt_1",
        )
    )

    memory_manager = MemoryManager(memory_repository=memory_repo)
    tool_registry = ToolRegistry()
    tool_registry.register(MemorySearchTool(memory_repository=memory_repo))

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=skill_repo,
        memory_manager=memory_manager,
        tool_executor=tool_registry,
    )

    bundle = assembler.assemble(
        session_id="sess_1",
        user_message="how is storage",
        skill_names=["base", "memory"],
    )

    assert "[base]" in bundle.system_prompt
    assert any(message["role"] == "user" for message in bundle.messages)
    assert len(bundle.memory_hits) == 1
    assert bundle.memory_hits[0].memory_id == "mem_1"
    assert len(bundle.tool_definitions) == 1
