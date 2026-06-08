"""Helpers for registering retrieval tools with a selectable backend."""

from __future__ import annotations

from app.core.errors import ValidationError
from app.retrieval.service import RetrievalService
from app.tools.builtin_tools.retrieval import RetrievalContextPackTool, RetrievalSearchTool
from app.tools.mcp_retrieval_proxy import RetrievalMcpContextPackTool, RetrievalMcpSearchTool
from app.tools.registry import ToolRegistry

__all__ = ["register_retrieval_tools"]


def register_retrieval_tools(
    *,
    registry: ToolRegistry,
    retrieval_service: RetrievalService,
    backend: str = "local",
) -> None:
    """Register retrieval tools backed by local service calls or MCP proxy calls."""

    normalized = backend.strip().lower()
    if normalized == "local":
        registry.register(RetrievalSearchTool(retrieval_service=retrieval_service))
        registry.register(RetrievalContextPackTool(retrieval_service=retrieval_service))
        return
    if normalized == "mcp":
        registry.register(RetrievalMcpSearchTool(retrieval_service=retrieval_service))
        registry.register(RetrievalMcpContextPackTool(retrieval_service=retrieval_service))
        return
    raise ValidationError("RETRIEVAL_TOOL_BACKEND must be local/mcp.")
