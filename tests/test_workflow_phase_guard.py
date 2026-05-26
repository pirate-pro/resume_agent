"""Tests for read-only career workflow phase snapshots."""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import RunContext, SessionArtifact
from app.runtime.context.models import CareerFlowState, CurrentWorkflowState
from app.runtime.workflow.career_phase import build_career_phase_snapshot
from app.runtime.workflow.phase import format_workflow_phase_lines

__all__ = []


def _context(agent_id: str = "agent_main", entry_agent_id: str = "agent_main") -> RunContext:
    return RunContext(
        session_id="sess_phase",
        run_id="run_phase",
        agent_id=agent_id,
        turn_id="turn_phase",
        entry_agent_id=entry_agent_id,
    )


def _artifact(artifact_id: str, title: str) -> SessionArtifact:
    now = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    return SessionArtifact(
        artifact_id=artifact_id,
        session_id="sess_phase",
        kind="uploaded_file",
        title=title,
        media_type="text/markdown",
        size_bytes=128,
        status="ready",
        visibility="user_visible",
        created_at=now,
        updated_at=now,
        storage_relpath=f"artifacts/{artifact_id}/original.bin",
        text_relpath=f"artifacts/{artifact_id}/content.txt",
    )


def test_phase_snapshot_skips_plain_chat_without_refs() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message="你好",
        workflow_state=CurrentWorkflowState(),
        career_flow_state=CareerFlowState(),
        active_artifacts=[],
    )

    assert snapshot.is_empty()


def test_phase_snapshot_identifies_resume_diagnosis_missing_outputs() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message="请诊断这份简历，并生成简历画像。",
        workflow_state=CurrentWorkflowState(),
        career_flow_state=CareerFlowState(),
        active_artifacts=[_artifact("artifact_resume", "张明简历.md")],
    )
    lines = format_workflow_phase_lines(snapshot)

    assert snapshot.phase_name == "resume_diagnosis"
    assert snapshot.confidence == "medium"
    assert [item.name for item in snapshot.missing_outputs] == [
        "resume_profile",
        "diagnosis_artifact",
        "career_profile",
    ]
    assert "career_jd_analysis_save" in snapshot.blocked_tool_names
    assert any("- missing_outputs=resume_profile,diagnosis_artifact,career_profile" == line for line in lines)


def test_phase_snapshot_identifies_jd_fit_before_resume_version() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message="请分析 JD 并生成岗位匹配报告。",
        workflow_state=CurrentWorkflowState(
            refs={
                "resume_profile_id": "resume_profile_alpha",
                "career_profile_id": "career_profile_default",
                "jd_source_artifact_id": "artifact_jd",
            }
        ),
        career_flow_state=CareerFlowState(),
        active_artifacts=[_artifact("artifact_jd", "星河智能 JD.md")],
    )

    assert snapshot.phase_name == "jd_fit"
    assert [item.name for item in snapshot.missing_outputs] == [
        "jd_analysis",
        "job_fit_report",
        "career_application",
    ]
    assert snapshot.blocked_tool_names == ["career_resume_version_create"]
    assert snapshot.next_action_hint == "先基于 JD artifact 生成 JDAnalysis。"


def test_phase_snapshot_requires_application_merge_after_resume_version() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message="基于这个岗位生成一版定制简历。",
        workflow_state=CurrentWorkflowState(
            refs={
                "resume_profile_id": "resume_profile_alpha",
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
                "application_id": "application_alpha",
            }
        ),
        career_flow_state=CareerFlowState(
            multi_refs={"resume_version_ids": ["resume_version_alpha"]},
            final_answer_ready=False,
        ),
        active_artifacts=[],
    )

    assert snapshot.phase_name == "resume_version"
    assert [item.name for item in snapshot.missing_outputs] == ["career_application_resume_version_link"]
    assert snapshot.next_action_hint == "ResumeVersion 已生成，下一步只需把 resume_version_id merge 回 CareerApplication。"


def test_phase_snapshot_keeps_resume_version_when_generation_mentions_application() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message=(
            "请基于刚才已经保存的 ResumeProfile、JDAnalysis 和 JobFitReport，生成一版 markdown 定制简历，"
            "保存 ResumeVersion 后，请调用 career_application_merge 把 resume_version_id 合并进当前求职项目。"
        ),
        workflow_state=CurrentWorkflowState(
            refs={
                "application_id": "application_alpha",
                "resume_profile_id": "resume_profile_alpha",
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
            }
        ),
        career_flow_state=CareerFlowState(),
        active_artifacts=[],
    )

    assert snapshot.phase_name == "resume_version"
    assert [item.name for item in snapshot.missing_outputs] == [
        "resume_version",
        "career_application_resume_version_link",
    ]
    assert snapshot.next_action_hint == "先生成 ResumeVersion；生成后必须 merge 回 CareerApplication。"


def test_phase_snapshot_requires_application_read_for_project_resume_version() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message=(
            "当前求职项目 application_id 是 application_alpha。请先调用 career_application_get 读取项目，"
            "再复用其中已有的 resume_profile_id、career_profile_id、jd_analysis_id、job_fit_report_id "
            "和 resume_version_ids。请生成或更新一版定制简历。必须调用 career_resume_version_create "
            "保存 ResumeVersion，再调用 career_application_merge 把新的 resume_version_id 合并进当前求职项目。"
        ),
        workflow_state=CurrentWorkflowState(
            refs={
                "application_id": "application_alpha",
                "resume_profile_id": "resume_profile_alpha",
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
            }
        ),
        career_flow_state=CareerFlowState(),
        active_artifacts=[],
    )

    assert snapshot.phase_name == "resume_version"
    assert [item.name for item in snapshot.missing_outputs] == [
        "career_application_read",
        "resume_version",
        "career_application_resume_version_link",
    ]
    assert snapshot.blocked_tool_names == ["career_resume_version_create"]
    assert snapshot.next_action_hint == (
        "先调用 career_application_get 读取当前 CareerApplication，再基于其关联记录生成 ResumeVersion。"
    )


def test_phase_snapshot_prioritizes_project_action_over_resume_version_status() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message=(
            "当前求职项目 application_id 是 application_alpha。请先调用 career_application_get 读取项目，"
            "再复用其中已有的 resume_profile_id、career_profile_id、jd_analysis_id、job_fit_report_id "
            "和 resume_version_ids。请执行投递前检查，检查定制简历状态。"
        ),
        workflow_state=CurrentWorkflowState(
            refs={
                "application_id": "application_alpha",
                "resume_profile_id": "resume_profile_alpha",
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
            }
        ),
        career_flow_state=CareerFlowState(
            multi_refs={"resume_version_ids": ["resume_version_alpha"]},
            final_answer_ready=False,
        ),
        active_artifacts=[],
    )

    assert snapshot.phase_name == "application_action"
    assert [item.name for item in snapshot.required_outputs] == ["career_application"]
    assert snapshot.missing_outputs == []
    assert snapshot.next_action_hint == "围绕已确认的 CareerApplication 执行用户指定动作。"


def test_phase_snapshot_ignores_child_agent_context() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(agent_id="resume_agent", entry_agent_id="agent_main"),
        user_message="解析简历",
        workflow_state=CurrentWorkflowState(refs={"resume_profile_id": "resume_profile_alpha"}),
        career_flow_state=CareerFlowState(),
        active_artifacts=[],
    )

    assert snapshot.is_empty()
