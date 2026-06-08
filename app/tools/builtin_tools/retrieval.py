"""Built-in read-only tools for product-context retrieval."""

from __future__ import annotations

import json
from typing import Any

from app.core.errors import ToolExecutionError, ValidationError
from app.domain.models import RunContext, ToolDefinition, ToolExecutionResult
from app.retrieval.facade import (
    RetrievalPrincipal,
    retrieval_context_pack_payload,
    retrieval_search_payload,
    retrieval_tool_input_from_arguments,
    retrieval_tool_parameters_schema,
)
from app.retrieval.service import RetrievalService
from app.tools.builtin_tools.common import validate_context

__all__ = [
    "RetrievalContextPackTool",
    "RetrievalSearchTool",
]


class RetrievalSearchTool:
    """Search read-only product context and current-session artifacts."""

    def __init__(self, retrieval_service: RetrievalService) -> None:
        self._retrieval_service = retrieval_service

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="retrieval_search",
            description=(
                "Search read-only Career, Note, Knowledge, Learning, and current SessionArtifact context. "
                "Use when the user refers to previous/saved/recent records without giving ids. "
                "This tool never writes products, files, or memory."
            ),
            parameters_schema=retrieval_tool_parameters_schema(),
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        payload = _retrieval_search_payload_for_run(
            self._retrieval_service,
            arguments,
            run_context=run_context,
        )
        return ToolExecutionResult(
            tool_name="retrieval_search",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class RetrievalContextPackTool:
    """Build a grouped, budgeted context pack for agent consumption."""

    def __init__(self, retrieval_service: RetrievalService) -> None:
        self._retrieval_service = retrieval_service

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="retrieval_context_pack",
            description=(
                "Build a read-only, budgeted context pack grouped by Career, Note, Knowledge, Learning, "
                "and current SessionArtifact sources. Use before answering questions that depend on "
                "saved product context. This tool never writes products, files, or memory."
            ),
            parameters_schema=retrieval_tool_parameters_schema(),
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        payload = _retrieval_context_pack_payload_for_run(
            self._retrieval_service,
            arguments,
            run_context=run_context,
        )
        return ToolExecutionResult(
            tool_name="retrieval_context_pack",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


def _retrieval_search_payload_for_run(
    retrieval_service: RetrievalService,
    arguments: dict[str, Any],
    *,
    run_context: RunContext,
) -> dict[str, Any]:
    try:
        return retrieval_search_payload(
            retrieval_service,
            retrieval_tool_input_from_arguments(arguments),
            principal=RetrievalPrincipal(session_id=run_context.session_id),
            include_session_id=True,
        )
    except ValidationError as exc:
        raise ToolExecutionError(str(exc)) from exc


def _retrieval_context_pack_payload_for_run(
    retrieval_service: RetrievalService,
    arguments: dict[str, Any],
    *,
    run_context: RunContext,
) -> dict[str, Any]:
    try:
        return retrieval_context_pack_payload(
            retrieval_service,
            retrieval_tool_input_from_arguments(arguments),
            principal=RetrievalPrincipal(session_id=run_context.session_id),
            include_session_id=True,
        )
    except ValidationError as exc:
        raise ToolExecutionError(str(exc)) from exc
