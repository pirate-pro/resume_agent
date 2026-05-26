"""Tests for per-run tool message context windowing."""

from __future__ import annotations

import json

from app.domain.models import ToolCall, ToolExecutionResult
from app.runtime.agent.tool_context_window import ToolContextWindow, build_tool_observation
from app.runtime.agent.tool_messages import build_assistant_tool_call_message, build_tool_result_message

__all__ = []


def test_compact_window_keeps_pending_exchange_and_summarizes_consumed_exchange() -> None:
    window = ToolContextWindow(base_messages=[{"role": "user", "content": "开始"}], mode="compact")
    first_call = ToolCall(
        name="career_application_list",
        arguments={"include_archived": False},
        tool_call_id="call_first",
    )
    first_content = json.dumps(
        {
            "record_type": "career_application",
            "records": [
                {
                    "application_id": "application_alpha",
                    "resume_profile_id": "resume_profile_alpha",
                    "jd_analysis_id": "jd_alpha",
                    "job_fit_report_id": "fit_alpha",
                    "source_artifact_id": "artifact_jd_alpha",
                    "summary": "当前项目",
                }
            ],
        },
        ensure_ascii=False,
    )
    window.set_pending_exchange(
        assistant_message=build_assistant_tool_call_message("", [first_call]),
        tool_messages=[build_tool_result_message(tool_call_id="call_first", content=first_content)],
        observations=[
            build_tool_observation(
                tool_call=first_call,
                result=ToolExecutionResult(
                    tool_name="career_application_list",
                    success=True,
                    content=first_content,
                ),
                model_visible_content=first_content,
            )
        ],
    )

    pending_messages = window.render_messages()
    assert [message["role"] for message in pending_messages] == ["user", "assistant", "tool"]
    assert pending_messages[-1]["tool_call_id"] == "call_first"

    window.consume_pending_exchange()
    second_call = ToolCall(
        name="career_resume_version_create",
        arguments={"content": "# 简历" * 100, "base_resume_profile_id": "resume_profile_alpha"},
        tool_call_id="call_second",
    )
    second_content = json.dumps(
        {
            "record_type": "resume_version",
            "record_id": "resume_version_alpha",
            "status": "active",
            "record": {
                "resume_version_id": "resume_version_alpha",
                "artifact_id": "artifact_resume_alpha",
                "base_resume_profile_id": "resume_profile_alpha",
                "target_jd_analysis_id": "jd_alpha",
            },
        },
        ensure_ascii=False,
    )
    window.set_pending_exchange(
        assistant_message=build_assistant_tool_call_message("", [second_call]),
        tool_messages=[build_tool_result_message(tool_call_id="call_second", content=second_content)],
        observations=[
            build_tool_observation(
                tool_call=second_call,
                result=ToolExecutionResult(
                    tool_name="career_resume_version_create",
                    success=True,
                    content=second_content,
                ),
                model_visible_content=second_content,
            )
        ],
    )

    rendered = window.render_messages()
    roles = [message["role"] for message in rendered]
    state_message = rendered[1]

    assert roles == ["user", "assistant", "assistant", "tool"]
    assert "runtime_tool_state" in state_message["content"]
    assert "application_alpha" in state_message["content"]
    assert "call_first" in state_message["content"]
    assert rendered[-1]["tool_call_id"] == "call_second"
    assert "call_first" not in json.dumps(rendered[2:], ensure_ascii=False)

    usage = window.usage_payload()
    assert usage["tool_context_window_mode"] == "compact"
    assert usage["pending_tool_exchange_count"] == 1
    assert usage["compacted_tool_observation_count"] == 1
    assert usage["tool_state_message_estimate_tokens"] > 0


def test_off_window_preserves_consumed_tool_messages() -> None:
    window = ToolContextWindow(base_messages=[{"role": "user", "content": "开始"}], mode="off")
    first_call = ToolCall(name="memory_write", arguments={"content": "first"}, tool_call_id="call_first")
    second_call = ToolCall(name="memory_write", arguments={"content": "second"}, tool_call_id="call_second")

    window.set_pending_exchange(
        assistant_message=build_assistant_tool_call_message("", [first_call]),
        tool_messages=[build_tool_result_message(tool_call_id="call_first", content='{"ok": true}')],
        observations=[],
    )
    window.consume_pending_exchange()
    window.set_pending_exchange(
        assistant_message=build_assistant_tool_call_message("", [second_call]),
        tool_messages=[build_tool_result_message(tool_call_id="call_second", content='{"ok": true}')],
        observations=[],
    )

    rendered = window.render_messages()

    assert [message["role"] for message in rendered] == ["user", "assistant", "tool", "assistant", "tool"]
    assert [message.get("tool_call_id") for message in rendered if message["role"] == "tool"] == [
        "call_first",
        "call_second",
    ]
    assert window.usage_payload()["compacted_tool_observation_count"] == 0


