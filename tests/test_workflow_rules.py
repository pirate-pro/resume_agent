"""Tests for workflow rule pack selection."""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import SessionArtifact
from app.runtime.context.models import ContextAssemblyRole
from app.runtime.context.workflow_rules import (
    normalize_workflow_rule_selection_mode,
    select_full_workflow_skill_names,
    select_sparse_workflow_rule_packs,
)

__all__ = []


def test_sparse_rules_keep_plain_chat_small() -> None:
    packs = select_sparse_workflow_rule_packs(
        role=ContextAssemblyRole.MAIN_AGENT,
        user_message="你好",
        active_artifacts=[],
    )

    assert [pack.name for pack in packs] == ["always_on"]


def test_sparse_rules_select_job_fit_and_delegation() -> None:
    packs = select_sparse_workflow_rule_packs(
        role=ContextAssemblyRole.MAIN_AGENT,
        user_message="请基于这份简历和 JD 生成匹配报告。",
        active_artifacts=[
            _artifact("artifact_resume", "张明简历.pdf", "application/pdf"),
            _artifact("artifact_jd", "后端工程师 JD.txt", "text/plain"),
        ],
    )

    assert [pack.name for pack in packs] == [
        "always_on",
        "career_resume_diagnosis",
        "career_jd_analysis",
        "career_job_fit",
        "delegate_agents",
    ]


def test_sparse_rules_select_retrieval_and_learning_for_previous_job() -> None:
    packs = select_sparse_workflow_rule_packs(
        role=ContextAssemblyRole.MAIN_AGENT,
        user_message="之前那个星河智能岗位下一步怎么准备，帮我加入学习任务。",
        active_artifacts=[],
    )

    assert [pack.name for pack in packs] == [
        "always_on",
        "retrieval_required",
        "learning_task_create",
    ]


def test_full_rules_preserve_coarse_skill_selection() -> None:
    skill_names = select_full_workflow_skill_names(
        role=ContextAssemblyRole.MAIN_AGENT,
        user_message="把这次面试复盘保存为笔记，并加入学习计划。",
        active_artifacts=[],
    )

    assert skill_names == [
        "retrieval-workflow",
        "retrieval-career-workflow",
        "note-workflow",
        "learning-workflow",
    ]


def test_workflow_rule_mode_validation() -> None:
    assert normalize_workflow_rule_selection_mode(" SPARSE ") == "sparse"
    assert normalize_workflow_rule_selection_mode("full") == "full"


def test_other_agent_gets_no_sparse_workflow_rules() -> None:
    assert (
        select_sparse_workflow_rule_packs(
            role=ContextAssemblyRole.OTHER_AGENT,
            user_message="请诊断简历",
            active_artifacts=[],
        )
        == []
    )


def _artifact(artifact_id: str, title: str, media_type: str) -> SessionArtifact:
    now = datetime.now(UTC)
    return SessionArtifact(
        artifact_id=artifact_id,
        session_id="sess_rules",
        kind="uploaded_file",
        title=title,
        media_type=media_type,
        size_bytes=10,
        status="ready",
        visibility="session_shared",
        created_at=now,
        updated_at=now,
        storage_relpath=f"artifacts/{artifact_id}/original.bin",
        text_relpath=f"artifacts/{artifact_id}/content.txt",
        error=None,
    )
