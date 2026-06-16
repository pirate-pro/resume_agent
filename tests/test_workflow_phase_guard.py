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


def test_phase_snapshot_skips_explanatory_rag_chat_with_no_tool_boundary() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message="用两句话解释 RAG 和普通关键词搜索的区别。不要保存任何内容，也不要调用工具。",
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


def test_phase_snapshot_keeps_resume_version_when_negative_refs_then_positive_resume_goal() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message=(
            "当前求职项目 application_id 是 application_alpha。请先调用 career_application_get 读取项目，"
            "再复用其中已有的 resume_profile_id、career_profile_id、jd_analysis_id、job_fit_report_id "
            "和 resume_version_ids。不要重新解析简历，不要重新分析 JD，不要重新创建 ResumeProfile、"
            "JDAnalysis 或 JobFitReport。请生成或更新一版定制简历。必须调用 career_resume_version_create "
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


def test_phase_snapshot_reads_application_id_from_current_message() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message=(
            "当前求职项目 application_id 是 application_alpha。请先调用 career_application_get 读取项目，"
            "再基于项目内已有资料生成一版定制简历。"
        ),
        workflow_state=CurrentWorkflowState(),
        career_flow_state=CareerFlowState(),
        active_artifacts=[],
    )

    assert snapshot.phase_name == "resume_version"
    completed = {item.name: item.ref_value for item in snapshot.completed_outputs}
    assert completed["career_application"] == "application_alpha"
    assert [item.name for item in snapshot.missing_outputs] == [
        "resume_profile",
        "jd_analysis",
        "job_fit_report",
        "career_application_read",
        "resume_version",
        "career_application_resume_version_link",
    ]


def test_phase_snapshot_direct_note_write_does_not_require_retrieval() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message=(
            "请把下面内容保存为一条可编辑笔记，标题叫 RAG 面试准备摘记："
            "RAG 面试要重点准备 chunk 策略、召回评估、失败恢复和 Agent 工具权限边界。"
            "这不是长期偏好，不要写 memory。"
        ),
        workflow_state=CurrentWorkflowState(),
        career_flow_state=CareerFlowState(),
        active_artifacts=[],
    )

    assert snapshot.phase_name == "note_write"
    assert [item.name for item in snapshot.missing_outputs] == ["note"]
    assert "memory_write" in snapshot.blocked_tool_names
    assert "retrieval_search" in snapshot.blocked_tool_names


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


def test_phase_snapshot_read_only_interview_prep_uses_retrieval_boundary() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message=(
            "根据之前保存的岗位资料，帮我准备二面。请先召回相关上下文再回答；"
            "这轮只读，不要保存笔记、不要写 memory、不要创建学习任务。"
        ),
        workflow_state=CurrentWorkflowState(refs={"application_id": "application_alpha"}),
        career_flow_state=CareerFlowState(),
        active_artifacts=[],
    )

    assert snapshot.phase_name == "retrieval_read_only"
    assert [item.name for item in snapshot.missing_outputs] == [
        "retrieval_search",
        "retrieval_context_pack",
    ]
    assert "career_application_merge" in snapshot.blocked_tool_names
    assert snapshot.allowed_tool_groups == ["retrieval"]


def test_phase_snapshot_save_note_uses_rag_note_action_contract() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message="把之前星河智能二面准备内容保存为笔记。",
        workflow_state=CurrentWorkflowState(refs={"application_id": "application_alpha"}),
        career_flow_state=CareerFlowState(),
        active_artifacts=[],
    )

    assert snapshot.phase_name == "rag_note_write"
    assert [item.name for item in snapshot.missing_outputs] == [
        "retrieval_search",
        "retrieval_context_pack",
        "note",
    ]
    assert "career_application_merge" in snapshot.blocked_tool_names
    assert snapshot.allowed_tool_groups == ["retrieval", "notes"]


def test_phase_snapshot_learning_task_uses_rag_learning_action_contract() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message="根据之前短板给我今天学习任务，并加入计划监督我完成。",
        workflow_state=CurrentWorkflowState(refs={"application_id": "application_alpha"}),
        career_flow_state=CareerFlowState(),
        active_artifacts=[],
    )

    assert snapshot.phase_name == "rag_learning_task_create"
    assert [item.name for item in snapshot.missing_outputs] == [
        "retrieval_search",
        "retrieval_context_pack",
        "learning_task",
    ]
    assert "career_application_merge" in snapshot.blocked_tool_names
    assert snapshot.allowed_tool_groups == ["retrieval", "learning"]


def test_phase_snapshot_interview_review_requires_note_and_application_update() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message="我刚面完星河智能一面，帮我记录复盘并更新项目，先不要建学习任务。",
        workflow_state=CurrentWorkflowState(refs={"application_id": "application_alpha"}),
        career_flow_state=CareerFlowState(),
        active_artifacts=[],
    )

    assert snapshot.phase_name == "interview_review_update"
    assert [item.name for item in snapshot.missing_outputs] == [
        "retrieval_search",
        "retrieval_context_pack",
        "note",
        "career_application_update",
    ]
    assert "learning_task_create" in snapshot.blocked_tool_names
    assert snapshot.allowed_tool_groups == ["retrieval", "notes", "career_application"]


