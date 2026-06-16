"""Tests for the M62 static task graph and workflow routing foundation."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.domain.models import AgentRunInput, RunContext
from app.runtime.langgraph import (
    CAREER_INTAKE_TASK_GRAPH,
    MULTI_AGENT_CAREER_WORKFLOW_ID,
    MultiAgentCareerWorkflowRunner,
    MultiAgentTaskDefinition,
    MultiAgentTaskGraph,
    WorkflowRouter,
    canonical_task_execution_key,
)


def test_career_intake_task_graph_exposes_parallel_roots_and_dependent_fit_task() -> None:
    assert CAREER_INTAKE_TASK_GRAPH.ready_task_keys(
        completed_task_keys=set(),
        started_task_keys=set(),
    ) == ["resume_analysis", "jd_analysis"]
    assert CAREER_INTAKE_TASK_GRAPH.ready_task_keys(
        completed_task_keys={"resume_analysis"},
        started_task_keys=set(),
    ) == ["jd_analysis"]
    assert CAREER_INTAKE_TASK_GRAPH.ready_task_keys(
        completed_task_keys={"resume_analysis", "jd_analysis"},
        started_task_keys=set(),
    ) == ["job_fit_analysis"]


def test_multi_agent_task_graph_rejects_cycles() -> None:
    with pytest.raises(ValidationError, match="cycle"):
        MultiAgentTaskGraph(
            workflow_id="test.workflow",
            contract_version="test.v1",
            tasks=(
                MultiAgentTaskDefinition(
                    task_key="first",
                    target_agent_id="resume_agent",
                    required_inputs=("artifact_id",),
                    required_outputs=("result_id",),
                    depends_on=("second",),
                ),
                MultiAgentTaskDefinition(
                    task_key="second",
                    target_agent_id="job_agent",
                    required_inputs=("artifact_id",),
                    required_outputs=("result_id",),
                    depends_on=("first",),
                ),
            ),
        )


def test_task_execution_key_is_stable_and_input_sensitive() -> None:
    first = canonical_task_execution_key(
        workflow_instance_id="wf_multi",
        graph=CAREER_INTAKE_TASK_GRAPH,
        task_key="resume_analysis",
        input_refs={"resume_artifact_id": "artifact_resume"},
    )
    same = canonical_task_execution_key(
        workflow_instance_id="wf_multi",
        graph=CAREER_INTAKE_TASK_GRAPH,
        task_key="resume_analysis",
        input_refs={"resume_artifact_id": "artifact_resume"},
    )
    changed = canonical_task_execution_key(
        workflow_instance_id="wf_multi",
        graph=CAREER_INTAKE_TASK_GRAPH,
        task_key="resume_analysis",
        input_refs={"resume_artifact_id": "artifact_resume_v2"},
    )

    assert first == same
    assert first.startswith("task_exec_")
    assert first != changed


def test_workflow_router_selects_multi_agent_career_conservatively() -> None:
    router = WorkflowRouter(
        enabled=True,
        interactive_note_enabled=True,
        multi_agent_career_enabled=True,
    )

    assert (
        router.select_workflow(
            _run_input("请基于这份简历和目标岗位 JD 生成岗位匹配报告，并创建求职项目。")
        )
        == MULTI_AGENT_CAREER_WORKFLOW_ID
    )
    assert router.select_workflow(_run_input("只分析这份简历，生成简历画像。")) is None
    assert router.select_workflow(_run_input("根据简历和 JD 给建议，只读，不要保存。")) is None


def test_multi_agent_career_runner_builds_code_owned_initial_state() -> None:
    state = MultiAgentCareerWorkflowRunner().initial_state_for(
        _run_input("请分析简历和 JD。"),
        workflow_instance_id="wf_multi",
    )

    assert state["workflow_instance_id"] == "wf_multi"
    assert state["thread_id"] == "sess_multi:wf_multi"
    assert state["contract_id"] == CAREER_INTAKE_TASK_GRAPH.contract_version
    assert set(state["task_specs"]) == {"resume_analysis", "jd_analysis", "job_fit_analysis"}
    assert state["task_specs"]["job_fit_analysis"]["depends_on"] == [
        "resume_analysis",
        "jd_analysis",
    ]
    assert state["task_results"] == {}


def _run_input(message: str) -> AgentRunInput:
    return AgentRunInput(
        session_id="sess_multi",
        user_message=message,
        skill_names=[],
        max_tool_rounds=24,
        context=RunContext(
            session_id="sess_multi",
            run_id="run_multi",
            agent_id="agent_main",
            turn_id="turn_multi",
            entry_agent_id="agent_main",
            parent_run_id=None,
            trace_flags={},
        ),
    )
