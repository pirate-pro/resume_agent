"""Debug-only HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_token_usage_debug_service
from app.api.responses import ok
from app.debug.token_usage import (
    TokenUsageBucket,
    TokenUsageCall,
    TokenUsageDebugService,
    TokenUsageSessionDetail,
    TokenUsageSessionSummary,
    TokenUsageSummary,
)
from app.schemas.common import StandardResponse
from app.schemas.debug import (
    TokenUsageBucketView,
    TokenUsageCallView,
    TokenUsageSessionDetailView,
    TokenUsageSessionView,
    TokenUsageSummaryView,
)

__all__ = ["router"]

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get(
    "/token-usage/summary",
    response_model=StandardResponse[TokenUsageSummaryView],
)
def get_token_usage_summary(
    agent_id: str | None = Query(default=None),
    phase: str | None = Query(default=None),
    estimated: bool | None = Query(default=None),
    session_limit: int = Query(default=10, ge=1, le=100),
    call_limit: int = Query(default=10, ge=1, le=100),
    bucket_limit: int = Query(default=8, ge=1, le=50),
    service: TokenUsageDebugService = Depends(get_token_usage_debug_service),
) -> StandardResponse[TokenUsageSummaryView]:
    summary = service.summarize(
        agent_id=agent_id,
        phase=phase,
        estimated=estimated,
        session_limit=session_limit,
        call_limit=call_limit,
        bucket_limit=bucket_limit,
    )
    return ok(_summary_view(summary))


@router.get(
    "/token-usage/calls",
    response_model=StandardResponse[list[TokenUsageCallView]],
)
def list_token_usage_calls(
    session_id: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    phase: str | None = Query(default=None),
    estimated: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    service: TokenUsageDebugService = Depends(get_token_usage_debug_service),
) -> StandardResponse[list[TokenUsageCallView]]:
    return ok([
        _call_view(item)
        for item in service.list_calls(
            session_id=session_id,
            agent_id=agent_id,
            phase=phase,
            estimated=estimated,
            limit=limit,
        )
    ])


@router.get(
    "/token-usage/sessions/{session_id}",
    response_model=StandardResponse[TokenUsageSessionDetailView],
)
def get_token_usage_session_detail(
    session_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    service: TokenUsageDebugService = Depends(get_token_usage_debug_service),
) -> StandardResponse[TokenUsageSessionDetailView]:
    return ok(
        _session_detail_view(
            service.get_session_detail(session_id, limit=limit),
        )
    )


def _summary_view(item: TokenUsageSummary) -> TokenUsageSummaryView:
    return TokenUsageSummaryView(
        session_count=item.session_count,
        call_count=item.call_count,
        prompt_tokens=item.prompt_tokens,
        completion_tokens=item.completion_tokens,
        total_tokens=item.total_tokens,
        estimated_count=item.estimated_count,
        provider_count=item.provider_count,
        agent_buckets=[_bucket_view(bucket) for bucket in item.agent_buckets],
        phase_buckets=[_bucket_view(bucket) for bucket in item.phase_buckets],
        model_buckets=[_bucket_view(bucket) for bucket in item.model_buckets],
        sessions=[_session_view(session) for session in item.sessions],
        recent_calls=[_call_view(call) for call in item.recent_calls],
    )


def _session_detail_view(item: TokenUsageSessionDetail) -> TokenUsageSessionDetailView:
    return TokenUsageSessionDetailView(
        session=_session_view(item.session),
        agent_buckets=[_bucket_view(bucket) for bucket in item.agent_buckets],
        phase_buckets=[_bucket_view(bucket) for bucket in item.phase_buckets],
        model_buckets=[_bucket_view(bucket) for bucket in item.model_buckets],
        calls=[_call_view(call) for call in item.calls],
    )


def _session_view(item: TokenUsageSessionSummary) -> TokenUsageSessionView:
    return TokenUsageSessionView(
        session_id=item.session_id,
        title=item.title,
        call_count=item.call_count,
        prompt_tokens=item.prompt_tokens,
        completion_tokens=item.completion_tokens,
        total_tokens=item.total_tokens,
        estimated_count=item.estimated_count,
        provider_count=item.provider_count,
        first_usage_at=item.first_usage_at,
        last_usage_at=item.last_usage_at,
        updated_at=item.updated_at,
    )


def _bucket_view(item: TokenUsageBucket) -> TokenUsageBucketView:
    return TokenUsageBucketView(
        key=item.key,
        call_count=item.call_count,
        prompt_tokens=item.prompt_tokens,
        completion_tokens=item.completion_tokens,
        total_tokens=item.total_tokens,
        estimated_count=item.estimated_count,
        provider_count=item.provider_count,
    )


def _call_view(item: TokenUsageCall) -> TokenUsageCallView:
    return TokenUsageCallView(
        event_id=item.event_id,
        session_id=item.session_id,
        session_title=item.session_title,
        agent_id=item.agent_id,
        run_id=item.run_id,
        parent_run_id=item.parent_run_id,
        api=item.api,
        operation=item.operation,
        mode=item.mode,
        phase=item.phase,
        round_index=item.round_index,
        model=item.model,
        prompt_tokens=item.prompt_tokens,
        completion_tokens=item.completion_tokens,
        total_tokens=item.total_tokens,
        estimated=item.estimated,
        usage_source=item.usage_source,
        message_count=item.message_count,
        tool_schema_count=item.tool_schema_count,
        returned_tool_call_count=item.returned_tool_call_count,
        content_chars=item.content_chars,
        reasoning_chars=item.reasoning_chars,
        created_at=item.created_at,
    )
