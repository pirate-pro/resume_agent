"""Model client dependency providers."""

from __future__ import annotations

from functools import lru_cache

from app.api.dependencies.config import get_settings
from app.infra.llm.openai_compatible_client import OpenAICompatibleClient

__all__ = ["get_maintenance_model_client", "get_model_client"]


@lru_cache(maxsize=1)
def get_model_client() -> OpenAICompatibleClient:
    settings = get_settings()
    return OpenAICompatibleClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


@lru_cache(maxsize=1)
def get_maintenance_model_client() -> OpenAICompatibleClient:
    settings = get_settings()
    return OpenAICompatibleClient(
        base_url=settings.maintenance_llm_base_url or settings.llm_base_url,
        api_key=settings.maintenance_llm_api_key or settings.llm_api_key,
        model=settings.maintenance_llm_model or settings.llm_model,
        timeout_seconds=settings.maintenance_llm_timeout_seconds or settings.llm_timeout_seconds,
    )
