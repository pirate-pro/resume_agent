"""Tests for MCP-backed internal retrieval tool proxy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from app.core.errors import ToolExecutionError, ValidationError
from app.core.settings import Settings
from app.domain.models import RunContext, ToolCall
from app.runtime.agent_capability import AgentCapabilityRegistry
from app.tools.mcp_retrieval_proxy import RetrievalMcpContextPackTool, RetrievalMcpSearchTool
from app.tools.registry import ToolRegistry
from app.tools.retrieval_registration import register_retrieval_tools
from tests.test_retrieval_service import _seed_stores, _service

__all__ = []


def test_retrieval_mcp_proxy_search_uses_run_session_without_exposing_session_id(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    tool = RetrievalMcpSearchTool(retrieval_service=_service(stores))

    result = tool.execute(
        {
            "query": "星河智能 RAG 二面准备",
            "source_types": ["career", "notes", "knowledge", "learning"],
            "top_k": 20,
        },
        context=_context("sess_alpha"),
    )
    payload = json.loads(result.content)
    source_types = {hit["source"]["source_type"] for hit in payload["hits"]}

    assert result.success is True
    assert payload["count"] >= 1
    assert "session_id" not in payload
    assert {"career_application", "note", "interview_question", "learning_task"} & source_types
    assert not _contains_path_key(payload)


def test_retrieval_mcp_proxy_context_pack_can_read_current_session_artifacts(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    tool = RetrievalMcpContextPackTool(retrieval_service=_service(stores))

    result = tool.execute(
        {
            "query": "星河智能 RAG",
            "source_types": ["artifacts"],
            "top_k": 5,
            "max_chars": 2000,
        },
        context=_context("sess_alpha"),
    )
    payload = json.loads(result.content)
    artifacts = payload["context_pack"]["grouped_context"]["artifacts"]

    assert result.success is True
    assert "session_id" not in payload
    assert {hit["source"]["source_id"] for hit in artifacts} == {"artifact_alpha_jd"}
    assert not _contains_path_key(payload)


def test_retrieval_mcp_proxy_rejects_model_owned_session_id(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    tool = RetrievalMcpSearchTool(retrieval_service=_service(stores))

    with pytest.raises(ToolExecutionError, match="Store-owned fields are not accepted"):
        tool.execute(
            {"query": "星河智能", "session_id": "sess_beta"},
            context=_context("sess_alpha"),
        )


def test_register_retrieval_tools_can_use_mcp_backend(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    registry = ToolRegistry(capability_registry=AgentCapabilityRegistry.for_tests())

    register_retrieval_tools(
        registry=registry,
        retrieval_service=_service(stores),
        backend="mcp",
    )
    result = registry.execute(
        call=_tool_call("retrieval_context_pack", {"query": "星河智能 RAG", "source_types": ["artifacts"]}),
        context=_context("sess_alpha"),
    )
    payload = json.loads(result.content)

    assert {item.name for item in registry.list_definitions_for_agent("agent_main")} == {
        "retrieval_search",
        "retrieval_context_pack",
    }
    assert payload["context_pack"]["grouped_context"]["artifacts"]


def test_settings_accepts_retrieval_tool_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETRIEVAL_TOOL_BACKEND", "mcp")
    assert Settings.load().retrieval_tool_backend == "mcp"
    monkeypatch.setenv("RETRIEVAL_TOOL_BACKEND", "unknown")
    with pytest.raises(ValidationError, match="RETRIEVAL_TOOL_BACKEND must be local/mcp"):
        Settings.load()


def _context(session_id: str) -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}",
        agent_id="agent_main",
        turn_id=f"turn_{session_id}",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={},
    )


def _tool_call(name: str, arguments: dict[str, Any]) -> Any:
    return ToolCall(name=name, arguments=arguments)


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
