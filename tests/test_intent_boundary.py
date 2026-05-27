"""Tests for current-turn intent boundary parsing."""

from __future__ import annotations

from app.runtime.workflow.intent_boundary import build_turn_intent_boundary

__all__ = []


def test_boundary_keeps_explicit_read_only_retrieval() -> None:
    boundary = build_turn_intent_boundary("本轮只读，根据之前保存的记录召回相关上下文，不要保存或创建新记录。")

    assert boundary.read_only is True
    assert boundary.forbid_jd_fit is True
    assert boundary.forbid_career_application_create is True


def test_boundary_does_not_make_child_jd_fit_task_read_only_for_local_artifact_constraint() -> None:
    boundary = build_turn_intent_boundary(
        "请基于 JD artifact 完成岗位分析和匹配报告。必须使用以下已有记录 id："
        "resume_profile_id=resume_profile_alpha。不要重新创建 JD artifact，不要猜测 artifact_id。"
        "必须调用 career_jd_analysis_save 保存 JDAnalysis，并调用 career_job_fit_report_save 保存 JobFitReport。"
    )

    assert boundary.read_only is False
    assert boundary.forbid_jd_fit is False


def test_boundary_keeps_negative_resume_version_when_no_write_goal() -> None:
    boundary = build_turn_intent_boundary("请总结已有匹配报告，不要生成定制简历，也不要创建简历版本。")

    assert boundary.read_only is False
    assert boundary.forbid_resume_version_create is True


def test_boundary_detects_negative_resume_version_with_shared_verb() -> None:
    boundary = build_turn_intent_boundary(
        "请保存面试复盘并更新当前求职项目，不要重新生成匹配报告或简历版本。"
    )

    assert boundary.read_only is False
    assert boundary.forbid_resume_version_create is True
    assert boundary.forbid_career_application_merge is False


def test_boundary_does_not_cross_non_resume_negative_into_positive_resume_goal() -> None:
    boundary = build_turn_intent_boundary(
        "当前求职项目 application_id 是 application_alpha。请先调用 career_application_get 读取项目，"
        "再复用其中已有的 resume_profile_id、career_profile_id、jd_analysis_id、job_fit_report_id "
        "和 resume_version_ids。不要重新解析简历，不要重新分析 JD，不要重新创建 ResumeProfile、"
        "JDAnalysis 或 JobFitReport。请生成或更新一版定制简历。必须调用 career_resume_version_create "
        "保存 ResumeVersion，再调用 career_application_merge 把新的 resume_version_id 合并进当前求职项目。"
    )

    assert boundary.forbid_resume_version_create is False


def test_boundary_does_not_mark_retrieval_learning_action_read_only() -> None:
    boundary = build_turn_intent_boundary(
        "请不要让我提供任何产品记录 id。你需要先根据历史求职资产自动召回相关上下文："
        "先用 retrieval_search 定位相关求职项目，再用 retrieval_context_pack 读取项目、匹配报告。"
        "创建任务、保存笔记或更新项目之前必须读取 context pack。不要使用 workspace path，不要写 memory。"
        "请根据之前的匹配短板，给我创建一个今天要完成的学习任务，并加入学习监督。"
        "这轮只写 LearningPlan 或 LearningTask；不要调用 career_application_merge，不要更新求职项目。"
    )

    assert boundary.read_only is False
    assert boundary.forbid_career_application_merge is True


def test_boundary_keeps_retrieval_advice_only_read_only_with_generic_prefix() -> None:
    boundary = build_turn_intent_boundary(
        "请不要让我提供任何产品记录 id。你需要先根据历史求职资产自动召回相关上下文："
        "先用 retrieval_search 定位相关求职项目，再用 retrieval_context_pack 读取项目、匹配报告。"
        "创建任务、保存笔记或更新项目之前必须读取 context pack。不要使用 workspace path，不要写 memory。"
        "请帮我准备之前那个 AI 应用开发岗位的面试。这轮只给准备建议，不要保存笔记、不要创建学习任务、不要更新求职项目。"
    )

    assert boundary.read_only is True
