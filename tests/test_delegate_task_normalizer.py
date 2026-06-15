"""Tests for delegate_agents argument normalization."""

from __future__ import annotations

from typing import Any

from app.runtime.workflow.delegation import (
    delegate_jd_fit_source_key,
    delegate_semantic_signature,
    delegate_signature,
    is_dependent_application_delegate_task,
    is_jd_fit_delegate_task,
    mentions_application_record,
    normalize_delegate_agents_arguments,
)


def test_delegate_normalizer_keeps_valid_task_and_drops_malformed_sibling() -> None:
    decision = normalize_delegate_agents_arguments(
        {
            "tasks": [
                {
                    "instruction": "基于 artifact_jd_live_001 完成 JDAnalysis 和 JobFitReport。",
                    "max_tool_rounds": 24,
                },
                {
                    "target_agent_id": "job_agent",
                    "instruction": "基于 artifact_jd_live_001 完成岗位匹配报告，并保存 JobFitReport。",
                    "artifact_refs": ["artifact_jd_live_001"],
                    "max_tool_rounds": 24,
                },
            ],
            "max_concurrency": 3,
        },
        phase="jd_fit",
    )

    assert decision.status == "normalized"
    assert decision.errors == [
        {"field": "delegate_agents.tasks[0].target_agent_id", "reason": "missing_target_agent_id"}
    ]
    assert len(decision.arguments["tasks"]) == 1
    assert decision.arguments["tasks"][0]["target_agent_id"] == "job_agent"
    assert decision.arguments["tasks"][0]["artifact_refs"] == ["artifact_jd_live_001"]
    assert decision.repair_actions[0]["reason"] == "delegate_task_schema_normalized"


def test_delegate_normalizer_rejects_when_no_executable_task_remains() -> None:
    decision = normalize_delegate_agents_arguments(
        {"tasks": [{"instruction": "创建 CareerApplication 求职项目。"}]},
        phase="jd_fit",
    )

    assert decision.rejected is True
    assert decision.reason == "delegate_tasks_invalid"
    assert decision.errors == [
        {"field": "delegate_agents.tasks[0].target_agent_id", "reason": "missing_target_agent_id"}
    ]


def test_delegate_normalizer_infers_artifact_refs_from_instruction() -> None:
    decision = normalize_delegate_agents_arguments(
        {
            "tasks": [
                {
                    "target_agent_id": "job_agent",
                    "instruction": "读取 artifact_jd_live_001 后保存岗位匹配报告。",
                }
            ]
        },
        phase="jd_fit",
    )

    assert decision.status == "normalized"
    assert decision.arguments["tasks"][0]["artifact_refs"] == ["artifact_jd_live_001"]


def test_delegate_normalizer_removes_placeholder_artifact_refs_when_valid_ids_are_known() -> None:
    decision = normalize_delegate_agents_arguments(
        {
            "tasks": [
                {
                    "target_agent_id": "job_agent",
                    "instruction": "基于 artifact_jd_live_001 完成岗位匹配报告。",
                    "artifact_refs": ["artifact_jd_live_001", "artifact_id", "artifact_refs"],
                }
            ]
        },
        phase="jd_fit",
        valid_artifact_ids=("artifact_jd_live_001",),
    )

    assert decision.status == "normalized"
    assert decision.arguments["tasks"][0]["artifact_refs"] == ["artifact_jd_live_001"]


def test_delegate_normalizer_dedupes_same_jd_fit_source() -> None:
    decision = normalize_delegate_agents_arguments(
        {
            "tasks": [
                {
                    "target_agent_id": "job_agent",
                    "instruction": "分析 artifact_jd_live_001，生成岗位匹配报告。",
                    "artifact_refs": ["artifact_jd_live_001"],
                },
                {
                    "target_agent_id": "job_agent",
                    "instruction": "读取 artifact_jd_live_001 后保存 JobFitReport。",
                    "artifact_refs": ["artifact_jd_live_001"],
                },
            ]
        },
        phase="jd_fit",
    )

    assert len(decision.arguments["tasks"]) == 1
    assert any(item["reason"] == "delegate_task_normalizer_deduped_tasks" for item in decision.repair_actions)


def test_delegate_normalizer_rejects_unknown_target_agent() -> None:
    decision = normalize_delegate_agents_arguments(
        {
            "tasks": [
                {
                    "target_agent_id": "research_agent",
                    "instruction": "检索资料。",
                }
            ]
        },
        phase=None,
        available_agent_ids=("resume_agent", "job_agent"),
    )

    assert decision.rejected is True
    assert decision.errors == [
        {"field": "delegate_agents.tasks[0].target_agent_id", "reason": "unknown_target_agent_id"}
    ]


def test_delegate_signature_uses_target_agent_and_artifacts() -> None:
    assert (
        delegate_signature(
            {
                "tasks": [
                    {
                        "target_agent_id": "job_agent",
                        "instruction": "分析 JD。",
                        "artifact_refs": ["artifact_jd_b", "artifact_jd_a"],
                    }
                ]
            }
        )
        == "job_agent:artifact_jd_a,artifact_jd_b"
    )


def test_delegate_semantic_signature_tracks_phase_sources_and_outputs() -> None:
    signature = delegate_semantic_signature(
        {
            "tasks": [
                {
                    "target_agent_id": "job_agent",
                    "instruction": "请基于 artifact_jd_live_001 分析 JD，调用 career_jd_analysis_save 和 career_job_fit_report_save。",
                    "artifact_refs": ["artifact_jd_live_001", "jd_live_001"],
                }
            ]
        }
    )

    assert (
        signature
        == "job_agent:jd_fit:artifacts=artifact_jd_live_001:products=jd_live_001:outputs=jd_analysis,job_fit_report"
    )


def test_delegate_jd_fit_helpers_identify_source_and_application_boundary() -> None:
    task: dict[str, Any] = {
        "target_agent_id": "job_agent",
        "instruction": "基于 jd_live_001 生成岗位匹配报告。",
        "artifact_refs": ["jd_live_001"],
    }

    assert is_jd_fit_delegate_task(task, task["instruction"]) is True
    assert delegate_jd_fit_source_key(task, task["instruction"]) == "jd_record:jd_live_001"
    assert mentions_application_record("请创建 CareerApplication 求职项目。") is True
    assert is_dependent_application_delegate_task("请创建 CareerApplication 求职项目。") is True
    assert is_dependent_application_delegate_task("请创建 CareerApplication 并保存 JobFitReport。") is False