def test_phase_snapshot_retrieval_learning_prompt_ignores_control_prefix() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message=(
            "请不要让我提供任何产品记录 id。你需要先根据历史求职资产自动召回相关上下文："
            "先用 retrieval_search 定位相关求职项目，再用 retrieval_context_pack 读取项目、匹配报告。"
            "创建任务、保存笔记或更新项目之前必须读取 context pack。不要使用 workspace path，不要写 memory。"
            "请根据之前的匹配短板，给我创建一个今天要完成的学习任务，并加入学习监督。"
            "这轮只写 LearningPlan 或 LearningTask；不要调用 career_application_merge，不要更新求职项目。"
        ),
        workflow_state=CurrentWorkflowState(refs={"application_id": "application_alpha"}),
        career_flow_state=CareerFlowState(),
        active_artifacts=[],
    )

    assert snapshot.phase_name == "rag_learning_task_create"
    assert [item.name for item in snapshot.missing_outputs] == [
        "retrieval_search",
        "retrieval_context_pack",
        "learning_task",
    ]
    assert "career_application_merge" in snapshot.blocked_tool_names


def test_phase_snapshot_retrieval_save_note_prompt_does_not_become_review_update() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message=(
            "请不要让我提供任何产品记录 id。你需要先根据历史求职资产自动召回相关上下文："
            "先用 retrieval_search 定位相关求职项目，再用 retrieval_context_pack 读取项目、匹配报告。"
            "创建任务、保存笔记或更新项目之前必须读取 context pack。不要使用 workspace path，不要写 memory。"
            "请把这次面试准备内容保存为一条可编辑笔记。先召回依据，再调用 note_create。"
        ),
        workflow_state=CurrentWorkflowState(refs={"application_id": "application_alpha"}),
        career_flow_state=CareerFlowState(),
        active_artifacts=[],
    )

    assert snapshot.phase_name == "rag_note_write"
    assert [item.name for item in snapshot.missing_outputs] == [
        "retrieval_search",
        "retrieval_context_pack",
        "note",
    ]
    assert "career_application_merge" in snapshot.blocked_tool_names


def test_phase_snapshot_retrieval_interview_review_prompt_uses_review_contract() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message=(
            "请不要让我提供任何产品记录 id。你需要先根据历史求职资产自动召回相关上下文："
            "先用 retrieval_search 定位相关求职项目，再用 retrieval_context_pack 读取项目、匹配报告。"
            "创建任务、保存笔记或更新项目之前必须读取 context pack。不要使用 workspace path，不要写 memory。"
            "我刚面完之前那个 AI 应用开发岗位的一面，被问到 RAG chunk 策略。"
            "请把这次面试复盘保存成一条 Note，并更新当前求职项目的阶段、风险、下一步行动和项目备注。"
            "不要创建学习计划或学习任务，不要重新委派 child-agent。"
        ),
        workflow_state=CurrentWorkflowState(refs={"application_id": "application_alpha"}),
        career_flow_state=CareerFlowState(),
        active_artifacts=[],
    )

    assert snapshot.phase_name == "interview_review_update"
    assert [item.name for item in snapshot.missing_outputs] == [
        "retrieval_search",
        "retrieval_context_pack",
        "note",
        "career_application_update",
    ]
    assert "learning_task_create" in snapshot.blocked_tool_names


def test_phase_snapshot_negative_resume_version_keeps_resume_diagnosis() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message=(
            "请委派 resume_agent 读取这份简历，生成诊断 artifact，并保存结构化 ResumeProfile。"
            "这轮不要分析 JD，不要创建求职项目，不要生成定制简历。"
        ),
        workflow_state=CurrentWorkflowState(),
        career_flow_state=CareerFlowState(),
        active_artifacts=[_artifact("artifact_resume", "候选人简历.md")],
    )

    assert snapshot.phase_name == "resume_diagnosis"
    assert [item.name for item in snapshot.missing_outputs] == [
        "resume_profile",
        "diagnosis_artifact",
        "career_profile",
    ]


def test_phase_snapshot_jd_fit_can_forbid_application_output() -> None:
    snapshot = build_career_phase_snapshot(
        context=_context(),
        user_message=(
            "请委派 job_agent 基于这个 JD 和已有画像生成 JDAnalysis 与 JobFitReport。"
            "这轮不要创建 CareerApplication，不要生成 ResumeVersion。"
        ),
        workflow_state=CurrentWorkflowState(
            refs={
                "resume_profile_id": "resume_profile_alpha",
                "career_profile_id": "career_profile_default",
                "jd_source_artifact_id": "artifact_jd",
            }
        ),
        career_flow_state=CareerFlowState(),
        active_artifacts=[_artifact("artifact_jd", "目标岗位 JD.md")],
    )

    assert snapshot.phase_name == "jd_fit"
    assert [item.name for item in snapshot.missing_outputs] == ["jd_analysis", "job_fit_report"]
    assert "career_application" not in [item.name for item in snapshot.required_outputs]
