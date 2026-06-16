from __future__ import annotations

from app.domain.models import ToolCall
from app.runtime.agent.tool_call_controller import (
    MAX_HIDDEN_RUNTIME_TOOL_SUPPRESSIONS_PER_PLAN,
    ToolCallController,
)


def test_controller_auto_call_uses_interview_review_action_payload() -> None:
    controller = ToolCallController()

    tool_call = controller.strict_required_tool_auto_call_from_plan(
        pending_runtime_plan={
            "phase": "interview_review_update",
            "final_answer_ready": False,
            "required_tools": ["career_application_merge"],
            "next_allowed_tools": ["career_application_merge"],
            "missing_outputs": ["career_application_update"],
            "known_refs": {
                "application_id": "application_alpha",
                "note_id": "note_alpha",
            },
        },
        visible_tool_names_for_round={"career_application_merge"},
        tool_call_id="call_1",
    )

    assert tool_call is not None
    assert tool_call.name == "career_application_merge"
    assert tool_call.tool_call_id == "call_1"
    assert tool_call.arguments["application_id"] == "application_alpha"
    assert tool_call.arguments["updates"]["stage"] == "interviewing"
    assert tool_call.arguments["evidence_refs"] == ["application_alpha", "note_alpha"]


def test_controller_auto_call_uses_generic_required_tool_hint() -> None:
    controller = ToolCallController()

    tool_call = controller.strict_required_tool_auto_call_from_plan(
        pending_runtime_plan={
            "phase": "resume_version",
            "final_answer_ready": False,
            "required_tools": ["career_application_merge"],
            "next_allowed_tools": ["career_application_merge"],
            "missing_outputs": ["career_application_merge"],
            "known_refs": {
                "application_id": "application_alpha",
                "resume_version_id": "resume_version_alpha",
            },
        },
        visible_tool_names_for_round={"career_application_merge"},
    )

    assert tool_call is not None
    assert tool_call.arguments == {
        "application_id": "application_alpha",
        "updates": {"resume_version_ids": ["resume_version_alpha"]},
        "evidence_refs": ["resume_version_alpha"],
    }


def test_controller_replaces_repeated_retrieval_search_with_context_pack() -> None:
    controller = ToolCallController()

    tool_call = controller.strict_required_tool_auto_call(
        ToolCall(
            name="retrieval_search",
            arguments={
                "query": "匹配 报告 简历 JD 分析",
                "source_types": '["career", "notes"]',
                "top_k": "20",
                "max_chars": "50000",
                "include_archived": "False",
            },
            tool_call_id="call_retrieval",
        ),
        pending_runtime_plan={
            "phase": "rag_learning_task_create",
            "final_answer_ready": False,
            "required_tools": ["retrieval_context_pack"],
            "next_allowed_tools": ["retrieval_context_pack"],
            "missing_outputs": ["retrieval_context_pack", "learning_task"],
        },
        visible_tool_names_for_round={"retrieval_context_pack"},
    )

    assert tool_call is not None
    assert tool_call.name == "retrieval_context_pack"
    assert tool_call.tool_call_id == "call_retrieval"
    assert tool_call.arguments == {
        "query": "匹配 报告 简历 JD 分析",
        "source_types": ["career", "notes"],
        "top_k": 20,
        "max_chars": 50000,
        "include_archived": False,
    }


def test_controller_does_not_auto_call_when_required_tool_hidden_or_ambiguous() -> None:
    controller = ToolCallController()

    assert (
        controller.strict_required_tool_auto_call_from_plan(
            pending_runtime_plan={
                "required_tools": ["career_application_merge"],
                "known_refs": {"application_id": "application_alpha", "resume_version_id": "resume_version_alpha"},
            },
            visible_tool_names_for_round={"tool_search"},
        )
        is None
    )
    assert (
        controller.strict_required_tool_auto_call_from_plan(
            pending_runtime_plan={
                "required_tools": ["career_application_merge", "career_resume_version_create"],
                "known_refs": {"application_id": "application_alpha", "resume_version_id": "resume_version_alpha"},
            },
            visible_tool_names_for_round={"career_application_merge", "career_resume_version_create"},
        )
        is None
    )


def test_controller_hidden_runtime_support_tool_allowed_for_resume_version_artifact() -> None:
    controller = ToolCallController()

    assert controller.hidden_runtime_support_tool_allowed(
        ToolCall(
            name="session_create_text_artifact",
            arguments={"title": "定制简历版本.md", "kind": "generated_file"},
        ),
        pending_runtime_plan={
            "phase": "resume_version",
            "missing_outputs": ["resume_version"],
        },
    )
    assert not controller.hidden_runtime_support_tool_allowed(
        ToolCall(
            name="session_create_text_artifact",
            arguments={"title": "简历诊断报告.md", "kind": "generated_file"},
        ),
        pending_runtime_plan={
            "phase": "resume_version",
            "missing_outputs": ["resume_version"],
        },
    )


def test_controller_suppresses_hidden_tools_only_when_required_tool_visible() -> None:
    controller = ToolCallController()
    plan = {
        "phase": "resume_version",
        "required_tools": ["career_application_merge"],
        "missing_outputs": ["career_application_merge"],
    }

    assert controller.hidden_runtime_tool_names_to_suppress(
        [ToolCall(name="tool_search", arguments={"query": "career_application_merge"})],
        pending_runtime_plan=plan,
        visible_tool_names_for_round={"career_application_merge"},
        strict_runtime_tool_mode=True,
    ) == ["tool_search"]
    assert controller.hidden_runtime_tool_names_to_suppress(
        [ToolCall(name="tool_search", arguments={"query": "career_application_merge"})],
        pending_runtime_plan=plan,
        visible_tool_names_for_round={"tool_search", "career_application_merge"},
        strict_runtime_tool_mode=True,
    ) == []


def test_controller_suppression_key_and_event_payload_are_stable() -> None:
    controller = ToolCallController()
    plan = {
        "phase": "resume_version",
        "required_tools": ["career_application_merge"],
        "missing_outputs": ["career_application_merge"],
        "known_refs": {"application_id": "application_alpha"},
    }
    replacement = ToolCall(
        name="career_application_merge",
        arguments={"application_id": "application_alpha"},
        tool_call_id="call_2",
    )

    assert MAX_HIDDEN_RUNTIME_TOOL_SUPPRESSIONS_PER_PLAN == 1
    assert controller.hidden_runtime_tool_suppression_key(
        pending_runtime_plan=plan,
        hidden_tool_names=["tool_search"],
    ) == (
        '{"blocked_tools":["tool_search"],"known_ref_keys":["application_id"],'
        '"missing_outputs":["career_application_merge"],"phase":"resume_version",'
        '"required_tools":["career_application_merge"]}'
    )
    payload = controller.strict_auto_execute_event_payload(
        blocked_tool_call=ToolCall(name="tool_search", arguments={}),
        replacement_tool_call=replacement,
        pending_runtime_plan=plan,
    )
    assert payload["reason"] == "strict_hidden_tool_replaced_with_required_tool"
    assert payload["required_tool"] == "career_application_merge"
    assert payload["required_tool_call_hint"]["tool_name"] == "career_application_merge"
