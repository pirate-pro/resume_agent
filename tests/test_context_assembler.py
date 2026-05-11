"""Tests for context assembly."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from app.domain.models import EventRecord, RunContext, SessionArtifact
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.file_store import FileMemoryStore
from app.runtime.agent_capability import AgentCapabilityRegistry
from app.runtime.agent_events import (
    AGENT_RESULT_SUMMARY_EVENT,
    AGENT_TASK_ASSIGNED_EVENT,
    AgentResultSummaryPayload,
    AgentTaskAssignedPayload,
)
from app.runtime.agent_registry import AgentRegistry
from app.runtime.context_assembler import ContextAssembler, ContextAssemblyRole
from app.runtime.memory_manager import MemoryManager
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.tools.builtins import DelegateAgentsTool, MemorySearchTool
from app.tools.registry import ToolRegistry

__all__ = []


def _capability_registry() -> AgentCapabilityRegistry:
    return AgentCapabilityRegistry.for_tests()


def _context(session_id: str, agent_id: str = "agent_main", entry_agent_id: str | None = None) -> RunContext:
    resolved_entry_agent_id = entry_agent_id if entry_agent_id is not None else agent_id
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}",
        agent_id=agent_id,
        turn_id=f"turn_{session_id}",
        entry_agent_id=resolved_entry_agent_id,
        parent_run_id=None,
        trace_flags={},
    )


def _state_manager(tmp_path: Path) -> StateManager:
    return StateManager(store=JsonlFileStateStore(root_dir=tmp_path / "state"))


def _agent_document_repository(root: Path | None = None) -> MarkdownAgentDocumentRepository:
    agents_dir = root if root is not None else Path("app/agents")
    return MarkdownAgentDocumentRepository(agents_dir=agents_dir)


def _memory_manager(tmp_path: Path, capability_registry: AgentCapabilityRegistry | None = None) -> MemoryManager:
    return MemoryManager(
        capability_registry=capability_registry or _capability_registry(),
        memory_store=FileMemoryStore(root_dir=tmp_path / "memory"),
    )


def _agent_registry(capability_registry: AgentCapabilityRegistry) -> AgentRegistry:
    payload = json.loads(Path("app/config/agents.json").read_text(encoding="utf-8"))
    return AgentRegistry.from_payload(
        payload,
        capability_registry=capability_registry,
        document_repository=_agent_document_repository(),
    )


def _unavailable_agent_task_runtime() -> NoReturn:
    raise AssertionError("agent task runtime should not be needed while assembling context")


def test_context_assembler_determines_main_and_other_agent_roles() -> None:
    main_context = _context("sess_role_main", agent_id="agent_main", entry_agent_id="agent_main")
    worker_context = _context("sess_role_worker", agent_id="agent_worker", entry_agent_id="agent_main")

    assert ContextAssembler.determine_role(main_context) == ContextAssemblyRole.MAIN_AGENT
    assert ContextAssembler.determine_role(worker_context) == ContextAssemblyRole.OTHER_AGENT


def test_context_assembler_injects_invokable_agent_catalog_for_main_agent(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_agent_catalog")
    capability_registry = _capability_registry()
    memory_manager = _memory_manager(tmp_path, capability_registry)
    tool_registry = ToolRegistry(capability_registry=capability_registry)
    tool_registry.register(DelegateAgentsTool(agent_task_runtime_provider=_unavailable_agent_task_runtime))

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=_agent_document_repository(),
        memory_manager=memory_manager,
        state_manager=_state_manager(tmp_path),
        tool_executor=tool_registry,
        agent_registry=_agent_registry(capability_registry),
    )

    bundle = assembler.assemble(
        context=_context("sess_agent_catalog", agent_id="agent_main", entry_agent_id="agent_main"),
        user_message="帮我分析这份简历",
        skill_names=["base"],
    )

    assert "Available child agents for delegation:" in bundle.system_prompt
    assert "agent_id=resume_agent name=ResumeAgent role=resume_parser" in bundle.system_prompt
    assert "负责简历解析、结构化和简历信息诊断" in bundle.system_prompt
    assert "agent_id=job_agent name=JobAgent role=job_analyzer" in bundle.system_prompt
    assert "负责岗位 JD 解析、岗位要求结构化和岗位匹配信号提取" in bundle.system_prompt
    assert "A single specialized task is enough reason to delegate" in bundle.system_prompt
    assert "include the relevant source text directly in the child instruction" in bundle.system_prompt
    assert "Do not create workspace files only to pass their paths to child agents" in bundle.system_prompt
    assert "Do not pass depends_on to delegate_agents" in bundle.system_prompt
    assert "Child agent ids such as resume_agent/job_agent are not tool names" in bundle.system_prompt
    assert "Use max_tool_rounds 10-20 for child tasks that must create artifacts or product records" in bundle.system_prompt
    assert "do not invent ids" in bundle.system_prompt
    assert any(definition.name == "delegate_agents" for definition in bundle.tool_definitions)


def test_context_assembler_does_not_inject_agent_catalog_for_other_agent(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_agent_catalog_child")
    capability_registry = _capability_registry()

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=_agent_document_repository(),
        memory_manager=_memory_manager(tmp_path, capability_registry),
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=capability_registry),
        agent_registry=_agent_registry(capability_registry),
    )

    bundle = assembler.assemble(
        context=_context("sess_agent_catalog_child", agent_id="resume_agent", entry_agent_id="agent_main"),
        user_message="执行简历解析子任务",
        skill_names=["base"],
    )

    assert "Available child agents for delegation:" not in bundle.system_prompt


def test_context_assembler_loads_skills_events_and_memory(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
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
    memory_manager = _memory_manager(tmp_path, capability_registry)
    memory_manager.write_memory(
        content="Use JSONL storage",
        tags=["storage", "long_term"],
        context=_context("sess_1"),
        source_event_id="evt_1",
    )
    memory_manager.write_memory(
        content="用户希望我叫李华。",
        tags=["preference", "long_term"],
        context=_context("sess_1"),
        source_event_id="evt_name",
    )
    tool_registry = ToolRegistry(capability_registry=capability_registry)
    tool_registry.register(MemorySearchTool(memory_manager=memory_manager))

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=skill_repo,
        agent_document_repository=_agent_document_repository(),
        memory_manager=memory_manager,
        state_manager=state_manager,
        tool_executor=tool_registry,
    )

    bundle = assembler.assemble(
        context=_context("sess_1"),
        user_message="how is storage",
        skill_names=["base", "memory"],
    )

    assert "Skills:" in bundle.system_prompt
    assert "- base: Core response guardrails and interaction baseline. Use for all conversations." in bundle.system_prompt
    assert "- memory: Guidance for long-term memory write and retrieval decisions." in bundle.system_prompt
    assert "你是一个务实的 Agent" not in bundle.system_prompt
    assert "Tools:" in bundle.system_prompt
    assert "- memory_search: Search memory only when relevant memory is not already present" in bundle.system_prompt
    assert "other agents are isolated by default" not in bundle.system_prompt
    assert "parameters_schema" not in bundle.system_prompt
    assert "do not call memory_search just to verify it" in bundle.system_prompt
    assert any(message["role"] == "user" for message in bundle.messages)
    assert any(item.content == "Use JSONL storage" for item in bundle.memory_hits)
    assert "Long-term summaries - Agent overlay:" in bundle.system_prompt
    assert "Long-term facts - Agent overlay" in bundle.system_prompt
    assert len(bundle.tool_definitions) == 1


def test_context_assembler_includes_active_artifact_metadata_prompt(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    skill_repo = MarkdownSkillRepository(skills_dir=Path("app/skills"))
    session_repo.create_session("sess_2")

    session_root = session_repo.get_session_root_path("sess_2")
    artifact_dir = session_root / "artifacts" / "artifact_1"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "original.bin").write_text("This is uploaded file content", encoding="utf-8")
    parsed_path = artifact_dir / "content.txt"
    parsed_path.write_text("This is uploaded file content", encoding="utf-8")

    now = datetime.now(UTC)
    session_repo.add_or_update_session_artifact(
        SessionArtifact(
            artifact_id="artifact_1",
            session_id="sess_2",
            kind="uploaded_file",
            title="doc.txt",
            media_type="text/plain",
            size_bytes=100,
            status="ready",
            visibility="session_shared",
            created_at=now,
            updated_at=now,
            storage_relpath="artifacts/artifact_1/original.bin",
            text_relpath="artifacts/artifact_1/content.txt",
            error=None,
        )
    )
    session_repo.set_active_artifact_ids("sess_2", ["artifact_1"])

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=skill_repo,
        agent_document_repository=_agent_document_repository(),
        memory_manager=_memory_manager(tmp_path),
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=_capability_registry()),
    )

    bundle = assembler.assemble(
        context=_context("sess_2"),
        user_message="summarize uploaded",
        skill_names=["base"],
    )

    assert "Active session artifacts (metadata only)" in bundle.system_prompt
    assert "artifact_id=artifact_1" in bundle.system_prompt
    assert "doc.txt" in bundle.system_prompt
    assert "session_read_artifact" in bundle.system_prompt


def test_context_assembler_recalls_cross_session_chinese_name_memory(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    skill_repo = MarkdownSkillRepository(skills_dir=Path("app/skills"))

    session_repo.create_session("sess_a")
    session_repo.create_session("sess_b")

    capability_registry = _capability_registry()
    memory_manager = _memory_manager(tmp_path, capability_registry)
    memory_manager.write_memory(
        content='用户要求以后叫我"李华"，这是我的新名字/称呼。',
        tags=["preference", "long_term"],
        context=_context("sess_a"),
        source_event_id="evt_rename",
    )

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=skill_repo,
        agent_document_repository=_agent_document_repository(),
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
    assert "Long-term facts - Agent overlay / Identity:" in bundle.system_prompt


def test_context_assembler_prioritizes_preferred_name_memory_for_name_question(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    skill_repo = MarkdownSkillRepository(skills_dir=Path("app/skills"))

    session_repo.create_session("sess_name_a")
    session_repo.create_session("sess_name_b")

    capability_registry = _capability_registry()
    memory_manager = _memory_manager(tmp_path, capability_registry)
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
        agent_document_repository=_agent_document_repository(),
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
        agent_document_repository=_agent_document_repository(),
        memory_manager=_memory_manager(tmp_path, capability_registry),
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
    assert "Main orchestration state:" in bundle.system_prompt
    assert "- shared_goal: 让协作 agent 看到阶段目标 [owner_agent_id: agent_main]" in bundle.system_prompt


def test_context_assembler_excludes_shared_state_for_other_agent(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    capability_registry = _capability_registry()
    state_manager = _state_manager(tmp_path)
    session_repo.create_session("sess_state_worker")
    state_manager.set_agent_state(
        session_id="sess_state_worker",
        agent_id="agent_worker",
        key="worker_progress",
        value="正在处理局部任务",
    )
    state_manager.set_agent_state(
        session_id="sess_state_worker",
        agent_id="agent_main",
        key="overall_goal",
        value="主 agent 的总体编排进度",
    )
    state_manager.publish_agent_state(
        session_id="sess_state_worker",
        agent_id="agent_main",
        keys=["overall_goal"],
    )

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=_agent_document_repository(),
        memory_manager=_memory_manager(tmp_path, capability_registry),
        state_manager=state_manager,
        tool_executor=ToolRegistry(capability_registry=capability_registry),
    )

    bundle = assembler.assemble(
        context=_context("sess_state_worker", agent_id="agent_worker", entry_agent_id="agent_main"),
        user_message="执行你的局部任务",
        skill_names=["base", "tools"],
    )

    assert "Current agent state:" in bundle.system_prompt
    assert "- worker_progress: 正在处理局部任务" in bundle.system_prompt
    assert "Main orchestration state:" not in bundle.system_prompt
    assert "主 agent 的总体编排进度" not in bundle.system_prompt


def test_context_assembler_injects_assigned_task_for_other_agent(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_task_worker")
    now = datetime.now(UTC)
    session_repo.append_event(
        "sess_task_worker",
        EventRecord(
            event_id="evt_assign_worker",
            session_id="sess_task_worker",
            type=AGENT_TASK_ASSIGNED_EVENT,
            payload=AgentTaskAssignedPayload(
                task_id="task_worker_1",
                source_agent_id="agent_main",
                target_agent_id="agent_worker",
                instruction="分析 memory scaffold 的风险",
                constraints=["不要改调度链路"],
                artifact_refs=["artifact_design_001"],
                parent_run_id="run_main",
            ).to_payload(),
            created_at=now,
            agent_id="agent_main",
            run_id="run_main",
        ),
    )
    session_repo.append_event(
        "sess_task_worker",
        EventRecord(
            event_id="evt_assign_sibling",
            session_id="sess_task_worker",
            type=AGENT_TASK_ASSIGNED_EVENT,
            payload=AgentTaskAssignedPayload(
                task_id="task_sibling_1",
                source_agent_id="agent_main",
                target_agent_id="agent_sibling",
                instruction="这是 sibling 的任务",
                parent_run_id="run_main",
            ).to_payload(),
            created_at=now,
            agent_id="agent_main",
            run_id="run_main",
        ),
    )

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=_agent_document_repository(),
        memory_manager=_memory_manager(tmp_path),
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=_capability_registry()),
    )

    bundle = assembler.assemble(
        context=_context("sess_task_worker", agent_id="agent_worker", entry_agent_id="agent_main"),
        user_message="开始执行",
        skill_names=["base"],
    )

    assert "Assigned agent tasks:" in bundle.system_prompt
    assert "task_id=task_worker_1 from=agent_main instruction=分析 memory scaffold 的风险" in bundle.system_prompt
    assert "constraints: 不要改调度链路" in bundle.system_prompt
    assert "这是 sibling 的任务" not in bundle.system_prompt


def test_context_assembler_injects_child_result_summary_for_main_agent(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_child_result")
    session_repo.append_event(
        "sess_child_result",
        EventRecord(
            event_id="evt_child_result",
            session_id="sess_child_result",
            type=AGENT_RESULT_SUMMARY_EVENT,
            payload=AgentResultSummaryPayload(
                task_id="task_worker_1",
                source_agent_id="agent_worker",
                target_agent_id="agent_main",
                status="completed",
                summary="worker 已完成 scaffold 风险检查",
                next_steps=["main agent 决定是否继续实现调度"],
                parent_run_id="run_main",
            ).to_payload(),
            created_at=datetime.now(UTC),
            agent_id="agent_worker",
            run_id="run_worker",
            parent_run_id="run_main",
        ),
    )

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=_agent_document_repository(),
        memory_manager=_memory_manager(tmp_path),
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=_capability_registry()),
    )

    bundle = assembler.assemble(
        context=_context("sess_child_result", agent_id="agent_main", entry_agent_id="agent_main"),
        user_message="继续编排",
        skill_names=["base"],
    )

    assert "Child agent result summaries:" in bundle.system_prompt
    assert "task_id=task_worker_1 agent=agent_worker status=completed" in bundle.system_prompt
    assert "worker 已完成 scaffold 风险检查" in bundle.system_prompt
    assert "main agent 决定是否继续实现调度" in bundle.system_prompt


def test_context_assembler_main_agent_excludes_child_raw_messages(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_id = "sess_main_child_raw_filter"
    session_repo.create_session(session_id)
    now = datetime.now(UTC)
    session_repo.append_event(
        session_id,
        EventRecord(
            event_id="evt_main_user",
            session_id=session_id,
            type="user_message",
            payload={"content": "main user instruction"},
            created_at=now,
            agent_id="agent_main",
            run_id="run_main",
        ),
    )
    session_repo.append_event(
        session_id,
        EventRecord(
            event_id="evt_child_user",
            session_id=session_id,
            type="user_message",
            payload={"content": "child private instruction"},
            created_at=now,
            agent_id="resume_agent",
            run_id="run_child",
            parent_run_id="run_main",
        ),
    )
    session_repo.append_event(
        session_id,
        EventRecord(
            event_id="evt_child_assistant",
            session_id=session_id,
            type="assistant_message",
            payload={"content": "child private detailed answer"},
            created_at=now,
            agent_id="resume_agent",
            run_id="run_child",
            parent_run_id="run_main",
        ),
    )
    session_repo.append_event(
        session_id,
        EventRecord(
            event_id="evt_child_result",
            session_id=session_id,
            type=AGENT_RESULT_SUMMARY_EVENT,
            payload=AgentResultSummaryPayload(
                task_id="task_resume_1",
                source_agent_id="resume_agent",
                target_agent_id="agent_main",
                status="completed",
                summary="resume_agent 已输出简历摘要",
                parent_run_id="run_main",
            ).to_payload(),
            created_at=now,
            agent_id="resume_agent",
            run_id="run_child",
            parent_run_id="run_main",
        ),
    )

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=_agent_document_repository(),
        memory_manager=_memory_manager(tmp_path),
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=_capability_registry()),
    )

    bundle = assembler.assemble(
        context=_context(session_id, agent_id="agent_main", entry_agent_id="agent_main"),
        user_message="继续编排",
        skill_names=["base"],
    )
    message_contents = [str(message.get("content", "")) for message in bundle.messages]

    assert "main user instruction" in message_contents
    assert "继续编排" in message_contents
    assert "child private instruction" not in message_contents
    assert "child private detailed answer" not in message_contents
    assert "Child agent result summaries:" in bundle.system_prompt
    assert "resume_agent 已输出简历摘要" in bundle.system_prompt


def test_context_assembler_filters_recent_events_for_other_agent(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_events_worker")
    now = datetime.now(UTC)
    session_repo.append_event(
        "sess_events_worker",
        EventRecord(
            event_id="evt_main_user",
            session_id="sess_events_worker",
            type="user_message",
            payload={"content": "root session instruction"},
            created_at=now,
            agent_id="agent_main",
            run_id="run_main",
        ),
    )
    session_repo.append_event(
        "sess_events_worker",
        EventRecord(
            event_id="evt_worker_user",
            session_id="sess_events_worker",
            type="user_message",
            payload={"content": "worker task instruction"},
            created_at=now,
            agent_id="agent_worker",
            run_id="run_sess_events_worker",
            parent_run_id="run_main",
        ),
    )
    session_repo.append_event(
        "sess_events_worker",
        EventRecord(
            event_id="evt_sibling_assistant",
            session_id="sess_events_worker",
            type="assistant_message",
            payload={"content": "sibling private progress"},
            created_at=now,
            agent_id="agent_sibling",
            run_id="run_sibling",
            parent_run_id="run_main",
        ),
    )
    session_repo.append_event(
        "sess_events_worker",
        EventRecord(
            event_id="evt_worker_assistant",
            session_id="sess_events_worker",
            type="assistant_message",
            payload={"content": "worker local progress"},
            created_at=now,
            agent_id="agent_worker",
            run_id="run_sess_events_worker",
            parent_run_id="run_main",
        ),
    )

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=_agent_document_repository(),
        memory_manager=_memory_manager(tmp_path),
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=_capability_registry()),
    )

    bundle = assembler.assemble(
        context=_context("sess_events_worker", agent_id="agent_worker", entry_agent_id="agent_main"),
        user_message="continue worker",
        skill_names=["base"],
    )
    message_contents = [str(message.get("content", "")) for message in bundle.messages]

    assert "worker task instruction" in message_contents
    assert "worker local progress" in message_contents
    assert "continue worker" in message_contents
    assert "root session instruction" not in message_contents
    assert "sibling private progress" not in message_contents


def test_context_assembler_excludes_agent_short_from_relevant_memories(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_short_1")
    capability_registry = _capability_registry()
    memory_manager = _memory_manager(tmp_path, capability_registry)
    memory_manager.write_memory(
        content="提到 state 这个词即可",
        tags=[],
        context=_context("sess_short_1"),
        source_event_id="evt_short",
    )

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=_agent_document_repository(),
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
    assert "Long-term facts -" not in bundle.system_prompt


def test_context_assembler_injects_memory_lanes_separately(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_lane_prompt")
    capability_registry = _capability_registry()
    memory_manager = _memory_manager(tmp_path, capability_registry)
    memory_manager.write_memory(
        content="以后回答简洁一点",
        tags=["preference", "long_term"],
        context=_context("sess_lane_prompt"),
        source_event_id="evt_lane_prompt_style",
    )
    memory_manager.write_memory(
        content="用户长期目标是提升后端工程能力",
        tags=["long_term"],
        context=_context("sess_lane_prompt"),
        source_event_id="evt_lane_prompt_goal",
    )

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=_agent_document_repository(),
        memory_manager=memory_manager,
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=capability_registry),
    )

    bundle = assembler.assemble(
        context=_context("sess_lane_prompt"),
        user_message="后端怎么继续优化",
        skill_names=["base", "memory"],
    )

    assert "Long-term facts - Agent overlay / Response preferences:" in bundle.system_prompt
    assert "以后回答简洁一点" in bundle.system_prompt
    assert "Long-term facts - Agent overlay / User profile:" in bundle.system_prompt
    assert "用户长期目标是提升后端工程能力" in bundle.system_prompt
    assert set(bundle.memory_lanes) == {"response_preferences", "user_profile"}


def test_context_assembler_injects_long_term_summaries_separately(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_long_summary_prompt")
    capability_registry = _capability_registry()
    memory_manager = _memory_manager(tmp_path, capability_registry)
    long_term_path = tmp_path / "memory" / "shared" / "long_term.json"
    payload = json.loads(long_term_path.read_text(encoding="utf-8"))
    payload["user"]["workContext"]["summary"] = "用户长期在优化 Agent runtime 和 memory 系统。"
    payload["user"]["workContext"]["updatedAt"] = "2026-04-29T00:00:00Z"
    long_term_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=_agent_document_repository(),
        memory_manager=memory_manager,
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=capability_registry),
    )

    bundle = assembler.assemble(
        context=_context("sess_long_summary_prompt"),
        user_message="Agent runtime 的 memory 怎么继续优化",
        skill_names=["base", "memory"],
    )

    assert any(item.memory_layer == "long_term" for item in bundle.memory_hits)
    assert "Long-term summaries - Shared:" in bundle.system_prompt
    assert "用户长期在优化 Agent runtime 和 memory 系统" in bundle.system_prompt
    assert "Long-term facts - Shared / Other relevant memory:" not in bundle.system_prompt


def test_context_assembler_injects_mid_term_context_separately(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_mid_term_prompt")
    capability_registry = _capability_registry()
    memory_manager = _memory_manager(tmp_path, capability_registry)
    daily_path = tmp_path / "memory" / "shared" / "mid_term" / "daily" / "2026-05-01.md"
    daily_path.parent.mkdir(parents=True, exist_ok=True)
    daily_path.write_text(
        "# 2026-05-01\n\n## Active Context\n\n- 用户最近在优化后端 ContextAssembler 的 multi-agent 注入边界。",
        encoding="utf-8",
    )

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=_agent_document_repository(),
        memory_manager=memory_manager,
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=capability_registry),
    )

    bundle = assembler.assemble(
        context=_context("sess_mid_term_prompt"),
        user_message="后端 ContextAssembler 接下来怎么做",
        skill_names=["base", "memory"],
    )

    assert any("ContextAssembler" in item.content for item in bundle.memory_hits)
    assert "Mid-term context:" in bundle.system_prompt
    assert "用户最近在优化后端 ContextAssembler" in bundle.system_prompt
    assert "Long-term facts - Agent overlay / Other relevant memory:" not in bundle.system_prompt


def test_context_assembler_injects_agent_and_soul_documents_before_skills(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_identity_1")
    docs_dir = tmp_path / "agents"
    agent_dir = docs_dir / "agent_main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENT.md").write_text("# Rules\n\n- 永远不要伪造工具结果。", encoding="utf-8")
    (agent_dir / "SOUL.md").write_text("# Soul\n\n冷静、直接、协作。", encoding="utf-8")

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=_agent_document_repository(docs_dir),
        memory_manager=_memory_manager(tmp_path),
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=_capability_registry()),
    )

    bundle = assembler.assemble(
        context=_context("sess_identity_1"),
        user_message="继续",
        skill_names=["base"],
    )

    assert "AGENT.md:\n# Rules" in bundle.system_prompt
    assert "SOUL.md:\n# Soul" in bundle.system_prompt
    assert bundle.system_prompt.index("AGENT.md:") < bundle.system_prompt.index("SOUL.md:")
    assert bundle.system_prompt.index("SOUL.md:") < bundle.system_prompt.index("Skills:")


def test_context_assembler_skips_agent_documents_when_repository_unavailable(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_identity_2")

    assembler = ContextAssembler(
        session_repository=session_repo,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=_agent_document_repository(tmp_path / "missing_agents"),
        memory_manager=_memory_manager(tmp_path),
        state_manager=_state_manager(tmp_path),
        tool_executor=ToolRegistry(capability_registry=_capability_registry()),
    )

    bundle = assembler.assemble(
        context=_context("sess_identity_2"),
        user_message="继续",
        skill_names=["base"],
    )

    assert "AGENT.md:" not in bundle.system_prompt
    assert "SOUL.md:" not in bundle.system_prompt
    assert "Skills:" in bundle.system_prompt
