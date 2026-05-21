"""Tests for concurrent delegated agent task groups."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.errors import ToolExecutionError, ValidationError
from app.domain.models import RunContext, SessionArtifact, ToolCall
from app.domain.protocols import ModelResponse, StreamChunk
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.jsonl_agent_task_store import JsonlAgentTaskStore
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.file_store import FileMemoryStore
from app.memory.models import MemoryScope
from app.runtime.agent_capability import AgentCapability, AgentCapabilityRegistry
from app.runtime.agent_registry import AgentRegistry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.event_recorder import EventRecorder
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.services.agent_invocation_service import AgentInvocationService
from app.services.agent_task_runtime import (
    AgentTaskGroupRequest,
    AgentTaskRuntime,
    AgentTaskSpec,
)
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.tools.builtin_tools.agents import AgentTaskStatusTool, DelegateAgentsTool
from app.tools.builtin_tools.memory import MemorySearchTool
from app.tools.registry import ToolRegistry

__all__ = []


def _add_shared_artifact(repository: JsonlSessionRepository, session_id: str, artifact_id: str) -> None:
    root = repository.get_session_root_path(session_id)
    artifact_dir = root / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "original.bin").write_text("resume content", encoding="utf-8")
    (artifact_dir / "content.txt").write_text("resume content", encoding="utf-8")
    now = datetime.now(UTC)
    repository.add_or_update_session_artifact(
        SessionArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            kind="uploaded_file",
            title="resume.txt",
            media_type="text/plain",
            size_bytes=14,
            status="ready",
            visibility="session_shared",
            created_at=now,
            updated_at=now,
            storage_relpath=f"artifacts/{artifact_id}/original.bin",
            text_relpath=f"artifacts/{artifact_id}/content.txt",
            text_char_count=14,
            token_estimate=4,
            parsed_at=now,
        )
    )


class ConcurrentCaptureModelClient:
    """Return deterministic answers while tracking overlapping generate calls."""

    def __init__(self, delay_seconds: float = 0.05) -> None:
        self._delay_seconds = delay_seconds
        self._lock = threading.Lock()
        self._active = 0
        self.max_active = 0
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            time.sleep(self._delay_seconds)
            user_message = str(messages[-1].get("content", "")) if messages else ""
            self.calls.append(
                {
                    "system_prompt": system_prompt,
                    "messages": messages,
                    "tools": tools,
                    "user_message": user_message,
                }
            )
            return ModelResponse(content=f"completed: {user_message[:40]}", tool_calls=[])
        finally:
            with self._lock:
                self._active -= 1

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        response = self.generate(system_prompt=system_prompt, messages=messages, tools=tools)
        yield StreamChunk(delta=response.content, finished=False, has_tool_call_delta=False)
        yield StreamChunk(delta="", tool_calls=[], finished=True, has_tool_call_delta=False)


class ToolProgressModelClient:
    """Drive one child run through a tool call so progress projection can be tested."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = (system_prompt, messages, tools)
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                content="我会先检索资料，再做简历诊断。",
                tool_calls=[
                    ToolCall(
                        name="memory_search",
                        arguments={"query": "不要展示的搜索词", "limit": 3},
                        tool_call_id="call_progress_secret",
                    )
                ],
            )
        return ModelResponse(
            content="完成简历诊断，产物为 artifact_progress_001 和 resume_profile_progress_001。",
            tool_calls=[],
        )

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        response = self.generate(system_prompt=system_prompt, messages=messages, tools=tools)
        if response.content:
            yield StreamChunk(delta=response.content, finished=False, has_tool_call_delta=False)
        yield StreamChunk(
            delta="",
            tool_calls=response.tool_calls,
            finished=True,
            has_tool_call_delta=bool(response.tool_calls),
        )


@dataclass(slots=True)
class RuntimeBundle:
    task_runtime: AgentTaskRuntime
    tool_registry: ToolRegistry
    session_repository: JsonlSessionRepository
    task_store: JsonlAgentTaskStore
    model_client: Any


