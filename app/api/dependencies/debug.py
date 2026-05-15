"""Debug service dependency providers."""

from __future__ import annotations

from functools import lru_cache

from app.api.dependencies.infrastructure import get_session_repository
from app.debug.token_usage import TokenUsageDebugService

__all__ = ["get_token_usage_debug_service"]


@lru_cache(maxsize=1)
def get_token_usage_debug_service() -> TokenUsageDebugService:
    return TokenUsageDebugService(session_repository=get_session_repository())
