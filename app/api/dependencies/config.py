"""Configuration dependency providers."""

from __future__ import annotations

from functools import lru_cache

from app.core.settings import Settings

__all__ = ["get_settings"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.load()
