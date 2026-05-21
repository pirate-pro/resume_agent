"""Tests for deterministic tool catalog search."""

from __future__ import annotations

import json

from app.domain.models import RunContext, ToolDefinition
from app.runtime.tool_catalog import ToolCatalog
from app.tools.builtin_tools import ToolSearchTool

__all__ = []


def test_tool_catalog_reveals_retrieval_and_career_packs_for_previous_job_query() -> None:
    result = ToolCatalog(_definitions()).search(query="根据之前星河智能岗位准备二面", top_k=8)
    names = {entry.name for entry in result.revealed_tools}

    assert {"retrieval_search", "retrieval_context_pack"} <= names
    assert {"career_application_get", "career_application_merge"} <= names
    assert "session_read_artifact" not in names
    assert "tool_search" not in names
    assert "state_set" not in names


def test_tool_catalog_reveals_learning_and_retrieval_for_learning_task_query() -> None:
    result = ToolCatalog(_definitions()).search(query="根据之前短板创建学习任务并监督我完成", top_k=8)
    names = {entry.name for entry in result.revealed_tools}

    assert {"retrieval_search", "retrieval_context_pack"} <= names
    assert {"learning_task_create", "learning_task_update_state"} <= names
    assert "note_create" not in names


def test_tool_catalog_reveals_narrow_resume_version_pack() -> None:
    result = ToolCatalog(_definitions()).search(query="创建定制简历版本并更新求职项目", groups=["career"], top_k=8)
    names = {entry.name for entry in result.revealed_tools}

    assert {"career_resume_version_create", "career_resume_version_get", "career_application_merge"} <= names
    assert {"career_resume_profile_get", "career_jd_analysis_get", "career_job_fit_report_get"} <= names
    assert "career_resume_profile_save" not in names
    assert "career_jd_analysis_save" not in names
    assert "career_job_fit_report_save" not in names
    assert "career_resume_profile_list" not in names


def test_tool_catalog_artifact_read_does_not_reveal_career_read_pack() -> None:
    result = ToolCatalog(_definitions()).search(query="读取 session artifact 内容", top_k=8)
    names = {entry.name for entry in result.revealed_tools}

    assert result.matched_groups == ["artifact"]
    assert "session_read_artifact" in names
    assert "session_create_text_artifact" not in names
    assert "career_resume_profile_get" not in names
    assert "career_application_get" not in names


def test_tool_catalog_artifact_write_reveals_create_tool() -> None:
    result = ToolCatalog(_definitions()).search(query="创建 text artifact 保存报告", top_k=8)
    names = {entry.name for entry in result.revealed_tools}

    assert "artifact" in result.matched_groups
    assert "session_create_text_artifact" in names


def test_tool_catalog_delegation_query_does_not_reveal_career_read_by_id_word() -> None:
    result = ToolCatalog(_definitions()).search(query="child agent ids available", top_k=8)
    names = {entry.name for entry in result.revealed_tools}

    assert result.matched_groups == ["delegation"]
    assert {"delegate_agents", "agent_task_status"} <= names
    assert "career_application_get" not in names


def test_tool_catalog_career_profile_work_reveals_delegation() -> None:
    result = ToolCatalog(_definitions()).search(query="create or update career profile", top_k=8)
    names = {entry.name for entry in result.revealed_tools}

    assert "career_diagnosis" in result.matched_groups
    assert "delegation" in result.matched_groups
    assert {"career_profile_merge", "delegate_agents"} <= names


def test_tool_catalog_guides_delegation_when_jd_save_tools_are_unavailable() -> None:
    definitions = [
        definition
        for definition in _definitions()
        if definition.name not in {"career_jd_analysis_save", "career_job_fit_report_save"}
    ]

    result = ToolCatalog(definitions).search(query="save JD analysis and job fit report", top_k=8)
    payload = result.to_payload()

    assert "delegate_agents" in payload["revealed_tool_names"]
    assert "routing_guidance" in payload
    assert "委派 job_agent" in payload["routing_guidance"]
    assert "不要继续 tool_search" in payload["routing_guidance"]


