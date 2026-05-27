from app.domain.models import RunContext, ToolDefinition
from app.runtime.workflow.contracts import ActionContract, ActionContractRegistry, ToolStep, WorkflowContract, WorkflowContractRegistry
from app.runtime.workflow.executor import dry_run_action_contract, dry_run_workflow_executor, tool_names_from_definitions
from app.runtime.workflow.state import UnifiedWorkflowState


def test_executor_dry_run_matches_resume_version_project_action() -> None:
    decision = dry_run_workflow_executor(
        state=_resume_version_state(),
        context=_context(),
        available_tool_names={
            "career_application_get",
            "career_resume_version_create",
            "career_application_merge",
        },
    )

    assert decision.executable is True
    assert decision.matched_contract_id == "career.resume_version.project_action.v1"
    assert decision.confidence == "high"
    assert decision.required_refs == [
        "application_id",
        "resume_profile_id",
        "jd_analysis_id",
        "job_fit_report_id",
    ]
    assert decision.missing_refs == []
    assert [step.tool_name for step in decision.planned_steps] == [
        "career_application_get",
        "career_resume_version_create",
        "career_application_merge",
    ]
    assert decision.planned_steps[0].resolved_args == {"application_id": "application_alpha"}
    assert decision.planned_steps[1].requires_model_payload is True
    assert decision.planned_steps[2].args_from_previous_result == {"resume_version_ids": "resume_version_id"}


def test_executor_dry_run_skips_application_read_when_refs_are_ready() -> None:
    state = _resume_version_state(missing_outputs=["resume_version", "career_application_resume_version_link"])

    decision = dry_run_workflow_executor(
        state=state,
        context=_context(),
        available_tool_names={
            "career_resume_version_create",
            "career_application_merge",
        },
    )

    assert decision.executable is True
    assert decision.required_tools == ["career_resume_version_create", "career_application_merge"]
    assert [step.tool_name for step in decision.planned_steps] == [
        "career_resume_version_create",
        "career_application_merge",
    ]
    assert decision.planned_steps[0].requires_model_payload is True
    assert decision.planned_steps[1].args_from_previous_result == {"resume_version_ids": "resume_version_id"}


def test_executor_dry_run_does_not_match_read_only_resume_version_state() -> None:
    state = _resume_version_state(missing_outputs=["career_application_read"])

    decision = dry_run_workflow_executor(state=state, context=_context())

    assert decision.executable is False
    assert decision.reason_not_executable == "no_matching_contract"


def test_executor_dry_run_reports_missing_required_refs() -> None:
    state = _resume_version_state()
    del state.known_refs["job_fit_report_id"]

    decision = dry_run_workflow_executor(
        state=state,
        context=_context(),
        available_tool_names={
            "career_application_get",
            "career_resume_version_create",
            "career_application_merge",
        },
    )

    assert decision.executable is False
    assert decision.reason_not_executable == "missing_required_refs"
    assert decision.missing_refs == ["job_fit_report_id"]


def test_executor_dry_run_rejects_reserved_placeholder_refs() -> None:
    state = _resume_version_state()
    state.known_refs["application_id"] = "application_id"

    decision = dry_run_workflow_executor(state=state, context=_context())

    assert decision.executable is False
    assert decision.reason_not_executable == "missing_required_refs"
    assert decision.missing_refs == ["application_id"]


def test_executor_dry_run_reports_missing_capabilities() -> None:
    decision = dry_run_workflow_executor(
        state=_resume_version_state(),
        context=_context(),
        available_tool_names={
            "career_application_get",
            "career_resume_version_create",
        },
    )

    assert decision.executable is False
    assert decision.reason_not_executable == "missing_required_capabilities"
    assert decision.missing_tools == ["career_application_merge"]


def test_executor_dry_run_rejects_ambiguous_contracts() -> None:
    registry = WorkflowContractRegistry(
        contracts=(
            _test_contract("contract.alpha"),
            _test_contract("contract.beta"),
        )
    )

    decision = dry_run_workflow_executor(
        state=_resume_version_state(),
        context=_context(),
        contract_registry=registry,
        available_tool_names={"career_application_get"},
    )

    assert decision.executable is False
    assert decision.matched_contract_id is None
    assert decision.matched_contract_count == 2
    assert decision.reason_not_executable == "ambiguous_contracts"


def test_executor_dry_run_is_capability_based_for_future_agent() -> None:
    decision = dry_run_workflow_executor(
        state=_resume_version_state(),
        context=_context(agent_id="career_action_agent"),
        available_tool_names={
            "career_application_get",
            "career_resume_version_create",
            "career_application_merge",
        },
    )

    assert decision.executable is True


def test_executor_dry_run_can_extract_tool_names_from_definitions() -> None:
    tool_names = tool_names_from_definitions(
        [
            ToolDefinition(name="career_application_get", description="get", parameters_schema={}),
            ToolDefinition(name="career_application_merge", description="merge", parameters_schema={}),
        ]
    )

    assert tool_names == {"career_application_get", "career_application_merge"}


