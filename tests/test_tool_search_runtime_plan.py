"""Tests for tool_search runtime plan guidance."""

from __future__ import annotations

import json

from app.domain.models import RunContext, ToolDefinition
from app.runtime.workflow.tool_plan import RuntimeToolPlan
from app.tools.builtin_tools import ToolSearchTool

__all__ = []


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} description",
        parameters_schema={"type": "object", "properties": {"value": {"type": "string"}}},
    )


def _context() -> RunContext:
    return RunContext(
        session_id="sess_tool_search_plan",
        run_id="run_tool_search_plan",
        agent_id="agent_main",
        turn_id="turn_tool_search_plan",
        entry_agent_id="agent_main",
    )


def test_tool_search_prefers_runtime_plan_next_allowed_tools_for_career_query() -> None:
    tool = ToolSearchTool(
        tool_definitions_provider=lambda agent_id: [
            _definition("tool_search"),
            _definition("delegate_agents"),
            _definition("session_read_artifact"),
            _definition("career_resume_version_create"),
            _definition("career_application_merge"),
        ],
        runtime_plan_provider=lambda context: RuntimeToolPlan(
            phase="resume_version",
            known_refs={"application_id": "application_alpha"},
            missing_outputs=["resume_version"],
            next_allowed_tools=["career_resume_version_create"],
            upcoming_required_tools=["career_application_merge"],
            discouraged_tools=["session_read_artifact", "delegate_agents"],
            schema_groups=["career_resume_version"],
            next_action="只生成定制简历版本。",
        ),
    )

    result = tool.execute(
        {"query": "创建定制简历版本并更新求职项目", "groups": ["career"], "top_k": 8},
        context=_context(),
    )
    payload = json.loads(result.content)

    assert payload["runtime_plan_applied"] is True
    assert payload["runtime_current_allowed_tools"] == ["career_resume_version_create"]
    assert payload["runtime_next_allowed_tools"] == ["career_resume_version_create"]
    assert payload["runtime_upcoming_required_tools"] == ["career_application_merge"]
    assert payload["revealed_tool_names"] == ["career_resume_version_create"]
    assert "session_read_artifact" in payload["runtime_discouraged_tools"]
    assert "不要为同一步继续 tool_search" in payload["next_step"]


def test_tool_search_does_not_apply_career_runtime_plan_to_memory_query() -> None:
    tool = ToolSearchTool(
        tool_definitions_provider=lambda agent_id: [
            _definition("tool_search"),
            _definition("memory_write"),
            _definition("career_resume_version_create"),
        ],
        runtime_plan_provider=lambda context: RuntimeToolPlan(
            phase="resume_version",
            missing_outputs=["resume_version"],
            next_allowed_tools=["career_resume_version_create"],
        ),
    )

    result = tool.execute(
        {"query": "以后叫我张明，需要写入 memory", "top_k": 8},
        context=_context(),
    )
    payload = json.loads(result.content)

    assert "runtime_plan_applied" not in payload
    assert "memory_write" in payload["revealed_tool_names"]
    assert "career_resume_version_create" not in payload["revealed_tool_names"]


def test_tool_search_final_runtime_plan_reveals_no_new_tools() -> None:
    tool = ToolSearchTool(
        tool_definitions_provider=lambda agent_id: [
            _definition("tool_search"),
            _definition("delegate_agents"),
            _definition("career_application_get"),
        ],
        runtime_plan_provider=lambda context: RuntimeToolPlan(
            phase="jd_fit",
            known_refs={"application_id": "application_alpha"},
            final_answer_ready=True,
            discouraged_tools=["tool_search", "delegate_agents", "career_application_get"],
            next_action="关键产物已完成，直接答复。",
        ),
    )

    result = tool.execute(
        {"query": "岗位匹配报告下一步需要什么工具", "groups": ["career"], "top_k": 8},
        context=_context(),
    )
    payload = json.loads(result.content)

    assert payload["runtime_plan_applied"] is True
    assert payload["runtime_final_answer_ready"] is True
    assert payload["revealed_tool_names"] == []
    assert payload["revealed_tool_count"] == 0
    assert "直接最终答复" in payload["next_step"]
