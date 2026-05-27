from __future__ import annotations

from app.runtime.workflow.action_payloads import (
    build_action_payload_tool_call_from_plan,
    build_required_tool_call_hint_for_plan,
)


def _interview_review_plan(**overrides: object) -> dict[str, object]:
    plan: dict[str, object] = {
        "phase": "interview_review_update",
        "final_answer_ready": False,
        "required_tools": ["career_application_merge"],
        "next_allowed_tools": ["career_application_merge"],
        "missing_outputs": ["career_application_update"],
        "known_refs": {
            "application_id": "application_alpha",
            "note_id": "note_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "jd_analysis_id": "jd_alpha",
            "job_fit_report_id": "fit_alpha",
        },
    }
    plan.update(overrides)
    return plan


def test_action_payload_builder_creates_interview_review_application_merge_call() -> None:
    tool_call = build_action_payload_tool_call_from_plan(
        pending_runtime_plan=_interview_review_plan(),
        visible_tool_names_for_round={"career_application_merge"},
        tool_call_id="call_1",
    )

    assert tool_call is not None
    assert tool_call.name == "career_application_merge"
    assert tool_call.tool_call_id == "call_1"
    assert tool_call.arguments["application_id"] == "application_alpha"
    assert tool_call.arguments["updates"]["stage"] == "interviewing"
    assert "note_alpha" in tool_call.arguments["updates"]["notes"]
    assert tool_call.arguments["evidence_refs"] == [
        "application_alpha",
        "note_alpha",
        "resume_profile_alpha",
        "career_profile_default",
        "jd_alpha",
        "fit_alpha",
    ]


def test_action_payload_builder_rejects_non_matching_plan_or_hidden_tool() -> None:
    assert (
        build_action_payload_tool_call_from_plan(
            pending_runtime_plan=_interview_review_plan(phase="rag_note_write"),
            visible_tool_names_for_round={"career_application_merge"},
        )
        is None
    )
    assert (
        build_action_payload_tool_call_from_plan(
            pending_runtime_plan=_interview_review_plan(),
            visible_tool_names_for_round={"tool_search"},
        )
        is None
    )
    assert (
        build_action_payload_tool_call_from_plan(
            pending_runtime_plan=_interview_review_plan(final_answer_ready=True),
            visible_tool_names_for_round={"career_application_merge"},
        )
        is None
    )


def test_required_tool_hint_uses_interview_review_payload_when_refs_exist() -> None:
    hint = build_required_tool_call_hint_for_plan("career_application_merge", _interview_review_plan())

    assert hint is not None
    assert hint["tool_name"] == "career_application_merge"
    assert hint["missing_args"] == []
    assert hint["available_args"]["application_id"] == "application_alpha"
    assert hint["available_args"]["updates"]["stage"] == "interviewing"
    assert hint["retry_tool_call_skeleton"] == hint["available_args"]


def test_required_tool_hint_reports_missing_interview_review_refs() -> None:
    hint = build_required_tool_call_hint_for_plan(
        "career_application_merge",
        _interview_review_plan(known_refs={"resume_profile_id": "resume_profile_alpha"}),
    )

    assert hint is not None
    assert hint["available_args"] == {}
    assert hint["missing_args"] == ["application_id", "note_id"]
    assert hint["retry_tool_call_skeleton"] == {}


def test_required_tool_hint_falls_back_to_generic_application_merge_hint() -> None:
    hint = build_required_tool_call_hint_for_plan(
        "career_application_merge",
        {
            "phase": "resume_version",
            "known_refs": {
                "application_id": "application_alpha",
                "resume_version_id": "resume_version_alpha",
            },
        },
    )

    assert hint is not None
    assert hint["available_args"]["application_id"] == "application_alpha"
    assert hint["available_args"]["updates"] == {"resume_version_ids": ["resume_version_alpha"]}