def test_tool_catalog_reveals_jd_fit_without_resume_version_tools() -> None:
    result = ToolCatalog(_definitions()).search(query="分析 JD 并生成岗位匹配报告", groups=["career"], top_k=8)
    names = {entry.name for entry in result.revealed_tools}

    assert {"career_jd_analysis_save", "career_job_fit_report_save", "career_application_create"} <= names
    assert {"career_resume_profile_get", "career_profile_get"} <= names
    assert "career_resume_version_create" not in names


def test_tool_catalog_does_not_reveal_state_by_default() -> None:
    result = ToolCatalog(_definitions()).search(query="更新工作视图进度", top_k=8)

    assert "state" not in result.matched_groups
    assert all(entry.group != "state" for entry in result.revealed_tools)


def test_tool_catalog_can_reveal_state_when_group_is_explicit() -> None:
    result = ToolCatalog(_definitions()).search(query="更新工作视图进度", groups=["state"], top_k=8)
    names = {entry.name for entry in result.revealed_tools}

    assert {"state_set", "state_publish", "state_list"} <= names


def test_tool_search_tool_returns_catalog_summary_without_schema() -> None:
    tool = ToolSearchTool(tool_definitions_provider=lambda agent_id: _definitions())

    result = tool.execute(
        {"query": "保存复盘为笔记", "top_k": 8},
        context=RunContext(
            session_id="sess_tool_catalog",
            run_id="run_tool_catalog",
            agent_id="agent_main",
            turn_id="turn_tool_catalog",
            entry_agent_id="agent_main",
        ),
    )
    payload = json.loads(result.content)
    names = set(payload["revealed_tool_names"])

    assert result.success is True
    assert "note_create" in names
    assert "parameters_schema" not in result.content
    assert payload["revealed_tool_count"] == len(payload["revealed_tools"])


def test_tool_catalog_risk_notes_in_resume_version_do_not_reveal_note_tools() -> None:
    result = ToolCatalog(_definitions()).search(
        query="create a customized resume version with markdown content, keyword strategy, and risk notes",
        top_k=8,
    )
    names = {entry.name for entry in result.revealed_tools}

    assert "career_resume_version" in result.matched_groups
    assert "note" not in result.matched_groups
    assert "note_create" not in names
    assert "note_append" not in names


def test_tool_catalog_explicit_note_intent_still_reveals_note_tools() -> None:
    result = ToolCatalog(_definitions()).search(query="save this as a note", top_k=8)
    names = {entry.name for entry in result.revealed_tools}

    assert "note" in result.matched_groups
    assert "note_create" in names


def _definitions() -> list[ToolDefinition]:
    names = [
        "tool_search",
        "memory_write",
        "delegate_agents",
        "agent_task_status",
        "state_set",
        "state_publish",
        "state_list",
        "session_list_artifacts",
        "session_plan_artifact_access",
        "session_read_artifact",
        "session_search_artifact",
        "session_create_text_artifact",
        "retrieval_search",
        "retrieval_context_pack",
        "career_resume_profile_get",
        "career_resume_profile_list",
        "career_resume_profile_save",
        "career_profile_get",
        "career_profile_merge",
        "career_jd_analysis_get",
        "career_jd_analysis_list",
        "career_jd_analysis_save",
        "career_job_fit_report_get",
        "career_job_fit_report_list",
        "career_job_fit_report_save",
        "career_resume_version_create",
        "career_resume_version_get",
        "career_resume_version_list",
        "career_application_get",
        "career_application_list",
        "career_application_create",
        "career_application_merge",
        "note_create",
        "note_get",
        "note_append",
        "learning_task_create",
        "learning_task_get",
        "learning_task_update_state",
    ]
    return [
        ToolDefinition(
            name=name,
            description=f"{name} description",
            parameters_schema={"type": "object", "properties": {"value": {"type": "string"}}},
        )
        for name in names
    ]
