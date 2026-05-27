"""Dry-run planner for deterministic workflow executor contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.domain.models import RunContext, ToolDefinition
from app.domain.reference_ids import is_reserved_reference_value
from app.runtime.workflow.contracts import (
    ActionContract,
    ActionContractRegistry,
    ToolStep,
    WorkflowContract,
    WorkflowContractRegistry,
    builtin_action_contract_registry,
    builtin_workflow_contract_registry,
)
from app.runtime.workflow.state import UnifiedWorkflowState

__all__ = [
    "PlannedToolStep",
    "WorkflowExecutorDryRun",
    "dry_run_action_contract",
    "dry_run_workflow_executor",
    "tool_names_from_definitions",
]


@dataclass(slots=True)
class PlannedToolStep:
    """Resolved dry-run view for one contract tool step."""

    index: int
    tool_name: str
    args_from_refs: dict[str, str] = field(default_factory=dict)
    resolved_args: dict[str, str] = field(default_factory=dict)
    args_from_previous_result: dict[str, str] = field(default_factory=dict)
    requires_model_payload: bool = False
    output_ref: str | None = None
    only_if_missing_output: str | None = None


@dataclass(slots=True)
class WorkflowExecutorDryRun:
    """Decision returned by deterministic executor dry-run."""

    executable: bool
    matched_contract_id: str | None = None
    confidence: str = "none"
    matched_contract_count: int = 0
    required_refs: list[str] = field(default_factory=list)
    missing_refs: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)
    planned_steps: list[PlannedToolStep] = field(default_factory=list)
    reason_not_executable: str | None = None


def dry_run_workflow_executor(
    *,
    state: UnifiedWorkflowState,
    context: RunContext,
    contract_registry: WorkflowContractRegistry | None = None,
    available_tool_names: Iterable[str] | None = None,
) -> WorkflowExecutorDryRun:
    """Return a deterministic executor decision without executing any tool."""

    registry = contract_registry or builtin_workflow_contract_registry()
    matching = registry.matching_contracts(state)
    if not matching:
        return WorkflowExecutorDryRun(
            executable=False,
            matched_contract_count=0,
            reason_not_executable="no_matching_contract",
        )
    if len(matching) > 1:
        return WorkflowExecutorDryRun(
            executable=False,
            matched_contract_count=len(matching),
            reason_not_executable="ambiguous_contracts",
        )

    contract = matching[0]
    base = _base_decision(contract=contract, state=state)
    base.matched_contract_count = 1
    if contract.allowed_agent_ids and context.agent_id not in contract.allowed_agent_ids:
        base.reason_not_executable = "agent_not_allowed"
        return base
    if base.missing_refs:
        base.reason_not_executable = "missing_required_refs"
        return base

    if available_tool_names is not None:
        available = {item for item in available_tool_names if item}
        missing_tools = [tool_name for tool_name in base.required_tools if tool_name not in available]
        if missing_tools:
            base.missing_tools = missing_tools
            base.reason_not_executable = "missing_required_capabilities"
            return base

    base.executable = True
    return base


def dry_run_action_contract(
    *,
    state: UnifiedWorkflowState,
    context: RunContext,
    contract_registry: ActionContractRegistry | None = None,
    available_tool_names: Iterable[str] | None = None,
) -> WorkflowExecutorDryRun:
    """Return a deterministic side-effect action decision without executing tools."""

    registry = contract_registry or builtin_action_contract_registry()
    matching = registry.matching_contracts(state)
    if not matching:
        return WorkflowExecutorDryRun(
            executable=False,
            matched_contract_count=0,
            reason_not_executable="no_matching_contract",
        )
    if len(matching) > 1:
        return WorkflowExecutorDryRun(
            executable=False,
            matched_contract_count=len(matching),
            reason_not_executable="ambiguous_contracts",
        )

    contract = matching[0]
    base = _base_decision(contract=contract, state=state)
    base.matched_contract_count = 1
    if contract.allowed_agent_ids and context.agent_id not in contract.allowed_agent_ids:
        base.reason_not_executable = "agent_not_allowed"
        return base
    if base.missing_refs:
        base.reason_not_executable = "missing_required_refs"
        return base

    if available_tool_names is not None:
        available = {item for item in available_tool_names if item}
        missing_tools = [tool_name for tool_name in base.required_tools if tool_name not in available]
        if missing_tools:
            base.missing_tools = missing_tools
            base.reason_not_executable = "missing_required_capabilities"
            return base

    base.executable = True
    return base


def tool_names_from_definitions(definitions: Iterable[ToolDefinition]) -> set[str]:
    """Extract available tool names from a tool definition iterable."""

    return {definition.name for definition in definitions}


def _base_decision(
    *,
    contract: WorkflowContract | ActionContract,
    state: UnifiedWorkflowState,
) -> WorkflowExecutorDryRun:
    required_refs = list(contract.required_refs)
    missing_refs = [ref_key for ref_key in required_refs if not _has_ref(state, ref_key)]
    return WorkflowExecutorDryRun(
        executable=False,
        matched_contract_id=contract.contract_id,
        confidence=contract.confidence,
        required_refs=required_refs,
        missing_refs=missing_refs,
        required_tools=_active_required_tools(contract=contract, state=state),
        planned_steps=_planned_steps(contract.steps, state),
    )


def _planned_steps(steps: tuple[ToolStep, ...], state: UnifiedWorkflowState) -> list[PlannedToolStep]:
    output: list[PlannedToolStep] = []
    for step in steps:
        if not _step_is_active(step, state):
            continue
        resolved_args: dict[str, str] = {}
        for arg_name, ref_key in step.args_from_refs.items():
            value = state.known_refs.get(ref_key)
            if _valid_ref_value(value):
                resolved_args[arg_name] = str(value).strip()
        output.append(
            PlannedToolStep(
                index=len(output) + 1,
                tool_name=step.tool_name,
                args_from_refs=dict(step.args_from_refs),
                resolved_args=resolved_args,
                args_from_previous_result=dict(step.args_from_previous_result),
                requires_model_payload=step.requires_model_payload,
                output_ref=step.output_ref,
                only_if_missing_output=step.only_if_missing_output,
            )
        )
    return output


def _active_required_tools(*, contract: WorkflowContract | ActionContract, state: UnifiedWorkflowState) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for step in contract.steps:
        if not _step_is_active(step, state):
            continue
        if step.tool_name in seen:
            continue
        output.append(step.tool_name)
        seen.add(step.tool_name)
    for tool_name in contract.required_capabilities:
        if tool_name in seen:
            continue
        output.append(tool_name)
        seen.add(tool_name)
    return output


def _step_is_active(step: ToolStep, state: UnifiedWorkflowState) -> bool:
    if step.only_if_missing_output is None:
        return True
    return step.only_if_missing_output in set(state.missing_outputs)


def _has_ref(state: UnifiedWorkflowState, ref_key: str) -> bool:
    return _valid_ref_value(state.known_refs.get(ref_key))


def _valid_ref_value(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return not is_reserved_reference_value(value.strip())
