from __future__ import annotations

from app.runtime.workflow.action_plan import (
    action_contract_for_phase,
    action_contract_plan_payload,
    pending_action_plan_after_tool_result,
)


def test_action_plan_payload_requires_rag_note_search_first() -> None:
    contract = action_contract_for_phase("rag_note_write")
    assert contract is not None

    payload = action_contract_plan_payload(
        contract=contract,
        known_refs={"source_artifact_id": "artifact_alpha"},
        missing_outputs=["retrieval_search", "retrieval_context_pack", "note"],
    )

    assert payload["phase"] == "rag_note_write"
    assert payload["contract_id"] == "rag.note.write.v1"
    assert payload["current_allowed_tools"] == ["retrieval_search"]
    assert payload["next_allowed_tools"] == ["retrieval_search"]
    assert payload["required_tools"] == ["retrieval_search"]
    assert payload["upcoming_required_tools"] == ["retrieval_context_pack", "note_create", "note_append"]
    assert payload["schema_groups"] == ["retrieval"]
    assert payload["final_answer_ready"] is False
    assert "career_application_merge" in payload["discouraged_tools"]


def test_action_plan_payload_groups_same_missing_output_tools() -> None:
    contract = action_contract_for_phase("interview_review_update")
    assert contract is not None

    payload = action_contract_plan_payload(
        contract=contract,
        known_refs={"application_id": "application_alpha"},
        missing_outputs=["note", "career_application_update"],
    )

    assert payload["current_allowed_tools"] == ["note_create", "note_append"]
    assert payload["next_allowed_tools"] == ["note_create", "note_append"]
    assert payload["required_tools"] == ["note_create", "note_append"]
    assert payload["upcoming_required_tools"] == ["career_application_merge"]
    assert payload["schema_groups"] == ["notes"]
    assert "learning_task_create" in payload["discouraged_tools"]


def test_pending_action_plan_after_tool_result_advances_refs_and_missing_outputs() -> None:
    plan = pending_action_plan_after_tool_result(
        "note_create",
        payload_known_refs={"note_id": "note_alpha"},
        record_id="note_alpha",
        previous_pending_plan={
            "phase": "interview_review_update",
            "known_refs": {"application_id": "application_alpha"},
            "missing_outputs": ["note", "career_application_update"],
        },
        record_id_ref_key="note_id",
    )

    assert plan is not None
    assert plan["phase"] == "interview_review_update"
    assert plan["known_refs"]["application_id"] == "application_alpha"
    assert plan["known_refs"]["note_id"] == "note_alpha"
    assert plan["missing_outputs"] == ["career_application_update"]
    assert plan["next_allowed_tools"] == ["career_application_merge"]
    assert plan["required_tools"] == ["career_application_merge"]
    assert plan["upcoming_required_tools"] == []


def test_pending_action_plan_finalizes_when_all_outputs_done() -> None:
    plan = pending_action_plan_after_tool_result(
        "learning_task_create",
        payload_known_refs={"learning_task_id": "learning_task_alpha"},
        record_id="learning_task_alpha",
        previous_pending_plan={
            "phase": "rag_learning_task_create",
            "known_refs": {},
            "missing_outputs": ["learning_task"],
        },
        record_id_ref_key="learning_task_id",
    )

    assert plan is not None
    assert plan["final_answer_ready"] is True
    assert plan["missing_outputs"] == []
    assert plan["upcoming_required_tools"] == []
    assert plan["known_refs"]["learning_task_id"] == "learning_task_alpha"
    assert "career_application_merge" in plan["discouraged_tools"]
