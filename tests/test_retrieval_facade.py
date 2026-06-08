"""Tests for shared retrieval tool facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.errors import ValidationError
from app.retrieval.facade import (
    RetrievalPrincipal,
    RetrievalToolInput,
    build_retrieval_query,
    retrieval_search_payload,
    retrieval_tool_input_from_arguments,
)
from tests.test_retrieval_service import _seed_stores, _service

__all__ = []


def test_retrieval_facade_rejects_model_owned_session_and_path_fields() -> None:
    with pytest.raises(ValidationError, match="Store-owned fields are not accepted"):
        retrieval_tool_input_from_arguments({"query": "星河智能", "session_id": "sess_alpha"})

    with pytest.raises(ValidationError, match="Path arguments are not allowed"):
        retrieval_tool_input_from_arguments({"query": "星河智能", "file_path": "/tmp/source.txt"})


def test_retrieval_facade_expands_external_query_without_session_artifacts() -> None:
    request = build_retrieval_query(
        RetrievalToolInput(query="星河智能 RAG"),
        principal=RetrievalPrincipal(session_id=None),
    )

    assert request.session_id == "sess_external_no_session"
    assert request.source_types
    assert "session_artifact" not in [source_type.value for source_type in request.source_types]


def test_retrieval_facade_rejects_explicit_session_artifact_without_app_session() -> None:
    with pytest.raises(ValidationError, match="session_artifact retrieval requires an app session"):
        build_retrieval_query(
            RetrievalToolInput(query="星河智能 RAG", source_types=["artifacts"]),
            principal=RetrievalPrincipal(session_id=None),
        )


def test_retrieval_facade_external_payload_omits_session_and_paths(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    payload = retrieval_search_payload(
        _service(stores),
        RetrievalToolInput(query="星河智能 RAG", top_k=20),
        principal=RetrievalPrincipal(session_id=None),
    )
    source_types = {hit["source"]["source_type"] for hit in payload["hits"]}

    assert "session_id" not in payload
    assert "session_artifact" not in source_types
    assert not _contains_path_key(payload)


def _contains_path_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if "path" in str(key).lower() or "relpath" in str(key).lower():
                return True
            if _contains_path_key(item):
                return True
    if isinstance(value, list):
        return any(_contains_path_key(item) for item in value)
    return False