def test_observation_drops_large_content_arguments_and_extracts_tool_search_reveal() -> None:
    call = ToolCall(
        name="tool_search",
        arguments={"query": "创建定制简历版本", "content": "x" * 1000},
        tool_call_id="call_search",
    )
    content = json.dumps(
        {
            "matched_groups": ["career"],
            "revealed_tool_count": 2,
            "revealed_tool_names": ["career_resume_version_create", "career_application_merge"],
        },
        ensure_ascii=False,
    )

    observation = build_tool_observation(
        tool_call=call,
        result=ToolExecutionResult(tool_name="tool_search", success=True, content=content),
        model_visible_content=content,
    )

    assert observation.arguments_preview["content_omitted"] == {"chars": 1000}
    assert "content" not in observation.arguments_preview
    assert observation.revealed_tool_names == ["career_resume_version_create", "career_application_merge"]
    assert "revealed 2 tools" in str(observation.summary)


def test_compact_state_carries_revealed_tools_guidance() -> None:
    window = ToolContextWindow(base_messages=[{"role": "user", "content": "开始"}], mode="compact")
    call = ToolCall(
        name="tool_search",
        arguments={"query": "创建定制简历并更新求职项目"},
        tool_call_id="call_search",
    )
    content = json.dumps(
        {
            "matched_groups": ["career"],
            "revealed_tool_count": 3,
            "revealed_tool_names": [
                "career_resume_profile_get",
                "career_resume_version_create",
                "career_application_merge",
            ],
        },
        ensure_ascii=False,
    )

    window.set_pending_exchange(
        assistant_message=build_assistant_tool_call_message("", [call]),
        tool_messages=[build_tool_result_message(tool_call_id="call_search", content=content)],
        observations=[
            build_tool_observation(
                tool_call=call,
                result=ToolExecutionResult(tool_name="tool_search", success=True, content=content),
                model_visible_content=content,
            )
        ],
    )
    window.consume_pending_exchange()

    rendered = window.render_messages()
    state_content = str(rendered[1]["content"])

    assert "career_resume_version_create" in state_content
    assert "revealed_tool_groups" in state_content
    assert "不要为了这些工具再次调用 tool_search" in state_content


def test_strict_compact_state_filters_discouraged_observations_but_keeps_required_support() -> None:
    window = ToolContextWindow(base_messages=[{"role": "user", "content": "开始"}], mode="compact")
    get_call = ToolCall(
        name="career_application_get",
        arguments={"application_id": "application_alpha"},
        tool_call_id="call_get",
    )
    get_content = json.dumps(
        {
            "record_type": "career_application",
            "record_id": "application_alpha",
            "record": {"application_id": "application_alpha"},
        },
        ensure_ascii=False,
    )
    create_call = ToolCall(
        name="career_resume_version_create",
        arguments={"base_resume_profile_id": "resume_profile_alpha", "content": "# 简历"},
        tool_call_id="call_create",
    )
    create_content = json.dumps(
        {
            "record_type": "resume_version",
            "record_id": "resume_version_alpha",
            "record": {
                "resume_version_id": "resume_version_alpha",
                "artifact_id": "artifact_resume_version_alpha",
            },
        },
        ensure_ascii=False,
    )

    window.set_pending_exchange(
        assistant_message=build_assistant_tool_call_message("", [get_call, create_call]),
        tool_messages=[
            build_tool_result_message(tool_call_id="call_get", content=get_content),
            build_tool_result_message(tool_call_id="call_create", content=create_content),
        ],
        observations=[
            build_tool_observation(
                tool_call=get_call,
                result=ToolExecutionResult(tool_name="career_application_get", success=True, content=get_content),
                model_visible_content=get_content,
            ),
            build_tool_observation(
                tool_call=create_call,
                result=ToolExecutionResult(
                    tool_name="career_resume_version_create",
                    success=True,
                    content=create_content,
                ),
                model_visible_content=create_content,
            ),
        ],
    )
    window.consume_pending_exchange()

    rendered = window.render_messages(
        runtime_plan={
            "phase": "resume_version",
            "required_tools": ["career_application_merge"],
            "next_allowed_tools": ["career_application_merge"],
            "known_refs": {
                "application_id": "application_alpha",
                "resume_version_id": "resume_version_alpha",
            },
            "missing_outputs": ["career_application_resume_version_link"],
            "discouraged_tools": ["career_application_get", "tool_search"],
        },
        strict_mode=True,
    )
    payload = json.loads(str(rendered[1]["content"]).split("\n", 1)[1])
    recent_tools = [item["tool"] for item in payload["recent_observations"]]

    assert payload["strict_runtime_plan"] is True
    assert payload["shown_tool_call_count"] == 1
    assert recent_tools == ["career_resume_version_create"]
    assert payload["known_refs"]["application_id"] == "application_alpha"
    assert payload["latest_refs"]["resume_version_id"] == "resume_version_alpha"


