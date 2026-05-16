"""Tests for sparse search over retrieval index chunks."""

from __future__ import annotations

from pathlib import Path

from app.retrieval.chunking import ChunkingOptions
from app.retrieval.index_store import RetrievalIndexStore
from app.retrieval.indexer import RetrievalIndexer
from app.retrieval.models import RetrievalQuery, RetrievalSourceType
from app.retrieval.search import build_index_hits
from app.retrieval.service import RetrievalService
from tests.test_retrieval_service import RetrievalStores, _add_artifact, _seed_stores

__all__ = []


def test_sparse_index_search_returns_source_hits_with_chunk_metadata(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    index_store = _build_index(tmp_path, stores)

    hits = build_index_hits(
        index_store,
        RetrievalQuery(
            query="chunk 策略 召回评估",
            session_id="sess_alpha",
            top_k=20,
        ),
    )

    assert hits
    source_ids = {hit.source.source_id for hit in hits}
    assert {"note_rag_review", "resource_stargazer_interview", "question_rag_chunk_strategy"} <= source_ids
    assert all(hit.metadata["retrieval"] == "chunk" for hit in hits)
    assert all(str(hit.metadata["chunk_id"]).startswith("chunk_") for hit in hits)
    assert all(hit.source.source_type != "rag_chunk" for hit in hits)
    assert any("chunk" in hit.snippet.casefold() for hit in hits)
    assert not any("path" in str(hit.to_payload()).casefold() for hit in hits)


def test_sparse_index_search_respects_source_type_and_session_only_scope(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    _add_artifact(
        stores.sessions,
        "sess_beta",
        "artifact_beta_rag",
        "星河智能 RAG 跨会话资料，包含 chunk 策略和召回评估。",
    )
    index_store = RetrievalIndexStore(root_dir=tmp_path / "retrieval_index")
    indexer = _indexer(index_store)
    indexer.sync_session_artifacts(stores.sessions, session_id="sess_alpha")
    indexer.sync_session_artifacts(stores.sessions, session_id="sess_beta")

    alpha_hits = build_index_hits(
        index_store,
        RetrievalQuery(
            query="RAG chunk 策略",
            session_id="sess_alpha",
            source_types=[RetrievalSourceType.SESSION_ARTIFACT],
            top_k=10,
        ),
    )
    beta_hits = build_index_hits(
        index_store,
        RetrievalQuery(
            query="RAG chunk 策略",
            session_id="sess_beta",
            source_types=[RetrievalSourceType.SESSION_ARTIFACT],
            top_k=10,
        ),
    )

    assert {hit.source.source_id for hit in alpha_hits} == {"artifact_alpha_jd"}
    assert {hit.source.source_id for hit in beta_hits} == {"artifact_beta_rag"}


def test_retrieval_service_fuses_index_hits_without_new_source_type(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    index_store = _build_index(tmp_path, stores)
    service = RetrievalService(index_store=index_store)

    hits = service.search(
        RetrievalQuery(
            query="RAG chunk 策略 失败恢复",
            session_id="sess_alpha",
            top_k=10,
        )
    )
    pack = service.build_context_pack(
        RetrievalQuery(
            query="RAG chunk 策略 失败恢复",
            session_id="sess_alpha",
            top_k=10,
            max_chars=2000,
        )
    )

    assert hits
    assert {hit.source.source_type for hit in hits} >= {
        RetrievalSourceType.NOTE,
        RetrievalSourceType.EXTERNAL_RESOURCE,
        RetrievalSourceType.INTERVIEW_QUESTION,
    }
    assert all(hit.metadata.get("retrieval") == "chunk" for hit in hits)
    assert all(hit.source.source_type != "rag_chunk" for hit in hits)
    assert pack.grouped_context["notes"]
    assert pack.grouped_context["knowledge"]
    assert {item.source_id for item in pack.citations} == {hit.source.source_id for hit in pack.hits}


def _build_index(tmp_path: Path, stores: RetrievalStores) -> RetrievalIndexStore:
    index_store = RetrievalIndexStore(root_dir=tmp_path / "retrieval_index")
    indexer = _indexer(index_store)
    indexer.sync_notes(stores.notes)
    indexer.sync_knowledge(stores.knowledge)
    indexer.sync_session_artifacts(stores.sessions, session_id="sess_alpha")
    return index_store


def _indexer(index_store: RetrievalIndexStore) -> RetrievalIndexer:
    return RetrievalIndexer(
        index_store=index_store,
        chunking_options=ChunkingOptions(target_tokens=80, max_tokens=120, overlap_tokens=10, min_chunk_tokens=10),
    )
