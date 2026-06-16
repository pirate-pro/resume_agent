"""Re-entrant execution adapter for LangGraph-owned child-agent tasks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.agent_tasks import AgentTaskSpec
from app.domain.graph_agent_task_protocols import GraphAgentTaskStore
from app.domain.graph_agent_tasks import (
    GRAPH_TASK_STATUS_COMPLETED,
    GRAPH_TASK_STATUS_FAILED,
    GraphAgentTaskAttemptRecord,
    GraphAgentTaskAttemptSpec,
)
from app.domain.models import RunContext
from app.runtime.langgraph.multi_agent_contracts import (
    MultiAgentTaskDefinition,
    MultiAgentTaskGraph,
    canonical_task_execution_key,
)
from app.services.agent_invocation_service import AgentInvocationRequest, AgentInvocationResult
from app.services.agent_task_runtime import child_completion_error
from app.services.task_context_builder import TaskContextBuilder

__all__ = ["GraphAgentTaskExecutor", "GraphAgentTaskRequest"]


class _AgentInvocationService(Protocol):
    def invoke(self, request: AgentInvocationRequest) -> AgentInvocationResult: ...


class _GraphAgentTaskOutputValidator(Protocol):
    def validate(
        self,
        request: GraphAgentTaskRequest,
        result: AgentInvocationResult,
    ) -> str | None: ...


@dataclass(frozen=True, slots=True)
class GraphAgentTaskRequest:
    """Code-owned inputs for one task in a static graph."""

    source_context: RunContext
    workflow_instance_id: str
    graph: MultiAgentTaskGraph
    definition: MultiAgentTaskDefinition
    instruction: str
    input_refs: dict[str, str]
    constraints: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    skill_names: tuple[str, ...] = ("base", "tools", "file-reader")
    child_run_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_context, RunContext):
            raise ValidationError("source_context must be RunContext.")
        if self.graph.task(self.definition.task_key) != self.definition:
            raise ValidationError("task definition does not belong to the supplied graph.")
        if not isinstance(self.instruction, str) or not self.instruction.strip():
            raise ValidationError("instruction must be non-empty.")
        if not isinstance(self.input_refs, dict):
            raise ValidationError("input_refs must be a dictionary.")
        if self.child_run_id is not None and not self.child_run_id.strip():
            raise ValidationError("child_run_id must be non-empty when provided.")


class GraphAgentTaskExecutor:
    """Execute one durable child task without recreating successful attempts."""

    def __init__(
        self,
        *,
        invocation_service: _AgentInvocationService,
        task_store: GraphAgentTaskStore,
        task_context_builder: TaskContextBuilder | None = None,
        output_validator: _GraphAgentTaskOutputValidator | None = None,
        lease_ttl_seconds: float = 900.0,
    ) -> None:
        if lease_ttl_seconds <= 0:
            raise ValidationError("lease_ttl_seconds must be positive.")
        self._invocation_service = invocation_service
        self._task_store = task_store
        self._task_context_builder = task_context_builder
        self._output_validator = output_validator
        self._lease_ttl_seconds = lease_ttl_seconds

    def ensure_attempt(
        self,
        request: GraphAgentTaskRequest,
        *,
        retry_failed: bool = False,
    ) -> GraphAgentTaskAttemptRecord:
        self._task_store.reconcile_stale_running()
        execution_key = canonical_task_execution_key(
            workflow_instance_id=request.workflow_instance_id,
            graph=request.graph,
            task_key=request.definition.task_key,
            input_refs=request.input_refs,
        )
        return self._task_store.ensure_attempt(
            GraphAgentTaskAttemptSpec(
                session_id=request.source_context.session_id,
                workflow_instance_id=request.workflow_instance_id,
                execution_key=execution_key,
                task_key=request.definition.task_key,
                target_agent_id=request.definition.target_agent_id,
                instruction=request.instruction.strip(),
                constraints=request.constraints,
                artifact_refs=request.artifact_refs,
                skill_names=request.skill_names,
                max_tool_rounds=request.definition.max_tool_rounds,
            ),
            retry_failed=retry_failed,
        )

    async def execute(
        self,
        request: GraphAgentTaskRequest,
        *,
        retry_failed: bool = False,
    ) -> GraphAgentTaskAttemptRecord:
        attempt = self.ensure_attempt(request, retry_failed=retry_failed)
        if attempt.status in {GRAPH_TASK_STATUS_COMPLETED, GRAPH_TASK_STATUS_FAILED}:
            return attempt
        owner_id = f"{request.source_context.run_id}:{uuid4().hex}"
        child_run_id = request.child_run_id or f"run_{uuid4().hex[:12]}"
        claimed = self._task_store.claim_attempt(
            attempt.attempt_id,
            owner_id=owner_id,
            child_run_id=child_run_id,
            ttl_seconds=self._lease_ttl_seconds,
        )
        task_context = self._build_task_context(request, task_id=claimed.attempt_id)
        try:
            result = await asyncio.to_thread(
                self._invocation_service.invoke,
                AgentInvocationRequest(
                    source_context=request.source_context,
                    target_agent_id=claimed.target_agent_id,
                    instruction=claimed.instruction,
                    constraints=list(claimed.constraints),
                    artifact_refs=list(claimed.artifact_refs),
                    skill_names=list(claimed.skill_names),
                    max_tool_rounds=claimed.max_tool_rounds,
                    task_id=claimed.attempt_id,
                    child_run_id=child_run_id,
                    task_context=task_context,
                ),
            )
            completion_error = (
                child_completion_error(
                    spec=AgentTaskSpec(
                        target_agent_id=claimed.target_agent_id,
                        instruction=claimed.instruction,
                        constraints=list(claimed.constraints),
                        artifact_refs=list(claimed.artifact_refs),
                        skill_names=list(claimed.skill_names),
                        max_tool_rounds=claimed.max_tool_rounds,
                    ),
                    result=result,
                )
                if request.definition.task_key != "jd_analysis"
                else None
            )
            if completion_error is not None:
                return self._task_store.mark_failed(
                    claimed.attempt_id,
                    owner_id=owner_id,
                    error=completion_error,
                )
            required_output_error = _required_output_error(request.definition, result)
            if required_output_error is not None:
                return self._task_store.mark_failed(
                    claimed.attempt_id,
                    owner_id=owner_id,
                    error=required_output_error,
                )
            if self._output_validator is not None:
                validation_error = self._output_validator.validate(request, result)
                if validation_error is not None:
                    return self._task_store.mark_failed(
                        claimed.attempt_id,
                        owner_id=owner_id,
                        error=validation_error,
                    )
            return self._task_store.mark_completed(
                claimed.attempt_id,
                owner_id=owner_id,
                summary=result.summary,
                output_artifact_refs=result.output_artifact_refs,
                product_refs=_contract_product_refs(request.definition, result.product_refs),
            )
        except Exception as exc:  # noqa: BLE001
            error = str(exc).strip() or exc.__class__.__name__
            return self._task_store.mark_failed(
                claimed.attempt_id,
                owner_id=owner_id,
                error=error,
            )

    def _build_task_context(
        self,
        request: GraphAgentTaskRequest,
        *,
        task_id: str,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {}
        if self._task_context_builder is not None:
            try:
                context = self._task_context_builder.build(
                    source_context=request.source_context,
                    target_agent_id=request.definition.target_agent_id,
                    task_id=task_id,
                    instruction=request.instruction,
                    artifact_refs=list(request.artifact_refs),
                )
            except Exception as exc:  # noqa: BLE001
                context = {
                    "schema_version": 1,
                    "task_id": task_id,
                    "target_agent_id": request.definition.target_agent_id,
                    "context_build_error": str(exc).strip() or exc.__class__.__name__,
                }
        context.update(_graph_task_context_overrides(request))
        context["known_refs"] = _graph_task_known_refs(request, context)
        provided_records = context.get("provided_records")
        if isinstance(provided_records, dict):
            context["provided_records"] = _graph_task_provided_records(
                request,
                provided_records,
            )
        return context


def _graph_task_context_overrides(request: GraphAgentTaskRequest) -> dict[str, Any]:
    allowed_tools = {
        "resume_analysis": [
            "session_read_artifact",
            "session_create_text_artifact",
            "career_resume_profile_save",
        ],
        "jd_analysis": [
            "session_read_artifact",
            "career_jd_analysis_save",
        ],
        "job_fit_analysis": [
            "career_resume_profile_get",
            "career_profile_get",
            "career_jd_analysis_get",
            "session_create_text_artifact",
            "career_job_fit_report_save",
        ],
    }
    return {
        "phase": request.definition.task_key,
        "graph_contract_id": request.graph.contract_version,
        "graph_task_key": request.definition.task_key,
        "missing_inputs": [],
        "provided_inputs_complete": True,
        "required_outputs": list(request.definition.required_outputs),
        "allowed_initial_tools": allowed_tools[request.definition.task_key],
    }


def _graph_task_known_refs(
    request: GraphAgentTaskRequest,
    context: dict[str, Any],
) -> dict[str, str]:
    raw_refs = context.get("known_refs")
    source_aliases = {
        key: value
        for key, value in (raw_refs.items() if isinstance(raw_refs, dict) else [])
        if key in {"resume_source_artifact_id", "jd_source_artifact_id", "source_artifact_id"}
        and isinstance(value, str)
        and value.strip()
    }
    source_aliases.update(request.input_refs)
    return source_aliases


def _graph_task_provided_records(
    request: GraphAgentTaskRequest,
    provided_records: dict[str, Any],
) -> dict[str, Any]:
    allowed = {
        "resume_analysis": set(),
        "jd_analysis": set(),
        "job_fit_analysis": {"resume_profile", "career_profile", "jd_analysis"},
    }[request.definition.task_key]
    return {
        key: value
        for key, value in provided_records.items()
        if key in allowed
    }


def _required_output_error(
    definition: MultiAgentTaskDefinition,
    result: AgentInvocationResult,
) -> str | None:
    checks = {
        "resume_profile_id": any(ref.startswith("resume_profile_") for ref in result.product_refs),
        "diagnosis_artifact_id": bool(result.output_artifact_refs),
        "jd_analysis_id": any(ref.startswith("jd_") for ref in result.product_refs),
        "job_fit_report_id": any(ref.startswith("fit_") for ref in result.product_refs),
        "report_artifact_id": bool(result.output_artifact_refs),
    }
    missing = [
        output_name
        for output_name in definition.required_outputs
        if checks.get(output_name) is not True
    ]
    if not missing:
        return None
    return (
        f"{definition.task_key} 子任务未满足输出合同："
        f"缺少 {', '.join(missing)}。"
    )


def _contract_product_refs(
    definition: MultiAgentTaskDefinition,
    product_refs: list[str],
) -> list[str]:
    prefixes_by_output = {
        "resume_profile_id": "resume_profile_",
        "jd_analysis_id": "jd_",
        "job_fit_report_id": "fit_",
    }
    prefixes = [
        prefix
        for output_name, prefix in prefixes_by_output.items()
        if output_name in definition.required_outputs
    ]
    if not prefixes:
        return list(dict.fromkeys(product_refs))
    return [
        ref
        for ref in dict.fromkeys(product_refs)
        if any(ref.startswith(prefix) for prefix in prefixes)
    ]