def test_compact_state_tells_model_to_stop_after_completed_resume_version_flow() -> None:
    window = ToolContextWindow(base_messages=[{"role": "user", "content": "开始"}], mode="compact")
    create_call = ToolCall(
        name="career_resume_version_create",
        arguments={"base_resume_profile_id": "resume_profile_alpha", "content": "# 简历"},
        tool_call_id="call_create",
    )
    create_content = json.dumps(
        {
            "record_type": "resume_version",
            "record_id": "resume_version_alpha",
            "record": {"resume_version_id": "resume_version_alpha", "artifact_id": "artifact_resume_alpha"},
        },
        ensure_ascii=False,
    )
    merge_call = ToolCall(
        name="career_application_merge",
        arguments={"application_id": "application_alpha"},
        tool_call_id="call_merge",
    )
    merge_content = json.dumps(
        {
            "record_type": "career_application",
            "record_id": "application_alpha",
            "record": {"resume_version_ids": ["resume_version_alpha"]},
        },
        ensure_ascii=False,
    )

    window.set_pending_exchange(
        assistant_message=build_assistant_tool_call_message("", [create_call, merge_call]),
        tool_messages=[
            build_tool_result_message(tool_call_id="call_create", content=create_content),
            build_tool_result_message(tool_call_id="call_merge", content=merge_content),
        ],
        observations=[
            build_tool_observation(
                tool_call=create_call,
                result=ToolExecutionResult(
                    tool_name="career_resume_version_create",
                    success=True,
                    content=create_content,
                ),
                model_visible_content=create_content,
            ),
            build_tool_observation(
                tool_call=merge_call,
                result=ToolExecutionResult(
                    tool_name="career_application_merge",
                    success=True,
                    content=merge_content,
                ),
                model_visible_content=merge_content,
            ),
        ],
    )
    window.consume_pending_exchange()

    state_content = str(window.render_messages()[1]["content"])

    assert "workflow_completion_guidance" in state_content
    assert "下一步应给最终答复" in state_content
    assert "不要再次创建 ResumeVersion" in state_content


def test_compact_window_replays_successful_tool_call_arguments_compactly() -> None:
    window = ToolContextWindow(base_messages=[{"role": "user", "content": "开始"}], mode="compact")
    long_content = "# 定制简历\n" * 500
    call = ToolCall(
        name="career_resume_version_create",
        arguments={
            "resume_version_id": "resume_version_alpha",
            "base_resume_profile_id": "resume_profile_alpha",
            "content": long_content,
            "evidence_refs": ["artifact_resume_alpha", "fit_alpha"],
        },
        tool_call_id="call_create",
    )
    content = json.dumps(
        {
            "record_type": "resume_version",
            "record_id": "resume_version_alpha",
            "record": {
                "resume_version_id": "resume_version_alpha",
                "artifact_id": "artifact_resume_alpha",
            },
        },
        ensure_ascii=False,
    )

    window.set_pending_exchange(
        assistant_message=build_assistant_tool_call_message("", [call]),
        tool_messages=[build_tool_result_message(tool_call_id="call_create", content=content)],
        observations=[
            build_tool_observation(
                tool_call=call,
                result=ToolExecutionResult(
                    tool_name="career_resume_version_create",
                    success=True,
                    content=content,
                ),
                model_visible_content=content,
            )
        ],
    )

    rendered = window.render_messages()
    replayed_arguments = json.loads(rendered[1]["tool_calls"][0]["function"]["arguments"])

    assert "content" not in replayed_arguments
    assert replayed_arguments["content_omitted"] == {"chars": len(long_content)}
    assert replayed_arguments["resume_version_id"] == "resume_version_alpha"
    assert replayed_arguments["evidence_refs"] == ["artifact_resume_alpha", "fit_alpha"]


