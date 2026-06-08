"""MCP-backed proxy tools for retrieval."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.errors import ToolExecutionError, ValidationError
from app.domain.models import RunContext, ToolDefinition, ToolExecutionResult
from app.mcp.retrieval_server import create_retrieval_mcp_server
from app.retrieval.facade import (
    RetrievalPrincipal,
    RetrievalToolInput,
    retrieval_tool_input_from_arguments,
    retrieval_tool_parameters_schema,
)
from app.retrieval.service import RetrievalService
from app.tools.builtin_tools.common import validate_context

__all__ = [
    "RetrievalMcpContextPackTool",
    "RetrievalMcpSearchTool",
]


class RetrievalMcpSearchTool:
    """Search retrieval context through the MCP retrieval server boundary."""

    def __init__(self, retrieval_service: RetrievalService) -> None:
        self._retrieval_service = retrieval_service

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="retrieval_search",
            description=(
                "Search read-only Career, Note, Knowledge, Learning, and current SessionArtifact context "
                "through the Retrieval MCP boundary. Use when the user refers to previous/saved/recent "
                "records without giving ids. This tool never writes products, files, or memory."
            ),
            parameters_schema=retrieval_tool_parameters_schema(),
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        payload = _call_retrieval_mcp_tool(
            tool_name="retrieval_search",
            arguments=arguments,
            retrieval_service=self._retrieval_service,
            run_context=run_context,
        )
        return ToolExecutionResult(
            tool_name="retrieval_search",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class RetrievalMcpContextPackTool:
    """Build retrieval context packs through the MCP retrieval server boundary."""

    def __init__(self, retrieval_service: RetrievalService) -> None:
        self._retrieval_service = retrieval_service

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="retrieval_context_pack",
            description=(
                "Build a read-only, budgeted context pack through the Retrieval MCP boundary, grouped by "
                "Career, Note, Knowledge, Learning, and current SessionArtifact sources. Use before "
                "answering questions that depend on saved product context. This tool never writes "
                "products, files, or memory."
            ),
            parameters_schema=retrieval_tool_parameters_schema(),
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        payload = _call_retrieval_mcp_tool(
            tool_name="retrieval_context_pack",
            arguments=arguments,
            retrieval_service=self._retrieval_service,
            run_context=run_context,
        )
        return ToolExecutionResult(
            tool_name="retrieval_context_pack",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


def _call_retrieval_mcp_tool(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    retrieval_service: RetrievalService,
    run_context: RunContext,
) -> dict[str, Any]:
    try:
        tool_input = retrieval_tool_input_from_arguments(arguments)
        mcp_arguments = _mcp_arguments_from_input(tool_input)
        server = create_retrieval_mcp_server(
            retrieval_service=retrieval_service,
            principal=RetrievalPrincipal(session_id=run_context.session_id),
        )
        return _run_mcp_call(server, tool_name, mcp_arguments)
    except ValidationError as exc:
        raise ToolExecutionError(str(exc)) from exc
    except RuntimeError as exc:
        raise ToolExecutionError(str(exc)) from exc
    except Exception as exc:
        raise ToolExecutionError(f"Retrieval MCP proxy failed: {exc}") from exc


def _mcp_arguments_from_input(tool_input: RetrievalToolInput) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "include_archived": tool_input.include_archived,
        "max_chars": tool_input.max_chars,
        "query": tool_input.query,
        "source_types": list(tool_input.source_types),
        "top_k": tool_input.top_k,
    }
    if tool_input.related_application_id is not None:
        payload["related_application_id"] = tool_input.related_application_id
    return payload


def _run_mcp_call(server: Any, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_call_mcp_tool(server, tool_name, arguments))


async def _call_mcp_tool(server: Any, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await server.call_tool(tool_name, arguments)
    if isinstance(result, tuple) and len(result) >= 2 and isinstance(result[1], dict):
        return result[1]
    if isinstance(result, dict):
        return result
    content = getattr(result, "content", None)
    if content:
        text = getattr(content[0], "text", None)
        if isinstance(text, str):
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
    raise ToolExecutionError(f"Unexpected MCP tool result for {tool_name}: {result!r}")
