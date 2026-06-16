"""Tests for re-entrant execution of LangGraph-owned child tasks."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.domain.graph_agent_tasks import GRAPH_TASK_STATUS_COMPLETED, GRAPH_TASK_STATUS_FAILED
from app.domain.models import RunContext
from app.infra.storage.sqlite_graph_agent_task_store import SqliteGraphAgentTaskStore
from app.runtime.langgraph.multi_agent_contracts import CAREER_INTAKE_TASK_GRAPH
from app.services.agent_invocation_service import AgentInvocationRequest, AgentInvocationResult
from app.services.graph_agent_task_executor import GraphAgentTaskExecutor, GraphAgentTaskRequest


class _SequenceInvocationService:
    def __init__(self, outcomes: list[AgentInvocationResult | Exception]) -> None:
        self._outcomes = list(outcomes)
        self.requests: list[AgentInvocationRequest] = []

    def invoke(self, request: AgentInvocationRequest) -> AgentInvocationResult:
        self.requests.append(request)
        if not self._outcomes:
            raise AssertionError("unexpected child-agent invocation")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _TaskContextBuilder:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error

    def build(self, **_: Any) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        return {
            "phase": "jd_fit",
            "known_refs": {
                "existing_ref": "existing_value",
                "jd_source_artifact_id": "artifact_jd",
                "jd_analysis_id": "jd_stale",
            },
            "provided_records": {
                "jd_analysis": {"record_id": "jd_stale"},
                "job_fit_report": {"record_id": "fit_stale"},
            },
            "required_outputs": [
                "jd_analysis",
                "job_fit_report",
                "career_application",
            ],
            "allowed_initial_tools": ["delegate_agents"],
        }


def test_graph_task_executor_reuses_completed_attempt(tmp_path: Path) -> None:
    invocation = _SequenceInvocationService(
        [
            _result(
                product_refs=["resume_profile_alpha"],
                output_artifact_refs=["artifact_resume_diagnosis"],
            )
        ]
    )
    executor = _executor(tmp_path, invocation)
    request = _request("resume_analysis")

    completed = asyncio.run(executor.execute(request))
    reused = asyncio.run(executor.execute(request))

    assert completed.status == GRAPH_TASK_STATUS_COMPLETED
    assert completed.product_refs == ("resume_profile_alpha",)
    assert reused.attempt_id == completed.attempt_id
    assert len(invocation.requests) == 1


def test_graph_task_executor_retries_only_after_explicit_request(tmp_path: Path) -> None:
    invocation = _SequenceInvocationService(
        [
            RuntimeError("temporary provider failure"),
            _result(
                product_refs=["jd_alpha"],
                output_artifact_refs=[],
                target_agent_id="job_agent",
            ),
        ]
    )
    executor = _executor(tmp_path, invocation)
    request = _request("jd_analysis")

    failed = asyncio.run(executor.execute(request))
    unchanged = asyncio.run(executor.execute(request))
    retried = asyncio.run(executor.execute(request, retry_failed=True))

    assert failed.status == GRAPH_TASK_STATUS_FAILED
    assert unchanged.attempt_id == failed.attempt_id
    assert retried.status == GRAPH_TASK_STATUS_COMPLETED
    assert retried.attempt == 2
    assert len(invocation.requests) == 2


def test_graph_task_executor_rejects_missing_required_child_outputs(tmp_path: Path) -> None:
    invocation = _SequenceInvocationService(
        [
            _result(
                product_refs=[],
                output_artifact_refs=[],
                target_agent_id="job_agent",
            )
        ]
    )
    executor = _executor(tmp_path, invocation)

    failed = asyncio.run(executor.execute(_request("job_fit_analysis")))

    assert failed.status == GRAPH_TASK_STATUS_FAILED
    assert failed.error is not None
    assert "job_fit_report" in failed.error
    assert "report_artifact" in failed.error


def test_graph_task_executor_requires_jd_analysis_product_ref(tmp_path: Path) -> None:
    invocation = _SequenceInvocationService(
        [
            _result(
                product_refs=[],
                output_artifact_refs=["artifact_jd_report"],
                target_agent_id="job_agent",
            )
        ]
    )
    executor = _executor(tmp_path, invocation)

    failed = asyncio.run(executor.execute(_request("jd_analysis")))

    assert failed.status == GRAPH_TASK_STATUS_FAILED
    assert failed.error is not None
    assert "jd_analysis_id" in failed.error


def test_graph_task_executor_persists_only_contract_product_refs(tmp_path: Path) -> None:
    invocation = _SequenceInvocationService(
        [
            _result(
                product_refs=[
                    "career_profile_default",
                    "resume_profile_old",
                    "resume_profile_current",
                    "jd_alpha",
                    "fit_alpha",
                ],
                output_artifact_refs=["artifact_fit_report"],
                target_agent_id="job_agent",
            )
        ]
    )
    executor = _executor(tmp_path, invocation)

    completed = asyncio.run(executor.execute(_request("job_fit_analysis")))

    assert completed.status == GRAPH_TASK_STATUS_COMPLETED
    assert completed.product_refs == ("fit_alpha",)


def test_graph_task_executor_applies_narrow_graph_contract_to_child_context(
    tmp_path: Path,
) -> None:
    invocation = _SequenceInvocationService(
        [
            _result(
                product_refs=["jd_alpha"],
                output_artifact_refs=[],
                target_agent_id="job_agent",
            )
        ]
    )
    executor = _executor(
        tmp_path,
        invocation,
        task_context_builder=_TaskContextBuilder(),
    )

    completed = asyncio.run(executor.execute(_request("jd_analysis")))

    assert completed.status == GRAPH_TASK_STATUS_COMPLETED
    task_context = invocation.requests[0].task_context
    assert task_context["phase"] == "jd_analysis"
    assert task_context["required_outputs"] == ["jd_analysis_id"]
    assert task_context["allowed_initial_tools"] == [
        "session_read_artifact",
        "career_jd_analysis_save",
    ]
    assert task_context["known_refs"] == {
        "jd_source_artifact_id": "artifact_jd",
        "jd_artifact_id": "artifact_jd",
    }
    assert task_context["provided_records"] == {}


def test_graph_task_executor_keeps_graph_contract_when_context_build_fails(
    tmp_path: Path,
) -> None:
    invocation = _SequenceInvocationService(
        [
            _result(
                product_refs=["jd_alpha"],
                output_artifact_refs=[],
                target_agent_id="job_agent",
            )
        ]
    )
    executor = _executor(
        tmp_path,
        invocation,
        task_context_builder=_TaskContextBuilder(error=RuntimeError("context unavailable")),
    )

    completed = asyncio.run(executor.execute(_request("jd_analysis")))

    assert completed.status == GRAPH_TASK_STATUS_COMPLETED
    task_context = invocation.requests[0].task_context
    assert task_context["context_build_error"] == "context unavailable"
    assert task_context["phase"] == "jd_analysis"
    assert task_context["required_outputs"] == ["jd_analysis_id"]
    assert task_context["known_refs"] == {"jd_artifact_id": "artifact_jd"}


def _executor(
    tmp_path: Path,
    invocation: _SequenceInvocationService,
    *,
    task_context_builder: Any = None,
) -> GraphAgentTaskExecutor:
    return GraphAgentTaskExecutor(
        invocation_service=invocation,
        task_store=SqliteGraphAgentTaskStore(tmp_path / "graph_tasks.sqlite"),
        task_context_builder=task_context_builder,
        lease_ttl_seconds=30,
    )


def _request(task_key: str) -> GraphAgentTaskRequest:
    definition = CAREER_INTAKE_TASK_GRAPH.task(task_key)
    input_refs: dict[str, str]
    artifact_refs: tuple[str, ...]
    if task_key == "resume_analysis":
        input_refs = {"resume_artifact_id": "artifact_resume"}
        artifact_refs = ("artifact_resume",)
        instruction = "保存简历画像 ResumeProfile，并生成诊断 artifact。"
    elif task_key == "jd_analysis":
        input_refs = {"jd_artifact_id": "artifact_jd"}
        artifact_refs = ("artifact_jd",)
        instruction = "分析 JD 并保存 JDAnalysis。"
    else:
        input_refs = {
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "jd_analysis_id": "jd_alpha",
        }
        artifact_refs = ("artifact_jd",)
        instruction = "生成岗位匹配报告 JobFitReport 和 report artifact。"
    return GraphAgentTaskRequest(
        source_context=RunContext(
            session_id="sess_multi",
            run_id="run_multi",
            agent_id="agent_main",
            turn_id="turn_multi",
            entry_agent_id="agent_main",
            parent_run_id=None,
            trace_flags={},
        ),
        workflow_instance_id="wf_multi",
        graph=CAREER_INTAKE_TASK_GRAPH,
        definition=definition,
        instruction=instruction,
        input_refs=input_refs,
        artifact_refs=artifact_refs,
    )


def _result(
    *,
    product_refs: list[str],
    output_artifact_refs: list[str],
    target_agent_id: str = "resume_agent",
    **_: Any,
) -> AgentInvocationResult:
    return AgentInvocationResult(
        task_id="graph_task_fake",
        source_agent_id="agent_main",
        target_agent_id=target_agent_id,
        child_run_id="run_child",
        status="completed",
        summary="completed",
        artifact_refs=["artifact_resume"],
        output_artifact_refs=output_artifact_refs,
        product_refs=product_refs,
        answer="completed",
    )
