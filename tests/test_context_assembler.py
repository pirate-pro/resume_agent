"""Tests for context assembly."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.domain.models import EventRecord, RunContext, SessionFile
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.facade import FileMemoryFacade
from app.memory.policies import default_memory_policy
from app.memory.stores.jsonl_file_store import JsonlFileMemoryStore
from app.runtime.agent_capability import AgentCapabilityRegistry
from app.runtime.context_assembler import ContextAssembler
from app.runtime.memory_manager import MemoryManager
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.tools.builtins import MemorySearchTool
from app.tools.registry import ToolRegistry

__all__ = []


def _capability_registry() -> AgentCapabilityRegistry:
    return AgentCapabilityRegistry.for_tests()


def _context(session_id: str, agent_id: str = "agent_main") -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}",
        agent_id=agent_id,
        turn_id=f"turn_{session_id}",
        entry_agent_id=agent_id,
        parent_run_id=None,
        trace_flags={},
    )


def _state_manager(tmp_path: Path) -> StateManager:
    return StateManager(store=JsonlFileStateStore(root_dir=tmp_path / "state_v1"))



def test_context_assembler_loads_skills_events_and_memory(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    skill_repo = MarkdownSkillRepository(skills_dir=Path("app/skills"))
    state_manager = _state_manager(tmp_path)

    session_repo.create_session("sess_1")
    session_repo.append_event(
        "sess_1",
        EventRecord(
            event_id="evt_1",
            session_id="sess_1",
            type="user_message",
            payload={"content": "remember storage"},
            created_at=datetime.now(UTC),
            agent_id="agent_main",
            run_id="run_sess_1",
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
            agent_id="agent_main",
            run_id="run_sess_1",
        ),
    )
    capability_registry = _capability_registry()
    memory_manager = MemoryManager(memory_facade=memory_facade, capability_registry=capability_registry)
    memory_manager.write_memory(
        content="Use JSONL storage",
        tags=["storage", "long_term"],
        context=_context("sess_1"),
        source_event_id="evt_1",
    )
    tool_registry = ToolRegistry(capability_registry=capability_registry)
    tool_registry.register(MemorySearchTool(memory_manager=memory_manager))

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=skill_repo,
        memory_manager=memory_manager,
        state_manager=state_manager,
        tool_executor=tool_registry,
    )

    bundle = assembler.assemble(
        context=_context("sess_1"),
        user_message="how is storage",
        skill_names=["base", "memory"],
    )

    assert "[base]" in bundle.system_prompt
    assert any(message["role"] == "user" for message in bundle.messages)
    assert len(bundle.memory_hits) == 1
    assert bundle.memory_hits[0].content == "Use JSONL storage"
    assert len(bundle.tool_definitions) == 1


def test_context_assembler_includes_active_file_metadata_prompt(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    skill_repo = MarkdownSkillRepository(skills_dir=Path("app/skills"))
    session_repo.create_session("sess_2")

    parsed_path = session_repo.get_workspace_path("sess_2") / ".parsed" / "file_1.txt"
    parsed_path.parent.mkdir(parents=True, exist_ok=True)
    parsed_path.write_text("This is uploaded file content", encoding="utf-8")

    session_repo.add_or_update_session_file(
        SessionFile(
            file_id="file_1",
            session_id="sess_2",
            filename="doc.txt",
            media_type="text/plain",
            size_bytes=100,
            status="ready",
            uploaded_at=datetime.now(UTC),
            storage_relpath="workspace/uploads/file_1_doc.txt",
            text_relpath="workspace/.parsed/file_1.txt",
            error=None,
        )
    )
    session_repo.set_active_file_ids("sess_2", ["file_1"])

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=skill_repo,
        memory_manager=MemoryManager(memory_facade=memory_facade, capability_registry=_capability_registry()),
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=_capability_registry()),
    )

    bundle = assembler.assemble(
        context=_context("sess_2"),
        user_message="summarize uploaded",
        skill_names=["base"],
    )

    assert "Active session files (metadata only)" in bundle.system_prompt
    assert "file_id=file_1" in bundle.system_prompt
    assert "doc.txt" in bundle.system_prompt
    assert "session_read_file" in bundle.system_prompt


def test_context_assembler_recalls_cross_session_chinese_name_memory(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    skill_repo = MarkdownSkillRepository(skills_dir=Path("app/skills"))

    session_repo.create_session("sess_a")
    session_repo.create_session("sess_b")

    capability_registry = _capability_registry()
    memory_manager = MemoryManager(memory_facade=memory_facade, capability_registry=capability_registry)
    memory_manager.write_memory(
        content='用户要求以后叫我"李华"，这是我的新名字/称呼。',
        tags=["preference", "long_term"],
        context=_context("sess_a"),
        source_event_id="evt_rename",
    )

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=skill_repo,
        memory_manager=memory_manager,
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=capability_registry),
    )
    bundle = assembler.assemble(
        context=_context("sess_b"),
        user_message="你叫什么名字",
        skill_names=["base", "memory"],
    )

    assert any("李华" in item.content for item in bundle.memory_hits)
    assert "Relevant memories:" in bundle.system_prompt


def test_context_assembler_prioritizes_preferred_name_memory_for_name_question(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    skill_repo = MarkdownSkillRepository(skills_dir=Path("app/skills"))

    session_repo.create_session("sess_name_a")
    session_repo.create_session("sess_name_b")

    capability_registry = _capability_registry()
    memory_manager = MemoryManager(memory_facade=memory_facade, capability_registry=capability_registry)
    memory_manager.write_memory(
        content='以后叫我"李华"',
        tags=["preference", "long_term"],
        context=_context("sess_name_a"),
        source_event_id="evt_name_preferred",
    )
    memory_manager.write_memory(
        content="这个项目名字叫珍格格",
        tags=["long_term"],
        context=_context("sess_name_a"),
        source_event_id="evt_name_project",
    )

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=skill_repo,
        memory_manager=memory_manager,
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=capability_registry),
    )
    bundle = assembler.assemble(
        context=_context("sess_name_b"),
        user_message="你叫什么名字",
        skill_names=["base", "memory"],
    )

    assert len(bundle.memory_hits) >= 2
    assert bundle.memory_hits[0].content == '以后叫我"李华"'


def test_context_assembler_includes_agent_and_shared_state_prompt(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    capability_registry = _capability_registry()
    state_manager = _state_manager(tmp_path)
    session_repo.create_session("sess_state_1")
    state_manager.set_agent_state(
        session_id="sess_state_1",
        agent_id="agent_main",
        key="current_goal",
        value="拆分 state 与 memory",
    )
    state_manager.set_agent_state(
        session_id="sess_state_1",
        agent_id="agent_main",
        key="shared_goal",
        value="让协作 agent 看到阶段目标",
    )
    state_manager.publish_agent_state(
        session_id="sess_state_1",
        agent_id="agent_main",
        keys=["shared_goal"],
    )

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        memory_manager=MemoryManager(memory_facade=memory_facade, capability_registry=capability_registry),
        state_manager=state_manager,
        tool_executor=ToolRegistry(capability_registry=capability_registry),
    )

    bundle = assembler.assemble(
        context=_context("sess_state_1"),
        user_message="继续推进",
        skill_names=["base", "tools"],
    )

    assert "Current agent state:" in bundle.system_prompt
    assert "- current_goal: 拆分 state 与 memory" in bundle.system_prompt
    assert "Shared session state:" in bundle.system_prompt
    assert "- shared_goal: 让协作 agent 看到阶段目标 [owner_agent_id: agent_main]" in bundle.system_prompt


def test_context_assembler_excludes_agent_short_from_relevant_memories(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_short_1")
    memory_store = JsonlFileMemoryStore(root_dir=tmp_path / "memory_v2")
    memory_facade = FileMemoryFacade(store=memory_store, policy=default_memory_policy())
    capability_registry = _capability_registry()
    memory_manager = MemoryManager(memory_facade=memory_facade, capability_registry=capability_registry)
    memory_manager.write_memory(
        content="提到 state 这个词即可",
        tags=[],
        context=_context("sess_short_1"),
        source_event_id="evt_short",
    )

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        memory_manager=memory_manager,
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=capability_registry),
    )

    bundle = assembler.assemble(
        context=_context("sess_short_1"),
        user_message="state",
        skill_names=["base", "memory"],
    )

    assert bundle.memory_hits == []
    assert "Relevant memories:" not in bundle.system_prompt