def test_compact_window_summarizes_failed_long_content_arguments_for_repair() -> None:
    window = ToolContextWindow(base_messages=[{"role": "user", "content": "开始"}], mode="compact")
    long_content = "# 定制简历\n" * 200
    call = ToolCall(
        name="career_resume_version_create",
        arguments={"content": long_content, "base_resume_profile_id": "resume_profile_alpha"},
        tool_call_id="call_failed",
    )

    window.set_pending_exchange(
        assistant_message=build_assistant_tool_call_message("", [call]),
        tool_messages=[build_tool_result_message(tool_call_id="call_failed", content='{"error":"validation"}')],
        observations=[
            build_tool_observation(
                tool_call=call,
                result=ToolExecutionResult(
                    tool_name="career_resume_version_create",
                    success=False,
                    content='{"error":"validation"}',
                ),
                model_visible_content='{"error":"validation"}',
            )
        ],
    )

    rendered = window.render_messages()
    replayed_arguments = json.loads(rendered[1]["tool_calls"][0]["function"]["arguments"])

    assert replayed_arguments["content_omitted"] == {"chars": len(long_content)}
    assert replayed_arguments["content_preview"].startswith("# 定制简历")
    assert "content" not in replayed_arguments


def test_compact_state_tells_model_not_to_duplicate_created_text_artifact() -> None:
    window = ToolContextWindow(base_messages=[{"role": "user", "content": "开始"}], mode="compact")
    call = ToolCall(
        name="session_create_text_artifact",
        arguments={"title": "简历诊断报告.txt", "content": "诊断报告正文"},
        tool_call_id="call_artifact",
    )
    content = json.dumps(
        {
            "artifact_id": "artifact_report_alpha",
            "title": "简历诊断报告.txt",
            "status": "ready",
        },
        ensure_ascii=False,
    )

    window.set_pending_exchange(
        assistant_message=build_assistant_tool_call_message("", [call]),
        tool_messages=[build_tool_result_message(tool_call_id="call_artifact", content=content)],
        observations=[
            build_tool_observation(
                tool_call=call,
                result=ToolExecutionResult(
                    tool_name="session_create_text_artifact",
                    success=True,
                    content=content,
                ),
                model_visible_content=content,
            )
        ],
    )
    window.consume_pending_exchange()

    state_content = str(window.render_messages()[1]["content"])

    assert "不要为同一标题/内容重复创建" in state_content
    assert "artifact_report_alpha" in state_content


def test_compact_state_surfaces_workflow_runtime_next_action() -> None:
    window = ToolContextWindow(base_messages=[{"role": "user", "content": "开始"}], mode="compact")
    call = ToolCall(
        name="session_read_artifact",
        arguments={"artifact_id": "artifact_resume"},
        tool_call_id="call_blocked_read",
    )
    content = json.dumps(
        {
            "workflow_runtime_result": True,
            "policy": "block",
            "reason": "job_fit_report_artifact_ready_stop_low_level_actions",
            "next_action": "调用 career_job_fit_report_save，并把 report_artifact_id 设置为已有 artifact_id：artifact_fit_report。",
            "missing_outputs": ["job_fit_report"],
        },
        ensure_ascii=False,
    )

    window.set_pending_exchange(
        assistant_message=build_assistant_tool_call_message("", [call]),
        tool_messages=[build_tool_result_message(tool_call_id="call_blocked_read", content=content)],
        observations=[
            build_tool_observation(
                tool_call=call,
                result=ToolExecutionResult(
                    tool_name="session_read_artifact",
                    success=True,
                    content=content,
                ),
                model_visible_content=content,
            )
        ],
    )
    window.consume_pending_exchange()

    state_content = str(window.render_messages()[1]["content"])

    assert "WorkflowRuntime" in state_content
    assert "career_job_fit_report_save" in state_content
    assert "job_fit_report" in state_content


def test_compact_state_tells_model_not_to_duplicate_jd_analysis_save() -> None:
    window = ToolContextWindow(base_messages=[{"role": "user", "content": "开始"}], mode="compact")
    call = ToolCall(
        name="career_jd_analysis_save",
        arguments={"jd_analysis_id": "jd_analysis_alpha", "source_artifact_id": "artifact_jd_alpha"},
        tool_call_id="call_jd_save",
    )
    content = json.dumps(
        {
            "record_type": "jd_analysis",
            "record_id": "jd_analysis_alpha",
            "record": {"jd_analysis_id": "jd_analysis_alpha"},
        },
        ensure_ascii=False,
    )

    window.set_pending_exchange(
        assistant_message=build_assistant_tool_call_message("", [call]),
        tool_messages=[build_tool_result_message(tool_call_id="call_jd_save", content=content)],
        observations=[
            build_tool_observation(
                tool_call=call,
                result=ToolExecutionResult(
                    tool_name="career_jd_analysis_save",
                    success=True,
                    content=content,
                ),
                model_visible_content=content,
            )
        ],
    )
    window.consume_pending_exchange()

    state_content = str(window.render_messages()[1]["content"])

    assert "JDAnalysis 已在本 run 成功保存" in state_content
    assert "不要重复保存同一份 JD 分析" in state_content
