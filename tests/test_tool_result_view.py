"""Tests for model-visible tool-result compaction."""

from __future__ import annotations

import json

from app.runtime.agent.tool_result_view import compact_tool_result_for_model

__all__ = []


def test_tool_search_model_view_keeps_names_and_drops_descriptions() -> None:
    payload = {
        "query": "创建定制简历版本并更新求职项目",
        "matched_groups": ["career"],
        "reveal_packs": ["career"],
        "revealed_tool_count": 2,
        "revealed_tools": [
            {
                "name": "career_resume_version_create",
                "description": "LONG_DESCRIPTION_MARKER" * 200,
                "group": "career",
                "why": "需要处理简历版本。",
            },
            {
                "name": "career_application_merge",
                "description": "LONG_DESCRIPTION_MARKER" * 200,
                "group": "career",
                "why": "需要更新求职项目。",
            },
        ],
        "revealed_tool_names": ["career_resume_version_create", "career_application_merge"],
        "available_tool_count": 55,
        "routing_guidance": "请直接调用已揭示的工具，不要继续搜索。",
        "next_step": "下一轮直接调用工具。",
        "search_guidance": "不要重复搜索。",
    }

    compact = compact_tool_result_for_model(
        tool_name="tool_search",
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
    )
    compact_payload = json.loads(compact)

    assert compact_payload["model_view"] == "compact"
    assert compact_payload["revealed_tool_names"] == [
        "career_resume_version_create",
        "career_application_merge",
    ]
    assert compact_payload["routing_guidance"] == "请直接调用已揭示的工具，不要继续搜索。"
    assert "revealed_tools" not in compact_payload
    assert "LONG_DESCRIPTION_MARKER" not in compact
    assert len(compact) < 1000


def test_product_model_view_includes_completion_hint_for_resume_version() -> None:
    payload = {
        "record_type": "resume_version",
        "record_id": "resume_version_alpha",
        "record": {
            "resume_version_id": "resume_version_alpha",
            "artifact_id": "artifact_resume_alpha",
            "content": "简历正文" * 500,
        },
    }

    compact = compact_tool_result_for_model(
        tool_name="career_resume_version_create",
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
    )
    compact_payload = json.loads(compact)

    assert compact_payload["model_view"] == "compact"
    assert "不要再次创建 ResumeVersion" in compact_payload["completion_hint"]
    assert compact_payload["ids"]["resume_version_id"] == "resume_version_alpha"
    assert compact_payload["artifact_refs"]["artifact_id"] == "artifact_resume_alpha"
    assert "record" not in compact_payload
    assert "简历正文" not in compact


def test_product_write_model_view_keeps_actionable_ids_without_full_record() -> None:
    payload = {
        "record_type": "job_fit_report",
        "record_id": "fit_alpha",
        "status": "active",
        "record": {
            "job_fit_report_id": "fit_alpha",
            "jd_analysis_id": "jd_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "career_profile_id": "career_profile_default",
            "source_artifact_id": "artifact_jd_alpha",
            "report_artifact_id": "artifact_report_alpha",
            "overall_score": 72,
            "recommendation": "cautious",
            "matched_evidence": ["Python/FastAPI 与候选人项目经验匹配"],
            "gaps": ["RAG 深度实践证据不足"],
        },
    }

    compact = compact_tool_result_for_model(
        tool_name="career_job_fit_report_save",
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
    )
    compact_payload = json.loads(compact)

    assert compact_payload["model_view"] == "compact"
    assert compact_payload["ids"]["record_id"] == "fit_alpha"
    assert compact_payload["ids"]["job_fit_report_id"] == "fit_alpha"
    assert compact_payload["link_refs"]["jd_analysis_id"] == "jd_alpha"
    assert compact_payload["artifact_refs"]["report_artifact_id"] == "artifact_report_alpha"
    assert compact_payload["score"] == 72
    assert "resume_version_guidance" in compact_payload
    assert "缺失 JD 关键词只能放入 risk_notes" in compact_payload["resume_version_guidance"]["rule"]
    assert compact_payload["resume_version_guidance"]["supported_evidence_for_resume"] == [
        "Python/FastAPI 与候选人项目经验匹配"
    ]
    assert "record" not in compact_payload


