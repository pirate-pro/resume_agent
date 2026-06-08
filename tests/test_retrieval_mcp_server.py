"""Tests for retrieval MCP server adapter."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any

import pytest

pytest.importorskip("mcp")

from app.mcp.retrieval_server import create_retrieval_mcp_server
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.retrieval.facade import RetrievalPrincipal
from mcp import ClientSession, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import stdio_client
from tests.test_retrieval_service import _add_artifact, _seed_stores, _service

__all__ = []


def test_retrieval_mcp_server_exposes_read_only_tools(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    server = create_retrieval_mcp_server(
        retrieval_service=_service(stores),
        principal=RetrievalPrincipal(session_id=None),
    )

    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    schemas = {tool.name: tool.inputSchema for tool in tools}

    assert {"retrieval_search", "retrieval_context_pack"} <= names
    assert "session_id" not in schemas["retrieval_search"]["properties"]
    assert "file_path" not in schemas["retrieval_search"]["properties"]
    assert "session_id" not in schemas["retrieval_context_pack"]["properties"]


def test_retrieval_mcp_search_returns_structured_payload_without_session_or_paths(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    server = create_retrieval_mcp_server(
        retrieval_service=_service(stores),
        principal=RetrievalPrincipal(session_id=None),
    )

    payload = _call_tool(
        server,
        "retrieval_search",
        {
            "query": "星河智能 RAG 二面准备",
            "top_k": 20,
        },
    )
    source_types = {hit["source"]["source_type"] for hit in payload["hits"]}

    assert payload["count"] >= 1
    assert "session_id" not in payload
    assert "session_artifact" not in source_types
    assert not _contains_path_key(payload)


def test_retrieval_mcp_rejects_session_artifact_without_app_session(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    server = create_retrieval_mcp_server(
        retrieval_service=_service(stores),
        principal=RetrievalPrincipal(session_id=None),
    )

    with pytest.raises(Exception, match="session_artifact retrieval requires an app session"):
        _call_tool(
            server,
            "retrieval_search",
            {
                "query": "星河智能 RAG",
                "source_types": ["session_artifact"],
            },
        )


def test_retrieval_mcp_allows_session_artifact_when_server_binds_app_session(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    server = create_retrieval_mcp_server(
        retrieval_service=_service(stores),
        principal=RetrievalPrincipal(session_id="sess_alpha"),
    )

    payload = _call_tool(
        server,
        "retrieval_context_pack",
        {
            "query": "星河智能 RAG",
            "source_types": ["artifacts"],
            "top_k": 5,
            "max_chars": 2000,
        },
    )
    context_pack = payload["context_pack"]

    assert "session_id" not in payload
    assert context_pack["grouped_context"]["artifacts"]
    assert {hit["source"]["source_id"] for hit in context_pack["grouped_context"]["artifacts"]} == {
        "artifact_alpha_jd"
    }


def test_retrieval_mcp_stdio_runner_smoke_uses_real_data_dir_layout(tmp_path: Path) -> None:
    _seed_stores(tmp_path)
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session("sess_alpha")
    _add_artifact(
        repository,
        "sess_alpha",
        "artifact_alpha_jd",
        "星河智能 AI Agent 后端二面会追问 RAG 检索评估、chunk 策略和异步任务。",
    )

    no_session = asyncio.run(_call_stdio_tool(tmp_path, app_session_id=None))
    assert {"retrieval_search", "retrieval_context_pack"} <= set(no_session["tools"])
    assert no_session["search"]["count"] >= 1
    assert "session_id" not in no_session["search"]
    assert "session_artifact" not in {
        hit["source"]["source_type"] for hit in no_session["search"]["hits"]
    }
    assert "session_artifact retrieval requires an app session" in no_session["artifact_error"]

    with_session = asyncio.run(_call_stdio_tool(tmp_path, app_session_id="sess_alpha"))
    artifacts = with_session["artifact"]["context_pack"]["grouped_context"]["artifacts"]
    assert {hit["source"]["source_id"] for hit in artifacts} == {"artifact_alpha_jd"}
    assert "session_id" not in with_session["artifact"]


def test_retrieval_mcp_streamable_http_runner_smoke_uses_real_data_dir_layout(tmp_path: Path) -> None:
    _seed_stores(tmp_path)
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session("sess_alpha")
    _add_artifact(
        repository,
        "sess_alpha",
        "artifact_alpha_jd",
        "星河智能 AI Agent 后端二面会追问 RAG 检索评估、chunk 策略和异步任务。",
    )
    port = _free_port()
    process = _start_http_server(tmp_path, port=port, app_session_id="sess_alpha")
    try:
        _wait_for_port(process, port=port)
        payload = asyncio.run(_call_streamable_http_tool(port=port))
    finally:
        _stop_process(process)

    assert {"retrieval_search", "retrieval_context_pack"} <= set(payload["tools"])
    assert payload["search"]["count"] >= 1
    assert "session_id" not in payload["search"]
    artifacts = payload["artifact"]["context_pack"]["grouped_context"]["artifacts"]
    assert {hit["source"]["source_id"] for hit in artifacts} == {"artifact_alpha_jd"}
    assert "session_id" not in payload["artifact"]


def _call_tool(server: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(name, arguments))
    if isinstance(result, tuple):
        structured = result[1]
        if isinstance(structured, dict):
            return structured
    if isinstance(result, dict):
        return result
    raise AssertionError(f"Unexpected MCP tool result: {result!r}")


async def _call_stdio_tool(data_dir: Path, *, app_session_id: str | None) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["DATA_DIR"] = str(data_dir)
    env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    args = ["scripts/run_retrieval_mcp.py", "--transport", "stdio"]
    if app_session_id is not None:
        args.extend(["--app-session-id", app_session_id])
    params = StdioServerParameters(
        command=sys.executable,
        args=args,
        env=env,
        cwd=root,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            search_result = await session.call_tool(
                "retrieval_search",
                {"query": "星河智能 RAG 二面准备", "top_k": 20},
            )
            artifact_result = await session.call_tool(
                "retrieval_context_pack",
                {
                    "query": "星河智能 RAG",
                    "source_types": ["session_artifact"],
                    "top_k": 5,
                    "max_chars": 2000,
                },
            )
    output: dict[str, Any] = {
        "tools": sorted(tool.name for tool in tools.tools),
        "search": _tool_result_payload(search_result),
    }
    if bool(getattr(artifact_result, "isError", False)):
        content = getattr(artifact_result, "content", [])
        text = getattr(content[0], "text", "") if content else ""
        output["artifact_error"] = text
    else:
        output["artifact"] = _tool_result_payload(artifact_result)
    return output


async def _call_streamable_http_tool(*, port: int) -> dict[str, Any]:
    async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (read, write, _session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            search_result = await session.call_tool(
                "retrieval_search",
                {"query": "星河智能 RAG 二面准备", "top_k": 20},
            )
            artifact_result = await session.call_tool(
                "retrieval_context_pack",
                {
                    "query": "星河智能 RAG",
                    "source_types": ["session_artifact"],
                    "top_k": 5,
                    "max_chars": 2000,
                },
            )
    return {
        "tools": sorted(tool.name for tool in tools.tools),
        "search": _tool_result_payload(search_result),
        "artifact": _tool_result_payload(artifact_result),
    }


def _start_http_server(data_dir: Path, *, port: int, app_session_id: str) -> subprocess.Popen[str]:
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["DATA_DIR"] = str(data_dir)
    env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return subprocess.Popen(
        [
            sys.executable,
            "scripts/run_retrieval_mcp.py",
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--app-session-id",
            app_session_id,
        ],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(process: subprocess.Popen[str], *, port: int) -> None:
    deadline = time.monotonic() + 10
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise AssertionError(f"MCP HTTP server exited early.\nstdout={stdout}\nstderr={stderr}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.1)
    raise AssertionError(f"MCP HTTP server did not listen on port {port}: {last_error}")


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)


def _tool_result_payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    if isinstance(result, tuple) and len(result) >= 2 and isinstance(result[1], dict):
        return result[1]
    content = getattr(result, "content", None)
    if content:
        text = getattr(content[0], "text", None)
        if isinstance(text, str):
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
    raise AssertionError(f"Unexpected MCP tool result: {result!r}")


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