def test_executor_dry_run_matches_child_resume_diagnosis_contract() -> None:
    decision = dry_run_workflow_executor(
        state=UnifiedWorkflowState(
            phase="resume_diagnosis",
            status="pending",
            known_refs={"resume_source_artifact_id": "artifact_resume_alpha"},
            missing_outputs=["diagnosis_artifact", "resume_profile"],
        ),
        context=_context(agent_id="resume_agent"),
        available_tool_names={"session_create_text_artifact", "career_resume_profile_save"},
    )

    assert decision.executable is True
    assert decision.matched_contract_id == "career.resume_diagnosis.child.v1"
    assert decision.required_refs == ["resume_source_artifact_id"]
    assert [step.tool_name for step in decision.planned_steps] == [
        "session_create_text_artifact",
        "career_resume_profile_save",
    ]
    assert decision.planned_steps[0].requires_model_payload is True
    assert decision.planned_steps[1].resolved_args == {"source_artifact_id": "artifact_resume_alpha"}
    assert decision.planned_steps[1].args_from_previous_result == {
        "diagnosis_artifact_id": "diagnosis_artifact_id"
    }


def test_executor_dry_run_child_resume_diagnosis_is_agent_scoped() -> None:
    decision = dry_run_workflow_executor(
        state=UnifiedWorkflowState(
            phase="resume_diagnosis",
            status="pending",
            known_refs={"resume_source_artifact_id": "artifact_resume_alpha"},
            missing_outputs=["diagnosis_artifact", "resume_profile"],
        ),
        context=_context(agent_id="agent_main"),
        available_tool_names={"session_create_text_artifact", "career_resume_profile_save"},
    )

    assert decision.executable is False
    assert decision.matched_contract_id == "career.resume_diagnosis.child.v1"
    assert decision.reason_not_executable == "agent_not_allowed"


def test_action_contract_dry_run_matches_rag_note_write() -> None:
    decision = dry_run_action_contract(
        state=UnifiedWorkflowState(
            phase="rag_note_write",
            status="pending",
            missing_outputs=["retrieval_search", "retrieval_context_pack", "note"],
        ),
        context=_context(),
        available_tool_names={"retrieval_search", "retrieval_context_pack", "note_create", "note_append"},
    )

    assert decision.executable is True
    assert decision.matched_contract_id == "rag.note.write.v1"
    assert decision.required_tools == ["retrieval_search", "retrieval_context_pack", "note_create", "note_append"]
    assert [step.tool_name for step in decision.planned_steps] == [
        "retrieval_search",
        "retrieval_context_pack",
        "note_create",
        "note_append",
    ]


def test_action_contract_dry_run_reports_missing_write_capability() -> None:
    decision = dry_run_action_contract(
        state=UnifiedWorkflowState(
            phase="rag_learning_task_create",
            status="pending",
            missing_outputs=["learning_task"],
        ),
        context=_context(),
        available_tool_names={"retrieval_search", "retrieval_context_pack"},
    )

    assert decision.executable is False
    assert decision.reason_not_executable == "missing_required_capabilities"
    assert decision.missing_tools == ["learning_task_create"]


def test_action_contract_dry_run_rejects_ambiguous_contracts() -> None:
    registry = ActionContractRegistry(
        contracts=(
            _test_action_contract("action.alpha"),
            _test_action_contract("action.beta"),
        )
    )

    decision = dry_run_action_contract(
        state=UnifiedWorkflowState(
            phase="rag_note_write",
            status="pending",
            missing_outputs=["note"],
        ),
        context=_context(),
        contract_registry=registry,
        available_tool_names={"note_create"},
    )

    assert decision.executable is False
    assert decision.reason_not_executable == "ambiguous_contracts"
    assert decision.matched_contract_count == 2


def _resume_version_state(*, missing_outputs: list[str] | None = None) -> UnifiedWorkflowState:
    return UnifiedWorkflowState(
        phase="resume_version",
        status="pending",
        known_refs={
            "application_id": "application_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "jd_analysis_id": "jd_alpha",
            "job_fit_report_id": "fit_alpha",
        },
        missing_outputs=missing_outputs
        or [
            "career_application_read",
            "resume_version",
            "career_application_resume_version_link",
        ],
    )


def _context(agent_id: str = "agent_main") -> RunContext:
    return RunContext(
        session_id="sess_executor_test",
        run_id="run_executor_test",
        agent_id=agent_id,
        turn_id="turn_executor_test",
        entry_agent_id=agent_id,
    )


def _test_contract(contract_id: str) -> WorkflowContract:
    return WorkflowContract(
        contract_id=contract_id,
        domain="career",
        trigger_phases=("resume_version",),
        required_refs=("application_id",),
        required_missing_outputs=("resume_version",),
        steps=(ToolStep("career_application_get", args_from_refs={"application_id": "application_id"}),),
    )


def _test_action_contract(contract_id: str) -> ActionContract:
    return ActionContract(
        contract_id=contract_id,
        domain="note",
        trigger_phases=("rag_note_write",),
        required_outputs=("note",),
        steps=(ToolStep("note_create", only_if_missing_output="note"),),
    )