def test_jd_analysis_save_model_view_guides_single_fit_report_artifact() -> None:
    payload = {
        "record_type": "jd_analysis",
        "record_id": "jd_alpha",
        "record": {
            "jd_analysis_id": "jd_alpha",
            "source_artifact_id": "artifact_jd_alpha",
            "company": "星河智能",
            "position": "AI Agent 后端工程师",
        },
    }

    compact = compact_tool_result_for_model(
        tool_name="career_jd_analysis_save",
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
    )
    compact_payload = json.loads(compact)

    guidance = compact_payload["job_fit_report_artifact_guidance"]
    assert compact_payload["model_view"] == "compact"
    assert "唯一岗位匹配报告 artifact" in compact_payload["completion_hint"]
    assert guidance["next_tool"] == "session_create_text_artifact"
    assert guidance["then_tool"] == "career_job_fit_report_save"
    assert "不要创建 JDAnalysis artifact" in guidance["artifact_rule"]
    assert any("MySQL" in rule for rule in guidance["candidate_fact_rules"])
    assert any("RAG 通常涉及向量检索" in rule for rule in guidance["candidate_fact_rules"])
    assert any("Docker/K8s" in rule for rule in guidance["candidate_fact_rules"])
    assert "record" not in compact_payload


def test_product_get_model_view_deduplicates_metadata_and_keeps_domain_fields() -> None:
    payload = {
        "record_type": "resume_profile",
        "record_id": "resume_profile_alpha",
        "found": True,
        "status": "active",
        "source_artifact_id": "artifact_resume_alpha",
        "evidence_refs": ["artifact_resume_alpha", "artifact_diagnosis_alpha"],
        "record": {
            "resume_profile_id": "resume_profile_alpha",
            "status": "active",
            "source_artifact_id": "artifact_resume_alpha",
            "raw_text_artifact_id": "artifact_resume_alpha",
            "diagnosis_artifact_id": "artifact_diagnosis_alpha",
            "evidence_refs": ["artifact_resume_alpha", "artifact_diagnosis_alpha"],
            "updated_at": "2026-05-20T12:00:00+08:00",
            "basic_info": {"name": "张三", "target_role": "AI 应用开发工程师"},
            "skills": ["Python", "FastAPI", "RAG", "Agent"],
            "diagnosis": {"summary": "FULL_DIAGNOSIS_MARKER" * 80},
        },
    }

    compact = compact_tool_result_for_model(
        tool_name="career_resume_profile_get",
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
    )
    compact_payload = json.loads(compact)

    assert compact_payload["model_view"] == "compact"
    assert compact_payload["ids"]["resume_profile_id"] == "resume_profile_alpha"
    assert compact_payload["artifact_refs"]["source_artifact_id"] == "artifact_resume_alpha"
    assert compact_payload["artifact_refs"]["diagnosis_artifact_id"] == "artifact_diagnosis_alpha"
    assert compact_payload["record"]["skills"] == ["Python", "FastAPI", "RAG", "Agent"]
    assert "status" not in compact_payload["record"]
    assert "evidence_refs" not in compact_payload["record"]
    assert "source_artifact_id" not in compact_payload["record"]
    assert "FULL_DIAGNOSIS_MARKER" not in compact


def test_career_profile_merge_compact_view_keeps_repaired_committed_record() -> None:
    payload = {
        "record_type": "career_profile",
        "record_id": "career_profile_default",
        "found": True,
        "status": "active",
        "evidence_refs": ["artifact_resume_alpha", "resume_profile_alpha"],
        "source_aligned": True,
        "source_alignment_repairs": [
            {
                "field": "updates",
                "from": ["unsupported_tech:cpp", "unsupported_tech:mysql"],
                "to": "source_aligned_updates",
                "reason": "source_drift_repaired",
            }
        ],
        "record": {
            "career_profile_id": "career_profile_default",
            "career_goal": "AI 应用开发 / 后端工程师",
            "target_roles": ["AI 应用开发", "后端工程师"],
            "skills": ["Python", "FastAPI", "PostgreSQL", "Redis", "RAG", "Agent 工具调用"],
            "strengths": ["技能覆盖：Python、FastAPI、PostgreSQL、Redis、RAG、Agent 工具调用"],
        },
    }

    compact = compact_tool_result_for_model(
        tool_name="career_profile_merge",
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
    )
    compact_payload = json.loads(compact)

    assert compact_payload["model_view"] == "compact"
    assert compact_payload["source_aligned"] is True
    assert compact_payload["source_alignment_repairs"][0]["reason"] == "source_drift_repaired"
    assert "committed record" in compact_payload["source_alignment_guidance"]
    assert compact_payload["record"]["career_goal"] == "AI 应用开发 / 后端工程师"
    assert compact_payload["record"]["target_roles"] == ["AI 应用开发", "后端工程师"]
    assert compact_payload["record"]["skills"] == [
        "Python",
        "FastAPI",
        "PostgreSQL",
        "Redis",
        "RAG",
        "Agent 工具调用",
    ]
    assert "C++" not in compact
    assert "MySQL" not in compact


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
                "summary": "已完成简历画像和诊断，resume_profile_id=resume_profile_alpha。",
                "answer": long_answer + " diagnosis artifact: artifact_resume_diagnosis",
                "child_run_id": "run_child_001",
                "artifact_refs": ["artifact_resume_diagnosis"],
                "output_artifact_refs": ["artifact_resume_diagnosis"],
                "product_refs": ["resume_profile_alpha"],
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
    assert compact_payload["results"][0]["output_artifact_refs"] == ["artifact_resume_diagnosis"]
    assert compact_payload["results"][0]["product_refs"] == ["resume_profile_alpha"]
    assert compact_payload["results"][0]["extracted_ids"] == [
        "resume_profile_alpha",
        "artifact_resume_diagnosis",
    ]
    assert compact_payload["results"][0]["followup_hints"] == [
        "Use returned product_refs/output_artifact_refs directly; do not list/get only to reconfirm completed child results.",
        "If product_refs includes a resume_profile_id, update career_profile_default with career_profile_merge before finalizing the resume diagnosis turn.",
        "If career tools are not visible yet, call tool_search for the career group first.",
    ]
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
    assert compact_payload["artifact_refs"]["report_artifact_id"] == "artifact_report_alpha"
    assert compact_payload["resume_version_guidance"]["supported_evidence_for_resume"][0]["title"] == (
        "Python/FastAPI 匹配"
    )
    assert compact_payload["resume_version_guidance"]["risk_note_candidates"][0]["title"] == "RAG 深度不足"
    assert "不能写成候选人已具备的简历事实" in compact_payload["resume_version_guidance"]["rule"]


