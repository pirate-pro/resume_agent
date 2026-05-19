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
    assert "session_read_artifact" in names
    assert "tool_search" not in names
    assert "state_set" not in names


def test_tool_catalog_reveals_learning_and_retrieval_for_learning_task_query() -> None:
    result = ToolCatalog(_definitions()).search(query="根据之前短板创建学习任务并监督我完成", top_k=8)
    names = {entry.name for entry in result.revealed_tools}

    assert {"retrieval_search", "retrieval_context_pack"} <= names
    assert {"learning_task_create", "learning_task_update_state"} <= names
    assert "note_create" not in names


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


def _definitions() -> list[ToolDefinition]:
    names = [
        "tool_search",
        "memory_write",
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
        "career_application_get",
        "career_application_list",
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
