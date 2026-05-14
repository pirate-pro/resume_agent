"""Tests for read-only retrieval tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.errors import ToolExecutionError
from app.domain.models import RunContext
from app.retrieval.service import RetrievalService
from app.tools.builtins import RetrievalContextPackTool, RetrievalSearchTool
from tests.test_retrieval_service import _seed_stores, _service

__all__ = []


def test_retrieval_search_tool_returns_typed_refs_without_paths(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    tool = RetrievalSearchTool(retrieval_service=_service(stores))

    result = tool.execute(
        {
            "query": "星河智能 RAG 二面准备",
            "source_types": ["career_application", "note", "learning_task"],
            "top_k": 8,
        },
        context=_context("sess_alpha"),
    )
    payload = json.loads(result.content)

    assert result.success is True
    assert payload["session_id"] == "sess_alpha"
    assert payload["count"] >= 3
    assert {hit["source"]["source_type"] for hit in payload["hits"]} >= {
        "career_application",
        "note",
        "learning_task",
    }
    assert all(hit["match_reason"] for hit in payload["hits"])
    assert all(hit["source"]["source_id"] for hit in payload["hits"])
    assert not _contains_path_key(payload)


def test_retrieval_context_pack_tool_groups_context_and_uses_run_session(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    tool = RetrievalContextPackTool(retrieval_service=_service(stores))

    result = tool.execute(
        {
            "query": "星河智能 RAG",
            "source_types": ["session_artifact", "career_application", "job_fit_report", "interview_question"],
            "top_k": 8,
            "max_chars": 2000,
        },
        context=_context("sess_alpha"),
    )
    payload = json.loads(result.content)
    context_pack = payload["context_pack"]

    assert result.success is True
    assert payload["session_id"] == "sess_alpha"
    assert context_pack["citations"]
    assert context_pack["grouped_context"]["career"]
    assert context_pack["grouped_context"]["knowledge"]
    assert context_pack["grouped_context"]["artifacts"]
    assert {hit["source"]["source_id"] for hit in context_pack["grouped_context"]["artifacts"]} == {
        "artifact_alpha_jd"
    }
    assert not _contains_path_key(payload)


def test_retrieval_tools_accept_source_group_aliases(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    tool = RetrievalContextPackTool(retrieval_service=_service(stores))

    result = tool.execute(
        {
            "query": "星河智能 RAG 面试题",
            "source_types": ["knowledge", "learning", "artifacts"],
            "top_k": 8,
            "max_chars": 2000,
        },
        context=_context("sess_alpha"),
    )
    payload = json.loads(result.content)
    source_types = {
        hit["source"]["source_type"]
        for hit in payload["context_pack"]["hits"]
    }

    assert result.success is True
    assert source_types & {"external_resource", "interview_question", "skill_requirement"}
    assert source_types & {"learning_task", "weakness_tracker"}
    assert "session_artifact" in source_types


def test_retrieval_tools_accept_common_career_source_aliases(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    tool = RetrievalSearchTool(retrieval_service=_service(stores))

    resume_result = tool.execute(
        {
            "query": "张明 Python RAG",
            "source_types": ["resume"],
            "top_k": 3,
        },
        context=_context("sess_alpha"),
    )
    resume_payload = json.loads(resume_result.content)
    resume_source_types = {hit["source"]["source_type"] for hit in resume_payload["hits"]}
    result = tool.execute(
        {
            "query": "星河智能 匹配报告",
            "source_types": [
                "resume",
                "career_job_fit_report",
                "job_fit_reports",
                "career_jd_analysis",
                "jd",
                "learning_weakness",
            ],
            "top_k": 8,
        },
        context=_context("sess_alpha"),
    )
    payload = json.loads(result.content)
    source_types = {hit["source"]["source_type"] for hit in payload["hits"]}

    assert resume_result.success is True
    assert "resume_profile" in resume_source_types
    assert result.success is True
    assert "job_fit_report" in source_types
    assert "jd_analysis" in source_types
    assert "weakness_tracker" in source_types


def test_retrieval_tools_reject_path_store_owned_and_invalid_source_type(tmp_path: Path) -> None:
    tool = RetrievalSearchTool(retrieval_service=RetrievalService())

    with pytest.raises(ToolExecutionError, match="Path arguments are not allowed"):
        tool.execute({"query": "星河智能", "file_path": "/tmp/source.txt"}, context=_context("sess_alpha"))

    with pytest.raises(ToolExecutionError, match="Store-owned fields are not accepted"):
        tool.execute({"query": "星河智能", "session_id": "sess_beta"}, context=_context("sess_alpha"))

    with pytest.raises(ToolExecutionError, match="source_type is invalid"):
        tool.execute({"query": "星河智能", "source_types": ["workspace"]}, context=_context("sess_alpha"))


def _context(session_id: str, agent_id: str = "agent_main") -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}",
        agent_id=agent_id,
        turn_id=f"turn_{session_id}",
        entry_agent_id=agent_id,
        parent_run_id=None,
        trace_flags={},
    )


def _contains_path_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if "path" in str(key).lower() or "relpath" in str(key).lower():
                return True
            if _contains_path_key(item):
                return True
    if isinstance(value, list):
        return any(_contains_path_key(item) for item in value)
    return False