def test_small_product_result_still_uses_compact_model_view() -> None:
    payload = {
        "record_type": "career_application",
        "record_id": "application_alpha",
        "found": True,
        "record": {
            "application_id": "application_alpha",
            "resume_profile_id": "resume_profile_alpha",
            "jd_analysis_id": "jd_alpha",
            "job_fit_report_id": "fit_alpha",
            "summary": "当前求职项目",
        },
    }

    compact = compact_tool_result_for_model(
        tool_name="career_application_get",
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
    )
    compact_payload = json.loads(compact)

    assert compact_payload["model_view"] == "compact"
    assert compact_payload["ids"]["record_id"] == "application_alpha"
    assert compact_payload["record"]["application_id"] == "application_alpha"
    assert compact_payload["record"]["job_fit_report_id"] == "fit_alpha"
    assert "full_result_hint" in compact_payload
    assert compact != json.dumps(payload, ensure_ascii=False)


def test_small_delegate_result_still_uses_compact_model_view() -> None:
    payload = {
        "task_group_id": "task_group_alpha",
        "status": "completed",
        "results": [
            {
                "task_id": "task_alpha",
                "target_agent_id": "job_agent",
                "status": "completed",
                "summary": "已保存 jd_analysis_id=jd_alpha 和 job_fit_report_id=fit_alpha。",
            }
        ],
    }

    compact = compact_tool_result_for_model(
        tool_name="delegate_agents",
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
    )
    compact_payload = json.loads(compact)

    assert compact_payload["model_view"] == "compact"
    assert compact_payload["results"][0]["target_agent_id"] == "job_agent"
    assert compact_payload["results"][0]["extracted_ids"] == ["jd_alpha", "fit_alpha"]
    assert "full_result_hint" in compact_payload


def test_strict_hidden_tool_result_compacts_model_view() -> None:
    payload = {
        "workflow_runtime_result": True,
        "event_type": "tool_schema_not_revealed",
        "policy": "block",
        "reason": "tool_hidden_by_runtime_plan",
        "strict_runtime_plan": True,
        "tool_name": "tool_search",
        "required_tool": "career_application_merge",
        "next_allowed_tools": ["career_application_merge"],
        "required_tools": ["career_application_merge"],
        "missing_outputs": ["career_application_resume_version_link"],
        "known_refs": {
            "application_id": "application_alpha",
            "resume_version_id": "resume_version_alpha",
        },
        "required_tool_call_hint": {
            "tool_name": "career_application_merge",
            "available_args": {"application_id": "application_alpha"},
            "missing_args": [],
        },
        "correction": "不要重试 tool_search；当前唯一允许的下一步工具是 career_application_merge。",
        "message": "当前 workflow 已锁定唯一下一步工具；不要继续调用隐藏工具，直接调用 required_tool。",
    }

    compact = compact_tool_result_for_model(
        tool_name="tool_search",
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
    )
    compact_payload = json.loads(compact)

    assert compact_payload["strict_runtime_plan"] is True
    assert compact_payload["required_tool"] == "career_application_merge"
    assert "known_refs" not in compact_payload
    assert compact_payload["required_tool_call_hint"]["tool_name"] == "career_application_merge"


def test_small_tool_result_passes_through_unchanged() -> None:
    content = '{"ok": true, "id": "artifact_small"}'

    assert (
        compact_tool_result_for_model(tool_name="session_read_artifact", success=True, content=content)
        == content
    )
