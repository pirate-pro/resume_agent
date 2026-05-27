"""Declarative contracts for deterministic workflow execution.

Contracts describe closed-world workflow steps that may eventually be executed
by code. They do not execute tools by themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from typing import Any

from app.core.errors import ValidationError

if TYPE_CHECKING:
    from app.runtime.workflow.state import UnifiedWorkflowState

__all__ = [
    "ActionContract",
    "ActionContractRegistry",
    "ToolStep",
    "WorkflowContract",
    "WorkflowContractRegistry",
    "builtin_action_contract_registry",
    "builtin_workflow_contract_registry",
]


@dataclass(slots=True)
class ToolStep:
    """One planned tool step inside a workflow contract."""

    tool_name: str
    args_from_refs: dict[str, str] = field(default_factory=dict)
    args_from_previous_result: dict[str, str] = field(default_factory=dict)
    requires_model_payload: bool = False
    output_ref: str | None = None
    only_if_missing_output: str | None = None

    def __post_init__(self) -> None:
        self.tool_name = _normalize_non_empty("tool step tool_name", self.tool_name)
        self.args_from_refs = _normalize_string_map("tool step args_from_refs", self.args_from_refs)
        self.args_from_previous_result = _normalize_string_map(
            "tool step args_from_previous_result",
            self.args_from_previous_result,
        )
        if not isinstance(self.requires_model_payload, bool):
            raise ValidationError("tool step requires_model_payload must be bool.")
        if self.output_ref is not None:
            self.output_ref = _normalize_non_empty("tool step output_ref", self.output_ref)
        if self.only_if_missing_output is not None:
            self.only_if_missing_output = _normalize_non_empty(
                "tool step only_if_missing_output",
                self.only_if_missing_output,
            )


@dataclass(slots=True)
class WorkflowContract:
    """A dry-run description of one deterministic workflow."""

    contract_id: str
    domain: str
    trigger_phases: tuple[str, ...]
    required_refs: tuple[str, ...]
    steps: tuple[ToolStep, ...]
    required_missing_outputs: tuple[str, ...] = ()
    allowed_agent_ids: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    confidence: str = "high"

    def __post_init__(self) -> None:
        self.contract_id = _normalize_non_empty("workflow contract_id", self.contract_id)
        self.domain = _normalize_non_empty("workflow contract domain", self.domain)
        self.trigger_phases = _normalize_string_tuple("workflow contract trigger_phases", self.trigger_phases)
        self.required_refs = _normalize_string_tuple("workflow contract required_refs", self.required_refs)
        self.required_missing_outputs = _normalize_string_tuple(
            "workflow contract required_missing_outputs",
            self.required_missing_outputs,
            allow_empty=True,
        )
        self.allowed_agent_ids = _normalize_string_tuple(
            "workflow contract allowed_agent_ids",
            self.allowed_agent_ids,
            allow_empty=True,
        )
        self.required_capabilities = _normalize_string_tuple(
            "workflow contract required_capabilities",
            self.required_capabilities,
            allow_empty=True,
        )
        if not isinstance(self.steps, tuple):
            self.steps = tuple(self.steps)
        if not self.steps:
            raise ValidationError("workflow contract steps cannot be empty.")
        self.steps = tuple(step if isinstance(step, ToolStep) else ToolStep(**_as_dict(step)) for step in self.steps)
        self.confidence = _normalize_confidence(self.confidence)

    @property
    def required_tool_names(self) -> tuple[str, ...]:
        return _dedupe_strings([*[step.tool_name for step in self.steps], *self.required_capabilities])

    def matches_state(self, state: UnifiedWorkflowState) -> bool:
        if state.phase not in self.trigger_phases:
            return False
        if state.final_answer_ready or state.status == "completed":
            return False
        if not self.required_missing_outputs:
            return True
        missing = set(state.missing_outputs)
        return any(item in missing for item in self.required_missing_outputs)


@dataclass(slots=True)
class ActionContract:
    """A deterministic contract for one user-visible side-effect action."""

    contract_id: str
    domain: str
    trigger_phases: tuple[str, ...]
    required_outputs: tuple[str, ...]
    steps: tuple[ToolStep, ...]
    required_refs: tuple[str, ...] = ()
    allowed_agent_ids: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    forbidden_write_tools: tuple[str, ...] = ()
    confidence: str = "high"

    def __post_init__(self) -> None:
        self.contract_id = _normalize_non_empty("action contract_id", self.contract_id)
        self.domain = _normalize_non_empty("action contract domain", self.domain)
        self.trigger_phases = _normalize_string_tuple("action contract trigger_phases", self.trigger_phases)
        self.required_outputs = _normalize_string_tuple("action contract required_outputs", self.required_outputs)
        self.required_refs = _normalize_string_tuple(
            "action contract required_refs",
            self.required_refs,
            allow_empty=True,
        )
        self.allowed_agent_ids = _normalize_string_tuple(
            "action contract allowed_agent_ids",
            self.allowed_agent_ids,
            allow_empty=True,
        )
        self.required_capabilities = _normalize_string_tuple(
            "action contract required_capabilities",
            self.required_capabilities,
            allow_empty=True,
        )
        self.forbidden_write_tools = _normalize_string_tuple(
            "action contract forbidden_write_tools",
            self.forbidden_write_tools,
            allow_empty=True,
        )
        if not isinstance(self.steps, tuple):
            self.steps = tuple(self.steps)
        if not self.steps:
            raise ValidationError("action contract steps cannot be empty.")
        self.steps = tuple(step if isinstance(step, ToolStep) else ToolStep(**_as_dict(step)) for step in self.steps)
        self.confidence = _normalize_confidence(self.confidence)

    @property
    def required_tool_names(self) -> tuple[str, ...]:
        return _dedupe_strings([*[step.tool_name for step in self.steps], *self.required_capabilities])

    def matches_state(self, state: UnifiedWorkflowState) -> bool:
        if state.phase not in self.trigger_phases:
            return False
        if state.final_answer_ready or state.status == "completed":
            return False
        missing = set(state.missing_outputs)
        return any(item in missing for item in self.required_outputs)


@dataclass(slots=True)
class WorkflowContractRegistry:
    """In-memory registry for deterministic workflow contracts."""

    contracts: tuple[WorkflowContract, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.contracts, tuple):
            self.contracts = tuple(self.contracts)
        if not self.contracts:
            raise ValidationError("workflow contract registry cannot be empty.")
        seen: set[str] = set()
        normalized: list[WorkflowContract] = []
        for raw in self.contracts:
            contract = raw if isinstance(raw, WorkflowContract) else WorkflowContract(**_as_dict(raw))
            if contract.contract_id in seen:
                raise ValidationError(f"duplicate workflow contract_id: {contract.contract_id}")
            normalized.append(contract)
            seen.add(contract.contract_id)
        self.contracts = tuple(normalized)

    def matching_contracts(self, state: UnifiedWorkflowState) -> list[WorkflowContract]:
        return [contract for contract in self.contracts if contract.matches_state(state)]


@dataclass(slots=True)
class ActionContractRegistry:
    """In-memory registry for side-effect action contracts."""

    contracts: tuple[ActionContract, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.contracts, tuple):
            self.contracts = tuple(self.contracts)
        if not self.contracts:
            raise ValidationError("action contract registry cannot be empty.")
        seen: set[str] = set()
        normalized: list[ActionContract] = []
        for raw in self.contracts:
            contract = raw if isinstance(raw, ActionContract) else ActionContract(**_as_dict(raw))
            if contract.contract_id in seen:
                raise ValidationError(f"duplicate action contract_id: {contract.contract_id}")
            normalized.append(contract)
            seen.add(contract.contract_id)
        self.contracts = tuple(normalized)

    def matching_contracts(self, state: UnifiedWorkflowState) -> list[ActionContract]:
        return [contract for contract in self.contracts if contract.matches_state(state)]

    def contract_for_phase(self, phase: str | None) -> ActionContract | None:
        if phase is None:
            return None
        matches = [contract for contract in self.contracts if phase in contract.trigger_phases]
        if len(matches) != 1:
            return None
        return matches[0]


def builtin_workflow_contract_registry() -> WorkflowContractRegistry:
    """Return built-in contracts currently eligible for executor dry-run."""

    return WorkflowContractRegistry(
        contracts=(
            WorkflowContract(
                contract_id="career.resume_diagnosis.child.v1",
                domain="career",
                trigger_phases=("resume_diagnosis",),
                required_refs=("resume_source_artifact_id",),
                required_missing_outputs=("diagnosis_artifact", "resume_profile"),
                allowed_agent_ids=("resume_agent",),
                steps=(
                    ToolStep(
                        "session_create_text_artifact",
                        requires_model_payload=True,
                        output_ref="diagnosis_artifact_id",
                        only_if_missing_output="diagnosis_artifact",
                    ),
                    ToolStep(
                        "career_resume_profile_save",
                        args_from_refs={"source_artifact_id": "resume_source_artifact_id"},
                        args_from_previous_result={"diagnosis_artifact_id": "diagnosis_artifact_id"},
                        requires_model_payload=True,
                        output_ref="resume_profile_id",
                        only_if_missing_output="resume_profile",
                    ),
                ),
            ),
            WorkflowContract(
                contract_id="career.resume_version.project_action.v1",
                domain="career",
                trigger_phases=("resume_version",),
                required_refs=(
                    "application_id",
                    "resume_profile_id",
                    "jd_analysis_id",
                    "job_fit_report_id",
                ),
                required_missing_outputs=(
                    "resume_version",
                    "career_application_resume_version_link",
                ),
                steps=(
                    ToolStep(
                        "career_application_get",
                        args_from_refs={"application_id": "application_id"},
                        output_ref="career_application",
                        only_if_missing_output="career_application_read",
                    ),
                    ToolStep(
                        "career_resume_version_create",
                        args_from_refs={
                            "base_resume_profile_id": "resume_profile_id",
                            "target_jd_analysis_id": "jd_analysis_id",
                        },
                        requires_model_payload=True,
                        output_ref="resume_version_id",
                    ),
                    ToolStep(
                        "career_application_merge",
                        args_from_refs={"application_id": "application_id"},
                        args_from_previous_result={"resume_version_ids": "resume_version_id"},
                        output_ref="application_id",
                    ),
                ),
            ),
        )
    )


def builtin_action_contract_registry() -> ActionContractRegistry:
    """Return built-in side-effect action contracts."""

    return ActionContractRegistry(
        contracts=(
            ActionContract(
                contract_id="note.write.v1",
                domain="note",
                trigger_phases=("note_write",),
                required_outputs=("note",),
                forbidden_write_tools=(
                    "career_application_merge",
                    "career_resume_version_create",
                    "learning_task_create",
                    "memory_write",
                ),
                steps=(
                    ToolStep("note_create", requires_model_payload=True, output_ref="note_id", only_if_missing_output="note"),
                ),
            ),
            ActionContract(
                contract_id="rag.note.write.v1",
                domain="note",
                trigger_phases=("rag_note_write",),
                required_outputs=("retrieval_search", "retrieval_context_pack", "note"),
                forbidden_write_tools=(
                    "career_application_merge",
                    "career_resume_version_create",
                    "learning_task_create",
                    "memory_write",
                ),
                steps=(
                    ToolStep("retrieval_search", output_ref="retrieval_search", only_if_missing_output="retrieval_search"),
                    ToolStep(
                        "retrieval_context_pack",
                        output_ref="retrieval_context_pack",
                        only_if_missing_output="retrieval_context_pack",
                    ),
                    ToolStep("note_create", requires_model_payload=True, output_ref="note_id", only_if_missing_output="note"),
                    ToolStep("note_append", requires_model_payload=True, output_ref="note_id", only_if_missing_output="note"),
                ),
            ),
            ActionContract(
                contract_id="rag.learning_task.create.v1",
                domain="learning",
                trigger_phases=("rag_learning_task_create",),
                required_outputs=("retrieval_search", "retrieval_context_pack", "learning_task"),
                forbidden_write_tools=(
                    "career_application_merge",
                    "note_create",
                    "note_append",
                    "memory_write",
                ),
                steps=(
                    ToolStep("retrieval_search", output_ref="retrieval_search", only_if_missing_output="retrieval_search"),
                    ToolStep(
                        "retrieval_context_pack",
                        output_ref="retrieval_context_pack",
                        only_if_missing_output="retrieval_context_pack",
                    ),
                    ToolStep(
                        "learning_task_create",
                        requires_model_payload=True,
                        output_ref="learning_task_id",
                        only_if_missing_output="learning_task",
                    ),
                ),
            ),
            ActionContract(
                contract_id="interview.review.update.v1",
                domain="career",
                trigger_phases=("interview_review_update",),
                required_outputs=("retrieval_search", "retrieval_context_pack", "note", "career_application_update"),
                forbidden_write_tools=("learning_task_create", "memory_write"),
                steps=(
                    ToolStep("retrieval_search", output_ref="retrieval_search", only_if_missing_output="retrieval_search"),
                    ToolStep(
                        "retrieval_context_pack",
                        output_ref="retrieval_context_pack",
                        only_if_missing_output="retrieval_context_pack",
                    ),
                    ToolStep("note_create", requires_model_payload=True, output_ref="note_id", only_if_missing_output="note"),
                    ToolStep("note_append", requires_model_payload=True, output_ref="note_id", only_if_missing_output="note"),
                    ToolStep(
                        "career_application_merge",
                        requires_model_payload=True,
                        output_ref="application_id",
                        only_if_missing_output="career_application_update",
                    ),
                ),
            ),
            ActionContract(
                contract_id="career.profile.merge.required.v1",
                domain="career",
                trigger_phases=("resume_diagnosis",),
                required_outputs=("career_profile",),
                forbidden_write_tools=(
                    "delegate_agents",
                    "career_jd_analysis_save",
                    "career_job_fit_report_save",
                    "career_application_create",
                    "career_resume_version_create",
                ),
                steps=(
                    ToolStep(
                        "career_profile_merge",
                        requires_model_payload=True,
                        output_ref="career_profile_id",
                        only_if_missing_output="career_profile",
                    ),
                ),
            ),
        )
    )


def _normalize_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _normalize_string_tuple(name: str, values: tuple[str, ...], *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        values = tuple(values)
    output = _dedupe_strings(str(item) for item in values)
    if not output and not allow_empty:
        raise ValidationError(f"{name} cannot be empty.")
    return output


def _normalize_string_map(name: str, values: dict[str, str]) -> dict[str, str]:
    if not isinstance(values, dict):
        raise ValidationError(f"{name} must be a dictionary.")
    output: dict[str, str] = {}
    for raw_key, raw_value in values.items():
        key = _normalize_non_empty(f"{name} key", str(raw_key))
        value = _normalize_non_empty(f"{name} value", str(raw_value))
        output[key] = value
    return output


def _normalize_confidence(value: str) -> str:
    normalized = _normalize_non_empty("workflow contract confidence", value).lower()
    if normalized not in {"low", "medium", "high"}:
        raise ValidationError("workflow contract confidence must be low/medium/high.")
    return normalized


def _dedupe_strings(values: Any) -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = _normalize_non_empty("string", str(raw))
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return tuple(output)


def _as_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("workflow contract item must be a dataclass or dict.")
    return value
