"""Tests for model-visible tool-result compaction."""

from __future__ import annotations

import json

from app.runtime.agent.tool_result_view import compact_tool_result_for_model

__all__ = []


def test_retrieval_context_pack_model_view_keeps_refs_and_drops_full_grouped_context() -> None:
    payload = {
        "query": "星河智能 RAG 二面准备",
        "session_id": "sess_alpha",
        "count": 2,
        "context_char_count": 42000,
        "max_chars": 50000,
        "omitted_count": 1,
        "group_counts": {"career": 1, "knowledge": 1},
        "context_pack": {
            "query": "星河智能 RAG 二面准备",
            "hits": [
                {
                    "source": {
                        "source_type": "job_fit_report",
                        "source_id": "fit_alpha_001",
                        "source_session_id": "sess_alpha",
                        "artifact_id": "artifact_fit_report",
                    },
                    "title": "星河智能匹配报告",
                    "summary": "候选人与岗位在后端能力上高度匹配。",
                    "snippet": "核心短板是 RAG 深度实践和 LangGraph 框架经验。",
                    "tags": ["RAG", "后端"],
                    "score": 0.91,
                    "match_reason": "命中公司、岗位和 RAG 关键词。",
                    "evidence_refs": ["artifact_fit_report", "jd_alpha_001"],
                    "updated_at": "2026-05-10T12:00:00+08:00",
                }
            ],
            "grouped_context": {
                "career": [
                    {
                        "title": "不应进入模型压缩视图",
                        "snippet": "FULL_GROUPED_CONTEXT_MARKER" * 500,
                    }
                ]
            },
            "citations": [
                {
                    "source_type": "job_fit_report",
                    "source_id": "fit_alpha_001",
                    "source_session_id": "sess_alpha",
                    "artifact_id": "artifact_fit_report",
                }
            ],
            "omitted": [{"snippet": "OMITTED_CONTEXT_MARKER" * 200}],
            "omitted_count": 1,
            "context_char_count": 42000,
        },
    }

    compact = compact_tool_result_for_model(
        tool_name="retrieval_context_pack",
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
    )
    compact_payload = json.loads(compact)

    assert compact_payload["model_view"] == "compact"
    assert compact_payload["top_hits"][0]["source"]["source_id"] == "fit_alpha_001"
    assert compact_payload["top_hits"][0]["source"]["artifact_id"] == "artifact_fit_report"
    assert "grouped_context" not in compact_payload
    assert "FULL_GROUPED_CONTEXT_MARKER" not in compact
    assert "OMITTED_CONTEXT_MARKER" not in compact
    assert len(compact) < 1800


def test_delegate_agents_model_view_keeps_task_summaries_and_artifacts() -> None:
    long_answer = "子 agent 完整回答。" * 500
    payload = {
        "task_group_id": "task_group_alpha",
        "status": "completed",
        "max_concurrency": 2,
        "results": [
            {
                "task_id": "task_alpha_001",
                "target_agent_id": "resume_agent",
                "status": "completed",
                "summary": "已完成简历画像和诊断。",
                "answer": long_answer,
                "child_run_id": "run_child_001",
                "artifact_refs": ["artifact_resume_diagnosis"],
            }
        ],
    }

    compact = compact_tool_result_for_model(
        tool_name="delegate_agents",
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
    )
    compact_payload = json.loads(compact)

    assert compact_payload["task_group_id"] == "task_group_alpha"
    assert compact_payload["results"][0]["target_agent_id"] == "resume_agent"
    assert compact_payload["results"][0]["artifact_refs"] == ["artifact_resume_diagnosis"]
    assert "子 agent 完整回答。" * 80 not in compact
    assert len(compact_payload["results"][0]["answer_preview"]) < len(long_answer)


def test_product_list_model_view_keeps_actionable_record_fields() -> None:
    payload = {
        "record_type": "career_application",
        "records": [
            {
                "status": "active",
                "source_session_id": "sess_alpha",
                "source_artifact_id": "artifact_jd_alpha",
                "evidence_refs": ["artifact_jd_alpha", "resume_profile_alpha", "fit_alpha"],
                "created_at": "2026-05-18T10:00:00+08:00",
                "updated_at": "2026-05-18T10:10:00+08:00",
                "application_id": "application_alpha",
                "company": "星河智能",
                "position": "AI Agent 后端工程师",
                "resume_profile_id": "resume_profile_alpha",
                "career_profile_id": "career_profile_default",
                "jd_analysis_id": "jd_alpha",
                "job_fit_report_id": "fit_alpha",
                "resume_version_ids": [],
                "summary": "匹配度中等偏上，需要补齐 RAG 深度证据。",
                "next_actions": ["生成定制简历版本"],
                "risks": ["RAG 项目证据不足"],
                "notes": "当前求职项目。" * 900,
            }
        ],
    }

    compact = compact_tool_result_for_model(
        tool_name="career_application_list",
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
    )
    compact_payload = json.loads(compact)
    record = compact_payload["records"][0]

    assert compact_payload["model_view"] == "compact"
    assert record["application_id"] == "application_alpha"
    assert record["resume_profile_id"] == "resume_profile_alpha"
    assert record["jd_analysis_id"] == "jd_alpha"
    assert record["job_fit_report_id"] == "fit_alpha"
    assert record["summary"].startswith("匹配度")


def test_product_get_model_view_keeps_nested_record_fields() -> None:
    payload = {
        "record_type": "job_fit_report",
        "record_id": "fit_alpha",
        "found": True,
        "status": "active",
        "source_artifact_id": "artifact_jd_alpha",
        "evidence_refs": ["resume_profile_alpha", "jd_alpha", "artifact_report_alpha"],
        "record": {
            "status": "active",
            "source_artifact_id": "artifact_jd_alpha",
            "evidence_refs": ["resume_profile_alpha", "jd_alpha", "artifact_report_alpha"],
            "updated_at": "2026-05-18T10:10:00+08:00",
            "job_fit_report_id": "fit_alpha",
            "jd_analysis_id": "jd_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "overall_score": 72,
            "score_breakdown": {"技术栈": 85, "RAG": 42},
            "recommendation": "cautious",
            "matched_evidence": [{"title": "Python/FastAPI 匹配", "detail": "已有项目经验"}],
            "gaps": [{"title": "RAG 深度不足", "detail": "缺少完整项目证据"}],
            "resume_optimization_direction": ["突出 Agent Runtime 项目"],
            "interview_preparation_focus": ["补齐 RAG 分块策略"],
            "report_artifact_id": "artifact_report_alpha",
            "large_debug_field": "不应因为大字段丢失核心记录字段。" * 900,
        },
    }

    compact = compact_tool_result_for_model(
        tool_name="career_job_fit_report_get",
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
    )
    compact_payload = json.loads(compact)
    record = compact_payload["record"]

    assert compact_payload["ids"]["record_id"] == "fit_alpha"
    assert record["job_fit_report_id"] == "fit_alpha"
    assert record["resume_profile_id"] == "resume_profile_alpha"
    assert record["overall_score"] == 72
    assert record["report_artifact_id"] == "artifact_report_alpha"


def test_small_tool_result_passes_through_unchanged() -> None:
    content = '{"ok": true, "id": "artifact_small"}'

    assert (
        compact_tool_result_for_model(tool_name="session_read_artifact", success=True, content=content)
        == content
    )
