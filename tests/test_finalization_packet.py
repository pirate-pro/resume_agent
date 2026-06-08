"""Tests for final-answer finalization packets."""

from __future__ import annotations

import json

from app.domain.models import ToolCall
from app.runtime.agent import (
    build_assistant_tool_call_message,
    build_final_answer_recovery_context,
    build_finalization_packet,
    build_tool_result_message,
    sanitize_messages_for_final_answer,
)


def test_finalization_packet_uses_committed_tool_result_not_attempt_arguments() -> None:
    messages = [
        {"role": "user", "content": "整理面试复盘并更新项目"},
        build_assistant_tool_call_message(
            "",
            [
                ToolCall(
                    name="career_profile_merge",
                    arguments={
                        "career_profile_id": "career_profile_default",
                        "skills": ["Python", "C++", "Spring Boot"],
                    },
                    tool_call_id="call_profile",
                )
            ],
        ),
        build_tool_result_message(
            tool_call_id="call_profile",
            content=json.dumps(
                {
                    "tool": "career_profile_merge",
                    "record_type": "career_profile",
                    "record_id": "career_profile_default",
                    "source_alignment_repairs": [{"reason": "unsupported_tech:cpp"}],
                    "record": {
                        "career_profile_id": "career_profile_default",
                        "skills": ["Python", "FastAPI", "RAG"],
                    },
                },
                ensure_ascii=False,
            ),
        ),
    ]

    packet = build_finalization_packet(
        messages=sanitize_messages_for_final_answer(messages),
        original_user_message="整理面试复盘并更新项目",
        pending_runtime_plan={
            "phase": "interview_review_update",
            "final_answer_ready": True,
            "known_refs": {"career_profile_id": "career_profile_default"},
        },
    )
    packet_text = json.dumps(packet.to_payload(), ensure_ascii=False)

    assert packet.phase == "interview_review_update"
    assert packet.final_answer_ready is True
    assert packet.product_refs == ["career_profile_default"]
    assert "career_profile_merge" in packet.completed_tools
    assert "Python" in packet_text
    assert "C++" not in packet_text
    assert "Spring Boot" not in packet_text
    assert "unsupported_tech:cpp" not in packet_text
    assert "source_alignment_repaired" in packet_text


def test_recovery_context_prefers_compact_finalization_packet() -> None:
    long_report = "# 报告\n\n" + ("候选人有 Python / FastAPI / RAG 经验。\n" * 200)
    messages = [
        {"role": "user", "content": "保存笔记"},
        build_assistant_tool_call_message(
            "",
            [
                ToolCall(
                    name="note_create",
                    arguments={"title": "复盘", "content": long_report},
                    tool_call_id="call_note",
                )
            ],
        ),
        build_tool_result_message(
            tool_call_id="call_note",
            content=json.dumps(
                {
                    "tool": "note_create",
                    "record_type": "note",
                    "record_id": "note_alpha",
                    "title": "复盘",
                    "summary": "已保存面试复盘笔记。",
                    "evidence_refs": ["application_alpha", "fit_alpha"],
                },
                ensure_ascii=False,
            ),
        ),
    ]
    context = build_final_answer_recovery_context(
        messages=messages,
        original_user_message="保存笔记",
        recovery_prompt="请补最终答复",
        pending_runtime_plan={
            "phase": "rag_note_write",
            "final_answer_ready": True,
            "known_refs": {"note_id": "note_alpha"},
        },
    )
    recovery_text = json.dumps(context.messages, ensure_ascii=False)

    assert context.used_packet is True
    assert len(context.messages) == 3
    assert "FINALIZATION_PACKET" in recovery_text
    assert "Do not list candidate name" in recovery_text
    assert "不要在最终答复里列出这些细节" in recovery_text
    assert "note_alpha" in recovery_text
    assert "application_alpha" in recovery_text
    assert "候选人有 Python" not in recovery_text
    assert "tool_calls" not in recovery_text
    assert "content_omitted" not in recovery_text


def test_recovery_context_falls_back_when_no_grounded_facts() -> None:
    messages = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": ""}]

    context = build_final_answer_recovery_context(
        messages=messages,
        original_user_message="你好",
        recovery_prompt="请补最终答复",
    )

    assert context.used_packet is False
    assert context.messages[-1]["content"] == "请补最终答复"


def test_finalization_packet_filters_orchestration_refs() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "运行时工具状态摘要（完整工具结果见事件日志）：\n"
            + json.dumps(
                {
                    "runtime_tool_state": "compact",
                    "latest_refs": {
                        "task_id": "task_alpha",
                        "task_group_id": "task_group_alpha",
                        "child_run_id": "run_child",
                        "target_agent_id": "resume_agent",
                        "resume_profile_id": "resume_profile_alpha",
                        "diagnosis_artifact_id": "artifact_diag",
                    },
                    "successful_tools": ["delegate_agents"],
                },
                ensure_ascii=False,
            ),
        }
    ]

    packet = build_finalization_packet(
        messages=messages,
        original_user_message="诊断简历",
        pending_runtime_plan={
            "known_refs": {
                "source_session_id": "sess_alpha",
                "career_profile_id": "career_profile_default",
            }
        },
    )
    payload_text = json.dumps(packet.to_payload(), ensure_ascii=False)

    assert packet.product_refs == ["career_profile_default", "resume_profile_alpha"]
    assert packet.artifact_refs == ["artifact_diag"]
    assert "task_alpha" not in payload_text
    assert "task_group_alpha" not in payload_text
    assert "run_child" not in payload_text
    assert "resume_agent" not in payload_text
    assert "sess_alpha" not in payload_text
