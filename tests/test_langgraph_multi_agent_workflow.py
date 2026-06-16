"""Integration tests for the M62 multi-agent career workflow."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

from app.career.store import CareerProductStore
from app.core.time import app_now
from app.domain.models import AgentRunInput, RunContext, SessionArtifact, ToolExecutionResult
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.jsonl_tool_call_ledger import JsonlToolCallLedger
from app.infra.storage.jsonl_workflow_instance_store import JsonlWorkflowInstanceStore
from app.infra.storage.sqlite_graph_agent_task_store import SqliteGraphAgentTaskStore
from app.runtime.agent.tool_gateway import ToolGatewayResult
from app.runtime.event_recorder import EventRecorder
from app.runtime.langgraph.multi_agent_career import MultiAgentCareerWorkflowRunner
from app.runtime.langgraph.types import WorkflowResumePayload, WorkflowResumeRequest
from app.services.agent_invocation_service import AgentInvocationRequest, AgentInvocationResult
from app.services.graph_agent_task_executor import GraphAgentTaskExecutor


class _CareerInvocationService:
    def __init__(self, *, fail_first_jd: bool = False) -> None:
        self.fail_first_jd = fail_first_jd
        self.calls: dict[str, int] = {}
        self.max_active = 0
        self._active = 0
        self._lock = threading.Lock()

    def invoke(self, request: AgentInvocationRequest) -> AgentInvocationResult:
        task_key = _task_key(request)
        with self._lock:
            self.calls[task_key] = self.calls.get(task_key, 0) + 1
            call_number = self.calls[task_key]
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            time.sleep(0.04)
            if task_key == "jd_analysis" and self.fail_first_jd and call_number == 1:
                raise RuntimeError("injected jd failure")
            product_refs, output_refs = {
                "resume_analysis": (
                    ["resume_profile_alpha", "career_profile_default"],
                    ["artifact_resume_diagnosis"],
                ),
                "jd_analysis": (["jd_alpha"], []),
                "job_fit_analysis": (["fit_alpha"], ["artifact_fit_report"]),
            }[task_key]
            return AgentInvocationResult(
                task_id=request.task_id or "graph_task",
                source_agent_id="agent_main",
                target_agent_id=request.target_agent_id,
                child_run_id=request.child_run_id or "run_child",
                status="completed",
                summary=f"{task_key} completed",
                artifact_refs=list(request.artifact_refs),
                output_artifact_refs=output_refs,
                product_refs=product_refs,
                answer=f"{task_key} completed",
            )
        finally:
            with self._lock:
                self._active -= 1


class _ApplicationGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute_async(
        self,
        tool_call: Any,
        context: RunContext,
        *,
        pending_runtime_plan: dict[str, Any] | None = None,
    ) -> ToolGatewayResult:
        _ = (context, pending_runtime_plan)
        self.calls.append(dict(tool_call.arguments))
        application_id = tool_call.arguments["application_id"]
        return ToolGatewayResult(
            tool_call=tool_call,
            result=ToolExecutionResult(
                tool_name=tool_call.name,
                success=True,
                content=json.dumps(
                    {
                        "record_type": "career_application",
                        "record_id": application_id,
                    }
                ),
            ),
        )


def test_multi_agent_workflow_runs_parallel_join_and_confirms_before_write(tmp_path: Path) -> None:
    repository = _session_repository(tmp_path)
    invocation = _CareerInvocationService()
    gateway = _ApplicationGateway()
    runner = _runner(
        tmp_path,
        repository=repository,
        invocation=invocation,
        gateway=gateway,
        checkpoint_backend="memory",
    )

    started = asyncio.run(runner.run_stream(_run_input()))

    assert started.status == "interrupted"
    assert started.interrupt_payload is not None
    assert started.interrupt_payload["type"] == "career_project_confirmation"
    assert invocation.max_active >= 2
    assert invocation.calls == {
        "resume_analysis": 1,
        "jd_analysis": 1,
        "job_fit_analysis": 1,
    }
    artifacts = [
        repository.get_session_artifact("sess_multi", artifact_id)
        for artifact_id in ("artifact_resume", "artifact_jd")
    ]
    assert all(artifact is not None for artifact in artifacts)
    assert {artifact.status for artifact in artifacts if artifact is not None} == {"ready"}
    assert gateway.calls == []

    completed = asyncio.run(
        runner.resume_stream(
            _resume_request(started.workflow_instance_id or "", {"action": "approve"})
        )
    )

    assert completed.status == "completed"
    assert "application_id:" in (completed.output.answer if completed.output else "")
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["job_fit_report_id"] == "fit_alpha"


def test_multi_agent_workflow_restart_retries_only_failed_task(tmp_path: Path) -> None:
    repository = _session_repository(tmp_path)
    invocation = _CareerInvocationService(fail_first_jd=True)
    gateway = _ApplicationGateway()
    runner = _runner(
        tmp_path,
        repository=repository,
        invocation=invocation,
        gateway=gateway,
        checkpoint_backend="sqlite",
    )

    failed = asyncio.run(runner.run_stream(_run_input()))

    assert failed.status == "interrupted"
    assert failed.interrupt_payload is not None
    assert failed.interrupt_payload["type"] == "workflow_task_retry"
    assert [item["task_key"] for item in failed.interrupt_payload["failed_tasks"]] == [
        "jd_analysis"
    ]
    assert invocation.calls["resume_analysis"] == 1
    assert invocation.calls["jd_analysis"] == 1
    assert "job_fit_analysis" not in invocation.calls

    restarted = _runner(
        tmp_path,
        repository=repository,
        invocation=invocation,
        gateway=gateway,
        checkpoint_backend="sqlite",
    )
    retried = asyncio.run(
        restarted.resume_stream(
            _resume_request(
                failed.workflow_instance_id or "",
                {"action": "retry_failed"},
                expected_version=1,
            )
        )
    )

    assert retried.status == "interrupted"
    assert retried.interrupt_payload is not None
    assert retried.interrupt_payload["type"] == "career_project_confirmation"
    assert invocation.calls == {
        "resume_analysis": 1,
        "jd_analysis": 2,
        "job_fit_analysis": 1,
    }

    cancelled = asyncio.run(
        restarted.resume_stream(
            _resume_request(
                retried.workflow_instance_id or "",
                {"action": "cancel"},
                expected_version=2,
            )
        )
    )

    assert cancelled.status == "completed"
    assert gateway.calls == []


def _runner(
    tmp_path: Path,
    *,
    repository: JsonlSessionRepository,
    invocation: _CareerInvocationService,
    gateway: _ApplicationGateway,
    checkpoint_backend: str,
) -> MultiAgentCareerWorkflowRunner:
    return MultiAgentCareerWorkflowRunner(
        task_executor=GraphAgentTaskExecutor(
            invocation_service=invocation,
            task_store=SqliteGraphAgentTaskStore(tmp_path / "graph_tasks.sqlite"),
            lease_ttl_seconds=30,
        ),
        tool_gateway=gateway,  # type: ignore[arg-type]
        event_recorder=EventRecorder(repository),
        session_repository=repository,
        career_store=CareerProductStore(root_dir=tmp_path / "career"),
        workflow_store=JsonlWorkflowInstanceStore(data_dir=tmp_path),
        checkpoint_backend=checkpoint_backend,
        checkpoint_path=tmp_path / "langgraph.sqlite",
        node_timeout_seconds=30,
    )


def _session_repository(tmp_path: Path) -> JsonlSessionRepository:
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session("sess_multi")
    _add_artifact(
        repository,
        artifact_id="artifact_resume",
        title="张明后端工程师简历.md",
        content="# 简历\n\n工作经历、项目经历、技能栈。",
    )
    _add_artifact(
        repository,
        artifact_id="artifact_jd",
        title="后端工程师 JD.md",
        content="# 岗位职责\n\n任职要求：Python、FastAPI、PostgreSQL。",
    )
    repository.set_active_artifact_ids(
        "sess_multi",
        ["artifact_resume", "artifact_jd"],
    )
    return repository


def _add_artifact(
    repository: JsonlSessionRepository,
    *,
    artifact_id: str,
    title: str,
    content: str,
) -> None:
    root = repository.get_session_root_path("sess_multi")
    relative = Path("artifacts") / artifact_id / "content.md"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    now = app_now()
    repository.add_or_update_session_artifact(
        SessionArtifact(
            artifact_id=artifact_id,
            session_id="sess_multi",
            kind="uploaded_file",
            title=title,
            media_type="text/markdown",
            size_bytes=len(content.encode("utf-8")),
            status="uploaded",
            visibility="session_shared",
            storage_relpath=str(relative),
            text_relpath=str(relative),
            created_at=now,
            updated_at=now,
        )
    )


def _run_input() -> AgentRunInput:
    return AgentRunInput(
        session_id="sess_multi",
        user_message="请基于这份简历和目标岗位 JD 生成岗位匹配报告，并创建求职项目。",
        skill_names=[],
        max_tool_rounds=24,
        context=_context("run_multi"),
    )


def _resume_request(
    workflow_instance_id: str,
    payload: dict[str, Any],
    *,
    expected_version: int | None = None,
) -> WorkflowResumeRequest:
    return WorkflowResumeRequest(
        session_id="sess_multi",
        workflow_instance_id=workflow_instance_id,
        payload=WorkflowResumePayload(payload=payload),
        context=_context(f"run_resume_{workflow_instance_id}"),
        expected_version=expected_version,
    )


def _context(run_id: str) -> RunContext:
    return RunContext(
        session_id="sess_multi",
        run_id=run_id,
        agent_id="agent_main",
        turn_id=f"turn_{run_id}",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={},
    )


def _task_key(request: AgentInvocationRequest) -> str:
    if request.target_agent_id == "resume_agent":
        return "resume_analysis"
    if "只做 JD 分析" in request.instruction:
        return "jd_analysis"
    return "job_fit_analysis"
