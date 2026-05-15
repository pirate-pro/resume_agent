"""Debug API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

__all__ = [
    "TokenUsageBucketView",
    "TokenUsageCallView",
    "TokenUsageSessionDetailView",
    "TokenUsageSessionView",
    "TokenUsageSummaryView",
]


class TokenUsageCallView(BaseModel):
    event_id: str
    session_id: str
    session_title: str
    agent_id: str
    run_id: str
    parent_run_id: str | None = None
    api: str
    operation: str
    mode: str
    phase: str
    round_index: int | None = None
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated: bool
    usage_source: str
    message_count: int
    tool_schema_count: int
    returned_tool_call_count: int
    content_chars: int
    reasoning_chars: int
    created_at: datetime


class TokenUsageBucketView(BaseModel):
    key: str
    call_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_count: int
    provider_count: int


class TokenUsageSessionView(BaseModel):
    session_id: str
    title: str
    call_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_count: int
    provider_count: int
    first_usage_at: datetime | None = None
    last_usage_at: datetime | None = None
    updated_at: datetime


class TokenUsageSummaryView(BaseModel):
    session_count: int
    call_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_count: int
    provider_count: int
    agent_buckets: list[TokenUsageBucketView]
    phase_buckets: list[TokenUsageBucketView]
    model_buckets: list[TokenUsageBucketView]
    sessions: list[TokenUsageSessionView]
    recent_calls: list[TokenUsageCallView]


class TokenUsageSessionDetailView(BaseModel):
    session: TokenUsageSessionView
    agent_buckets: list[TokenUsageBucketView]
    phase_buckets: list[TokenUsageBucketView]
    model_buckets: list[TokenUsageBucketView]
    calls: list[TokenUsageCallView]