def _write_docs(root: Path, agent_id: str, *, agent_text: str, soul_text: str) -> None:
    agent_dir = root / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENT.md").write_text(agent_text, encoding="utf-8")
    (agent_dir / "SOUL.md").write_text(soul_text, encoding="utf-8")


def _capability_registry() -> AgentCapabilityRegistry:
    return AgentCapabilityRegistry(
        {
            "agent_main": AgentCapability(
                agent_id="agent_main",
                allowed_tools=["delegate_agents", "agent_task_status", "memory_search"],
                allowed_skills=["*"],
                default_skills=["base", "memory", "tools"],
                memory_read_scopes=[MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                memory_write_scopes=[MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
            ),
            "resume_agent": AgentCapability(
                agent_id="resume_agent",
                allowed_tools=["memory_search"],
                allowed_skills=["base", "tools", "file-reader"],
                default_skills=["base", "tools", "file-reader"],
                memory_read_scopes=[MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                memory_write_scopes=[MemoryScope.AGENT_LONG],
            ),
            "job_agent": AgentCapability(
                agent_id="job_agent",
                allowed_tools=["memory_search"],
                allowed_skills=["base", "tools", "file-reader"],
                default_skills=["base", "tools", "file-reader"],
                memory_read_scopes=[MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                memory_write_scopes=[MemoryScope.AGENT_LONG],
            ),
        }
    )


def _registry_payload() -> dict[str, object]:
    return {
        "agents": [
            {
                "agent_id": "agent_main",
                "display_name": "MainCareerAgent",
                "description": "主 agent",
                "role": "main_orchestrator",
                "enabled": True,
                "is_main_agent": True,
                "document_agent_id": "default",
                "can_invoke_agents": True,
                "invokable_agent_ids": ["resume_agent", "job_agent"],
            },
            {
                "agent_id": "resume_agent",
                "display_name": "ResumeAgent",
                "description": "简历 agent",
                "role": "resume_parser",
                "enabled": True,
                "is_main_agent": False,
                "document_agent_id": "resume_agent",
                "can_invoke_agents": False,
                "invokable_agent_ids": [],
            },
            {
                "agent_id": "job_agent",
                "display_name": "JobAgent",
                "description": "岗位 agent",
                "role": "job_analyzer",
                "enabled": True,
                "is_main_agent": False,
                "document_agent_id": "job_agent",
                "can_invoke_agents": False,
                "invokable_agent_ids": [],
            },
        ],
    }


def _source_context(session_id: str = "sess_delegate") -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id="run_main",
        agent_id="agent_main",
        turn_id="turn_main",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={},
    )


def _build_bundle(tmp_path: Path, model_client: Any | None = None) -> RuntimeBundle:
    session_repository = JsonlSessionRepository(data_dir=tmp_path / "sessions")
    state_manager = StateManager(store=JsonlFileStateStore(root_dir=tmp_path / "state"))
    capability_registry = _capability_registry()
    memory_manager = MemoryManager(
        capability_registry=capability_registry,
        memory_store=FileMemoryStore(root_dir=tmp_path / "memory"),
    )
    agents_dir = tmp_path / "agents"
    _write_docs(agents_dir, "default", agent_text="# Main Agent", soul_text="# Main Soul")
    _write_docs(agents_dir, "resume_agent", agent_text="# Resume Agent", soul_text="# Resume Soul")
    _write_docs(agents_dir, "job_agent", agent_text="# Job Agent", soul_text="# Job Soul")
    agent_document_repository = MarkdownAgentDocumentRepository(agents_dir=agents_dir)
    resolved_model_client = model_client or ConcurrentCaptureModelClient()
    tool_registry = ToolRegistry(capability_registry=capability_registry)
    context_assembler = ContextAssembler(
        session_repository=session_repository,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=agent_document_repository,
        memory_manager=memory_manager,
        state_manager=state_manager,
        tool_executor=tool_registry,
    )
    event_recorder = EventRecorder(session_repository=session_repository)
    runtime = AgentRuntime(
        session_manager=SessionManager(session_repository=session_repository),
        event_recorder=event_recorder,
        context_assembler=context_assembler,
        model_client=resolved_model_client,
        tool_executor=tool_registry,
    )
    agent_registry = AgentRegistry.from_payload(
        _registry_payload(),
        capability_registry=capability_registry,
        document_repository=agent_document_repository,
    )
    invocation_service = AgentInvocationService(
        agent_registry=agent_registry,
        runtime=runtime,
        event_recorder=event_recorder,
        session_repository=session_repository,
    )
    task_store = JsonlAgentTaskStore(data_dir=tmp_path / "sessions")
    task_runtime = AgentTaskRuntime(
        invocation_service=invocation_service,
        task_store=task_store,
        event_recorder=event_recorder,
        default_max_concurrency=2,
    )
    tool_registry.register(DelegateAgentsTool(agent_task_runtime_provider=lambda: task_runtime))
    tool_registry.register(AgentTaskStatusTool(agent_task_store_provider=lambda: task_store))
    tool_registry.register(MemorySearchTool(memory_manager=memory_manager))
    return RuntimeBundle(
        task_runtime=task_runtime,
        tool_registry=tool_registry,
        session_repository=session_repository,
        task_store=task_store,
        model_client=resolved_model_client,
    )


def test_agent_task_runtime_runs_independent_child_tasks_concurrently(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_delegate")

    result = bundle.task_runtime.run_group(
        AgentTaskGroupRequest(
            source_context=_source_context(),
            max_concurrency=2,
            tasks=[
                AgentTaskSpec(target_agent_id="resume_agent", instruction="提取项目经历 A", max_tool_rounds=0),
                AgentTaskSpec(target_agent_id="resume_agent", instruction="提取教育经历 B", max_tool_rounds=0),
            ],
        )
    )

    assert result.status == "completed"
    assert len(result.results) == 2
    assert bundle.model_client.max_active >= 2


def test_agent_task_runtime_records_progress_events_without_raw_instruction(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_delegate")

    result = bundle.task_runtime.run_group(
        AgentTaskGroupRequest(
            source_context=_source_context(),
            max_concurrency=1,
            tasks=[
                AgentTaskSpec(
                    target_agent_id="resume_agent",
                    instruction="需要保密的完整指令：解析简历并输出详细诊断",
                    max_tool_rounds=0,
                )
            ],
        )
    )

    assert result.status == "completed"
    progress_events = [
        event
        for event in bundle.session_repository.list_events("sess_delegate")
        if event.type
        in {
            "agent_task_group_created",
            "agent_task_started",
            "agent_task_completed",
            "agent_task_group_completed",
        }
    ]
    assert {event.type for event in progress_events} == {
        "agent_task_group_created",
        "agent_task_started",
        "agent_task_completed",
        "agent_task_group_completed",
    }
    payload_text = json.dumps([event.payload for event in progress_events], ensure_ascii=False)
    assert "需要保密的完整指令" not in payload_text
    assert "resume_agent" in payload_text
    assert result.task_group_id in payload_text


def test_child_agent_tool_events_are_projected_as_safe_task_progress(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path, model_client=ToolProgressModelClient())
    bundle.session_repository.create_session("sess_delegate")

    result = bundle.task_runtime.run_group(
        AgentTaskGroupRequest(
            source_context=_source_context(),
            max_concurrency=1,
            tasks=[
                AgentTaskSpec(
                    target_agent_id="resume_agent",
                    instruction="需要保密的完整指令：解析简历并输出详细诊断",
                    max_tool_rounds=1,
                )
            ],
        )
    )

    assert result.status == "completed"
    assert result.results[0].output_artifact_refs == []
    assert result.results[0].artifact_refs == []
    assert result.results[0].product_refs == ["resume_profile_progress_001"]
    visible_events = bundle.session_repository.list_events("sess_delegate")
    result_summary_events = [event for event in visible_events if event.type == "agent_result_summary"]
    assert result_summary_events[0].payload["output_artifact_refs"] == []
    assert result_summary_events[0].payload["product_refs"] == ["resume_profile_progress_001"]
    progress_events = [event for event in visible_events if event.type == "agent_task_progress"]
    source_types = {event.payload["source_event_type"] for event in progress_events}
    assert {"tool_call", "tool_result", "assistant_message"} <= source_types

    payload_text = json.dumps([event.payload for event in progress_events], ensure_ascii=False)
    assert "需要保密的完整指令" not in payload_text
    assert "不要展示的搜索词" not in payload_text
    assert "memory_search" in payload_text
    assert "current_action" in payload_text
    assert "next_action" in payload_text
    assert "正在检索可复用上下文" in payload_text
    assert "artifact_progress_001" in payload_text
    assert "resume_profile_progress_001" in payload_text

    for event in progress_events:
        assert event.parent_run_id == "run_main"
        assert event.run_id.startswith("run_")
        assert event.payload["child_run_id"] == event.run_id
        assert event.payload["target_agent_id"] == "resume_agent"
        assert "detail" in event.payload
        assert event.payload["total_steps"] == 7
        assert 1 <= event.payload["step_index"] <= 7
        assert event.payload["phase"]


def test_same_target_child_prompt_only_receives_its_own_assigned_task(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_delegate")

    bundle.task_runtime.run_group(
        AgentTaskGroupRequest(
            source_context=_source_context(),
            max_concurrency=2,
            tasks=[
                AgentTaskSpec(target_agent_id="resume_agent", instruction="只处理任务 Alpha", max_tool_rounds=0),
                AgentTaskSpec(target_agent_id="resume_agent", instruction="只处理任务 Beta", max_tool_rounds=0),
            ],
        )
    )

    prompts = [call["system_prompt"] for call in bundle.model_client.calls]
    alpha_prompts = [prompt for prompt in prompts if "只处理任务 Alpha" in prompt]
    beta_prompts = [prompt for prompt in prompts if "只处理任务 Beta" in prompt]
    assert len(alpha_prompts) == 1
    assert len(beta_prompts) == 1
    assert "只处理任务 Beta" not in alpha_prompts[0]
    assert "只处理任务 Alpha" not in beta_prompts[0]


def test_different_child_agents_run_concurrently_and_keep_contexts_isolated(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_delegate")

    result = bundle.task_runtime.run_group(
        AgentTaskGroupRequest(
            source_context=_source_context(),
            max_concurrency=2,
            tasks=[
                AgentTaskSpec(target_agent_id="resume_agent", instruction="只分析简历 Alpha", max_tool_rounds=0),
                AgentTaskSpec(target_agent_id="job_agent", instruction="只分析岗位 Beta", max_tool_rounds=0),
            ],
        )
    )

    assert result.status == "completed"
    assert {item.target_agent_id for item in result.results} == {"resume_agent", "job_agent"}
    assert bundle.model_client.max_active >= 2

    prompts = [call["system_prompt"] for call in bundle.model_client.calls]
    resume_prompts = [prompt for prompt in prompts if "只分析简历 Alpha" in prompt]
    job_prompts = [prompt for prompt in prompts if "只分析岗位 Beta" in prompt]
    assert len(resume_prompts) == 1
    assert len(job_prompts) == 1
    assert "AGENT.md:\n# Resume Agent" in resume_prompts[0]
    assert "AGENT.md:\n# Job Agent" not in resume_prompts[0]
    assert "只分析岗位 Beta" not in resume_prompts[0]
    assert "AGENT.md:\n# Job Agent" in job_prompts[0]
    assert "AGENT.md:\n# Resume Agent" not in job_prompts[0]
    assert "只分析简历 Alpha" not in job_prompts[0]

    events = (
        bundle.session_repository.list_agent_events("sess_delegate", "resume_agent")
        + bundle.session_repository.list_agent_events("sess_delegate", "job_agent")
    )
    child_started = [event for event in events if event.type == "run_started" and event.parent_run_id == "run_main"]
    assert {event.agent_id for event in child_started} == {"resume_agent", "job_agent"}


def test_delegate_agents_tool_returns_aggregated_results(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_delegate")
    _add_shared_artifact(bundle.session_repository, "sess_delegate", "artifact_resume_001")
    definition = next(item for item in bundle.tool_registry.list_definitions() if item.name == "delegate_agents")
    task_properties = definition.parameters_schema["properties"]["tasks"]["items"]["properties"]

    assert "depends_on" not in task_properties
    assert task_properties["max_tool_rounds"]["default"] == 10

    result = bundle.tool_registry.execute(
        ToolCall(
            name="delegate_agents",
            arguments={
                "wait": True,
                "max_concurrency": 2,
                "tasks": [
                    {"target_agent_id": "resume_agent", "instruction": "解析简历文件", "max_tool_rounds": 0},
                    {"target_agent_id": "resume_agent", "instruction": "检查简历缺口", "max_tool_rounds": 0},
                ],
            },
        ),
        _source_context(),
    )

    payload = json.loads(result.content)
    assert result.success is True
    assert payload["status"] == "completed"
    assert len(payload["results"]) == 2
    assert all(item["target_agent_id"] == "resume_agent" for item in payload["results"])


def test_delegate_agents_tool_accepts_json_string_tasks(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_delegate")

    result = bundle.tool_registry.execute(
        ToolCall(
            name="delegate_agents",
            arguments={
                "wait": True,
                "tasks": json.dumps(
                    [{"target_agent_id": "resume_agent", "instruction": "解析简历文件", "max_tool_rounds": 0}],
                    ensure_ascii=False,
                ),
            },
        ),
        _source_context(),
    )
    payload = json.loads(result.content)

    assert result.success is True
    assert payload["status"] == "completed"
    assert payload["results"][0]["target_agent_id"] == "resume_agent"


def test_delegate_agents_tool_returns_noop_for_empty_task_list(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_delegate")

    result = bundle.tool_registry.execute(
        ToolCall(name="delegate_agents", arguments={"wait": True, "tasks": []}),
        _source_context(),
    )
    payload = json.loads(result.content)

    assert result.success is True
    assert payload["status"] == "skipped"
    assert payload["results"] == []
    assert "target_agent_id" in payload["hint"]

    missing_tasks_result = bundle.tool_registry.execute(
        ToolCall(name="delegate_agents", arguments={"wait": True}),
        _source_context(),
    )
    missing_tasks_payload = json.loads(missing_tasks_result.content)

    assert missing_tasks_result.success is True
    assert missing_tasks_payload["status"] == "skipped"
    assert missing_tasks_payload["results"] == []

    invalid_tasks_result = bundle.tool_registry.execute(
        ToolCall(name="delegate_agents", arguments={"wait": True, "tasks": "not-json"}),
        _source_context(),
    )
    invalid_tasks_payload = json.loads(invalid_tasks_result.content)

    assert invalid_tasks_result.success is True
    assert invalid_tasks_payload["status"] == "skipped"
    assert invalid_tasks_payload["results"] == []


def test_agent_task_status_tool_returns_persisted_task_group(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_delegate")

    delegated = bundle.tool_registry.execute(
        ToolCall(
            name="delegate_agents",
            arguments={
                "wait": True,
                "tasks": [
                    {"target_agent_id": "resume_agent", "instruction": "解析简历文件", "max_tool_rounds": 0},
                    {"target_agent_id": "job_agent", "instruction": "分析岗位文件", "max_tool_rounds": 0},
                ],
            },
        ),
        _source_context(),
    )
    delegated_payload = json.loads(delegated.content)

    status_result = bundle.tool_registry.execute(
        ToolCall(
            name="agent_task_status",
            arguments={"task_group_id": delegated_payload["task_group_id"]},
        ),
        _source_context(),
    )
    status_payload = json.loads(status_result.content)

    assert status_result.success is True
    assert status_payload["task_group_id"] == delegated_payload["task_group_id"]
    assert status_payload["status"] == "completed"
    assert {task["target_agent_id"] for task in status_payload["tasks"]} == {"resume_agent", "job_agent"}
    assert all(task["child_run_id"] for task in status_payload["tasks"])
    assert all(task["summary"] for task in status_payload["tasks"])


def test_delegate_agents_tool_accepts_session_artifact_refs(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_delegate")
    _add_shared_artifact(bundle.session_repository, "sess_delegate", "artifact_resume_001")

    result = bundle.tool_registry.execute(
        ToolCall(
            name="delegate_agents",
            arguments={
                "wait": True,
                "tasks": [
                    {
                        "target_agent_id": "resume_agent",
                        "instruction": "解析已上传简历文件",
                        "artifact_refs": ["artifact_resume_001"],
                        "max_tool_rounds": 0,
                    }
                ],
            },
        ),
        _source_context(),
    )

    payload = json.loads(result.content)
    assert result.success is True
    assert payload["results"][0]["artifact_refs"] == ["artifact_resume_001"]
    child_message = bundle.model_client.calls[-1]["user_message"]
    assert "artifact 事实源规则" in child_message
    assert "artifact 内容预览" in child_message
    assert "resume content" in child_message


def test_delegate_agents_tool_rejects_workspace_path_artifact_refs(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_delegate")

    with pytest.raises(ToolExecutionError, match="not workspace paths or filenames"):
        bundle.tool_registry.execute(
            ToolCall(
                name="delegate_agents",
                arguments={
                    "tasks": [
                        {
                            "target_agent_id": "resume_agent",
                            "instruction": "解析 main-agent 临时文件",
                            "artifact_refs": ["resume.txt"],
                            "max_tool_rounds": 0,
                        }
                    ],
                },
            ),
            _source_context(),
        )


def test_agent_task_spec_rejects_workspace_artifact_refs() -> None:
    with pytest.raises(ValidationError, match="not workspace paths or filenames"):
        AgentTaskSpec(
            target_agent_id="resume_agent",
            instruction="解析 main-agent 临时文件",
            artifact_refs=["workspace/resume.txt"],
        )


def test_agent_task_runtime_returns_partial_failed_when_one_child_fails(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_delegate")

    result = bundle.task_runtime.run_group(
        AgentTaskGroupRequest(
            source_context=_source_context(),
            max_concurrency=2,
            tasks=[
                AgentTaskSpec(target_agent_id="resume_agent", instruction="提取项目经历", max_tool_rounds=0),
                AgentTaskSpec(target_agent_id="missing_agent", instruction="这个 agent 不存在", max_tool_rounds=0),
            ],
        )
    )

    assert result.status == "partial_failed"
    assert [item.status for item in result.results].count("completed") == 1
    failed = [item for item in result.results if item.status == "failed"]
    assert len(failed) == 1
    assert failed[0].target_agent_id == "missing_agent"
    assert failed[0].error is not None
    assert "Unknown agent_id" in failed[0].error


def test_agent_task_runtime_pressure_keeps_persisted_status_and_event_isolation(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_delegate")

    requests = [
        AgentTaskGroupRequest(
            source_context=_source_context(),
            max_concurrency=2,
            tasks=[
                AgentTaskSpec(target_agent_id="resume_agent", instruction="压力测试 A: 解析简历", max_tool_rounds=0),
                AgentTaskSpec(target_agent_id="job_agent", instruction="压力测试 A: 分析岗位", max_tool_rounds=0),
            ],
        ),
        AgentTaskGroupRequest(
            source_context=_source_context(),
            max_concurrency=2,
            tasks=[
                AgentTaskSpec(target_agent_id="resume_agent", instruction="压力测试 B: 提取亮点", max_tool_rounds=0),
                AgentTaskSpec(target_agent_id="missing_agent", instruction="压力测试 B: 不存在 agent", max_tool_rounds=0),
            ],
        ),
        AgentTaskGroupRequest(
            source_context=_source_context(),
            max_concurrency=3,
            tasks=[
                AgentTaskSpec(target_agent_id="resume_agent", instruction="压力测试 C: 项目经历", max_tool_rounds=0),
                AgentTaskSpec(target_agent_id="job_agent", instruction="压力测试 C: 岗位要求", max_tool_rounds=0),
                AgentTaskSpec(target_agent_id="resume_agent", instruction="压力测试 C: 教育经历", max_tool_rounds=0),
            ],
        ),
    ]

    results = [bundle.task_runtime.run_group(request) for request in requests]

    assert [result.status for result in results] == ["completed", "partial_failed", "completed"]
    assert bundle.model_client.max_active >= 2

    reloaded_store = JsonlAgentTaskStore(data_dir=tmp_path / "sessions")
    for result, expected_count in zip(results, [2, 2, 3], strict=True):
        group = reloaded_store.get_group("sess_delegate", result.task_group_id)
        tasks = reloaded_store.list_group_tasks("sess_delegate", result.task_group_id)

        assert group is not None
        assert group.status == result.status
        assert len(tasks) == expected_count
        assert [task.task_id for task in tasks] == [item.task_id for item in result.results]
        assert all(task.child_run_id for task in tasks)
        for task in tasks:
            assert task.created_at is not None
            assert task.updated_at is not None
            assert task.updated_at >= task.created_at

    first_status = bundle.tool_registry.execute(
        ToolCall(
            name="agent_task_status",
            arguments={"task_group_id": results[0].task_group_id},
        ),
        _source_context(),
    )
    first_status_payload = json.loads(first_status.content)
    assert first_status.success is True
    assert first_status_payload["status"] == "completed"
    assert len(first_status_payload["tasks"]) == 2

    visible_event_types = [event.type for event in bundle.session_repository.list_events("sess_delegate")]
    orchestration_event_types = [
        event.type for event in bundle.session_repository.list_orchestration_events("sess_delegate")
    ]
    resume_event_types = [
        event.type for event in bundle.session_repository.list_agent_events("sess_delegate", "resume_agent")
    ]
    job_event_types = [
        event.type for event in bundle.session_repository.list_agent_events("sess_delegate", "job_agent")
    ]

    assert "agent_task_assigned" in visible_event_types
    assert "agent_result_summary" in visible_event_types
    assert "agent_task_assigned" in orchestration_event_types
    assert "agent_result_summary" in orchestration_event_types
    assert "run_started" not in visible_event_types
    assert "assistant_message" not in visible_event_types
    assert "run_started" in resume_event_types
    assert "assistant_message" in resume_event_types
    assert "run_started" in job_event_types
    assert "assistant_message" in job_event_types


def test_context_assembler_filters_tool_catalog_by_agent_capability(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    bundle.session_repository.create_session("sess_delegate")

    main_definitions = bundle.tool_registry.list_definitions_for_agent("agent_main")
    child_definitions = bundle.tool_registry.list_definitions_for_agent("resume_agent")

    assert any(item.name == "delegate_agents" for item in main_definitions)
    assert any(item.name == "agent_task_status" for item in main_definitions)
    assert not any(item.name == "delegate_agents" for item in child_definitions)
    assert not any(item.name == "agent_task_status" for item in child_definitions)
