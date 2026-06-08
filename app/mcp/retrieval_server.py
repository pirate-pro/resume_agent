"""MCP server adapter for retrieval/RAG tools."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Literal, Protocol

from app.api.dependencies.retrieval import get_retrieval_service
from app.core.errors import ValidationError
from app.retrieval.facade import (
    RetrievalPrincipal,
    RetrievalToolInput,
    retrieval_context_pack_payload,
    retrieval_search_payload,
)
from app.retrieval.service import RetrievalService

__all__ = [
    "create_retrieval_mcp_server",
    "retrieval_principal_from_env",
    "run_retrieval_mcp_server",
]

RetrievalMcpTransport = Literal["stdio", "streamable-http"]


class _PayloadBuilder(Protocol):
    def __call__(
        self,
        retrieval_service: RetrievalService,
        tool_input: RetrievalToolInput,
        *,
        principal: RetrievalPrincipal,
        include_session_id: bool = False,
    ) -> dict[str, Any]: ...


def create_retrieval_mcp_server(
    *,
    retrieval_service: RetrievalService | None = None,
    principal: RetrievalPrincipal | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    streamable_http_path: str = "/mcp",
) -> Any:
    """Create a FastMCP server exposing read-only retrieval tools."""

    FastMCP = _load_fastmcp()
    service = retrieval_service or get_retrieval_service()
    server_principal = principal or retrieval_principal_from_env()
    mcp = FastMCP(
        "resume-agent-retrieval",
        instructions=(
            "Read-only retrieval tools over Career, Note, Knowledge, Learning, "
            "and server-bound SessionArtifact context."
        ),
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
    )

    @mcp.tool(
        name="retrieval_search",
        description=(
            "Search read-only Career, Note, Knowledge, Learning, and server-bound "
            "SessionArtifact context. This tool never writes products, files, or memory."
        ),
    )
    def retrieval_search(
        query: str,
        source_types: list[str] | None = None,
        related_application_id: str | None = None,
        top_k: int = 8,
        max_chars: int = 12000,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        return _run_payload(
            retrieval_search_payload,
            service,
            _tool_input(
                query=query,
                source_types=source_types,
                related_application_id=related_application_id,
                top_k=top_k,
                max_chars=max_chars,
                include_archived=include_archived,
            ),
            principal=server_principal,
        )

    @mcp.tool(
        name="retrieval_context_pack",
        description=(
            "Build a read-only, budgeted context pack grouped by Career, Note, Knowledge, "
            "Learning, and server-bound SessionArtifact sources. This tool never writes "
            "products, files, or memory."
        ),
    )
    def retrieval_context_pack(
        query: str,
        source_types: list[str] | None = None,
        related_application_id: str | None = None,
        top_k: int = 8,
        max_chars: int = 12000,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        return _run_payload(
            retrieval_context_pack_payload,
            service,
            _tool_input(
                query=query,
                source_types=source_types,
                related_application_id=related_application_id,
                top_k=top_k,
                max_chars=max_chars,
                include_archived=include_archived,
            ),
            principal=server_principal,
        )

    return mcp


def run_retrieval_mcp_server(
    *,
    transport: RetrievalMcpTransport = "stdio",
    principal: RetrievalPrincipal | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/mcp",
    allow_remote: bool = False,
) -> None:
    """Run the retrieval MCP server with the selected transport."""

    if transport == "streamable-http" and not allow_remote and not _is_localhost(host):
        raise RuntimeError("Remote MCP HTTP binding requires explicit --allow-remote.")
    mcp = create_retrieval_mcp_server(
        principal=principal,
        host=host,
        port=port,
        streamable_http_path=path,
    )
    mcp.run(transport=transport)


def retrieval_principal_from_env(environ: Mapping[str, str] | None = None) -> RetrievalPrincipal:
    """Build the server-owned retrieval principal from process environment."""

    values = os.environ if environ is None else environ
    return RetrievalPrincipal(
        session_id=_empty_to_none(values.get("RESUME_AGENT_MCP_SESSION_ID")),
        owner_user_id=_empty_to_default(values.get("RESUME_AGENT_MCP_OWNER_USER_ID"), "user_local"),
        workspace_id=_empty_to_default(values.get("RESUME_AGENT_MCP_WORKSPACE_ID"), "workspace_default"),
    )


def _tool_input(
    *,
    query: str,
    source_types: list[str] | None,
    related_application_id: str | None,
    top_k: int,
    max_chars: int,
    include_archived: bool,
) -> RetrievalToolInput:
    return RetrievalToolInput(
        query=query,
        source_types=[] if source_types is None else source_types,
        related_application_id=related_application_id,
        top_k=top_k,
        max_chars=max_chars,
        include_archived=include_archived,
    )


def _run_payload(
    payload_builder: _PayloadBuilder,
    retrieval_service: RetrievalService,
    tool_input: RetrievalToolInput,
    *,
    principal: RetrievalPrincipal,
) -> dict[str, Any]:
    try:
        return payload_builder(
            retrieval_service,
            tool_input,
            principal=principal,
            include_session_id=False,
        )
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def _load_fastmcp() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        raise RuntimeError("MCP SDK is not installed. Install project dependencies with `uv sync`.") from exc
    return FastMCP


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _empty_to_default(value: str | None, default: str) -> str:
    normalized = _empty_to_none(value)
    return normalized if normalized is not None else default


def _is_localhost(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1", "[::1]"}
