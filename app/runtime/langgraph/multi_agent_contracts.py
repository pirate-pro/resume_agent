"""Static task-graph contracts for LangGraph multi-agent workflows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from app.core.errors import ValidationError
from app.runtime.langgraph.types import MULTI_AGENT_CAREER_WORKFLOW_ID

__all__ = [
    "CAREER_INTAKE_TASK_GRAPH",
    "MultiAgentTaskDefinition",
    "MultiAgentTaskGraph",
    "canonical_task_execution_key",
]


@dataclass(frozen=True, slots=True)
class MultiAgentTaskDefinition:
    """One code-owned task in a static multi-agent graph."""

    task_key: str
    target_agent_id: str
    required_inputs: tuple[str, ...]
    required_outputs: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    max_tool_rounds: int = 24

    def __post_init__(self) -> None:
        _require_identifier("task_key", self.task_key)
        _require_identifier("target_agent_id", self.target_agent_id)
        _validate_identifier_tuple("required_inputs", self.required_inputs)
        _validate_identifier_tuple("required_outputs", self.required_outputs)
        _validate_identifier_tuple("depends_on", self.depends_on)
        if self.task_key in self.depends_on:
            raise ValidationError(f"task cannot depend on itself: {self.task_key}")
        if self.max_tool_rounds <= 0 or self.max_tool_rounds > 40:
            raise ValidationError("max_tool_rounds must be in range 1..40.")


@dataclass(frozen=True, slots=True)
class MultiAgentTaskGraph:
    """Validated static DAG used by a LangGraph workflow."""

    workflow_id: str
    contract_version: str
    tasks: tuple[MultiAgentTaskDefinition, ...]

    def __post_init__(self) -> None:
        _require_non_empty("workflow_id", self.workflow_id)
        _require_non_empty("contract_version", self.contract_version)
        if not self.tasks:
            raise ValidationError("multi-agent task graph must contain at least one task.")
        task_keys = [task.task_key for task in self.tasks]
        if len(task_keys) != len(set(task_keys)):
            raise ValidationError("multi-agent task graph contains duplicate task keys.")
        known = set(task_keys)
        for task in self.tasks:
            missing = sorted(set(task.depends_on) - known)
            if missing:
                raise ValidationError(
                    f"task '{task.task_key}' references unknown dependencies: {', '.join(missing)}"
                )
        _validate_acyclic(self.tasks)

    def task(self, task_key: str) -> MultiAgentTaskDefinition:
        normalized = _require_identifier("task_key", task_key)
        for task in self.tasks:
            if task.task_key == normalized:
                return task
        raise ValidationError(f"unknown multi-agent task key: {normalized}")

    def ready_task_keys(
        self,
        *,
        completed_task_keys: set[str],
        started_task_keys: set[str],
    ) -> list[str]:
        unknown = (completed_task_keys | started_task_keys) - {task.task_key for task in self.tasks}
        if unknown:
            raise ValidationError(f"unknown task keys in graph state: {', '.join(sorted(unknown))}")
        return [
            task.task_key
            for task in self.tasks
            if task.task_key not in completed_task_keys
            and task.task_key not in started_task_keys
            and set(task.depends_on) <= completed_task_keys
        ]


def canonical_task_execution_key(
    *,
    workflow_instance_id: str,
    graph: MultiAgentTaskGraph,
    task_key: str,
    input_refs: Mapping[str, str],
) -> str:
    """Return a stable key for one task and its canonical inputs."""

    workflow_instance_id = _require_non_empty("workflow_instance_id", workflow_instance_id)
    task = graph.task(task_key)
    canonical_inputs: dict[str, str] = {}
    for input_name in task.required_inputs:
        value = input_refs.get(input_name)
        canonical_inputs[input_name] = _require_non_empty(input_name, value)
    payload = {
        "workflow_instance_id": workflow_instance_id,
        "workflow_id": graph.workflow_id,
        "contract_version": graph.contract_version,
        "task_key": task.task_key,
        "target_agent_id": task.target_agent_id,
        "inputs": canonical_inputs,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"task_exec_{digest}"


def _validate_acyclic(tasks: tuple[MultiAgentTaskDefinition, ...]) -> None:
    dependencies = {task.task_key: set(task.depends_on) for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def _visit(task_key: str) -> None:
        if task_key in visited:
            return
        if task_key in visiting:
            raise ValidationError(f"multi-agent task graph contains a cycle at: {task_key}")
        visiting.add(task_key)
        for dependency in dependencies[task_key]:
            _visit(dependency)
        visiting.remove(task_key)
        visited.add(task_key)

    for task_key in dependencies:
        _visit(task_key)


def _validate_identifier_tuple(name: str, values: tuple[str, ...]) -> None:
    if not isinstance(values, tuple):
        raise ValidationError(f"{name} must be a tuple.")
    normalized = [_require_identifier(name, value) for value in values]
    if len(normalized) != len(set(normalized)):
        raise ValidationError(f"{name} cannot contain duplicates.")


def _require_identifier(name: str, value: str) -> str:
    normalized = _require_non_empty(name, value)
    if not normalized.replace("_", "").replace(".", "").isalnum():
        raise ValidationError(f"{name} contains unsupported characters: {normalized}")
    return normalized


def _require_non_empty(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


CAREER_INTAKE_TASK_GRAPH = MultiAgentTaskGraph(
    workflow_id=MULTI_AGENT_CAREER_WORKFLOW_ID,
    contract_version="career.intake.analysis.v1",
    tasks=(
        MultiAgentTaskDefinition(
            task_key="resume_analysis",
            target_agent_id="resume_agent",
            required_inputs=("resume_artifact_id",),
            required_outputs=("resume_profile_id", "diagnosis_artifact_id"),
        ),
        MultiAgentTaskDefinition(
            task_key="jd_analysis",
            target_agent_id="job_agent",
            required_inputs=("jd_artifact_id",),
            required_outputs=("jd_analysis_id",),
        ),
        MultiAgentTaskDefinition(
            task_key="job_fit_analysis",
            target_agent_id="job_agent",
            required_inputs=("resume_profile_id", "career_profile_id", "jd_analysis_id"),
            required_outputs=("job_fit_report_id", "report_artifact_id"),
            depends_on=("resume_analysis", "jd_analysis"),
        ),
    ),
)
