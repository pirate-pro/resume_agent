"""Retrieval service dependency providers."""

from __future__ import annotations

from functools import lru_cache

from app.api.dependencies.infrastructure import (
    get_career_product_store,
    get_knowledge_store,
    get_learning_store,
    get_note_store,
    get_retrieval_index_store,
    get_session_repository,
)
from app.retrieval.service import RetrievalService

__all__ = ["get_retrieval_service"]


@lru_cache(maxsize=1)
def get_retrieval_service() -> RetrievalService:
    return RetrievalService(
        career_store=get_career_product_store(),
        note_store=get_note_store(),
        knowledge_store=get_knowledge_store(),
        learning_store=get_learning_store(),
        session_repository=get_session_repository(),
        index_store=get_retrieval_index_store(),
    )
