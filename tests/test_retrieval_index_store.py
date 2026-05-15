"""Tests for the retrieval index store."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core.errors import StorageError, ValidationError
from app.core.time import APP_TIMEZONE
from app.retrieval.chunking import ChunkingOptions, build_retrieval_chunks
from app.retrieval.index_models import RetrievalChunk, RetrievalChunkStatus
from app.retrieval.index_store import RetrievalIndexStore
from app.retrieval.models import RetrievalSourceRef, RetrievalSourceType

__all__ = []


class _Clock:
    def __init__(self) -> None:
        self._value = datetime(2026, 5, 15, 10, 0, tzinfo=APP_TIMEZONE)

    def __call__(self) -> datetime:
        current = self._value
        self._value = self._value + timedelta(minutes=1)
        return current


def test_retrieval_index_store_replaces_and_lists_source_chunks(tmp_path: Path) -> None:
    clock = _Clock()
    store = RetrievalIndexStore(root_dir=tmp_path / "retrieval_index", clock=clock)
    chunks = _chunks(
        source_type=RetrievalSourceType.NOTE,
        source_id="note_rag_review",
        text="RAG chunk 策略。 " * 120,
    )

    saved = store.replace_source_chunks(
        source_type=RetrievalSourceType.NOTE,
        source_id="note_rag_review",
        chunks=chunks,
    )
    reloaded = RetrievalIndexStore(root_dir=tmp_path / "retrieval_index", clock=clock)
    listed = reloaded.list_chunks(source_type="note", source_id="note_rag_review")

    assert [chunk.chunk_id for chunk in listed] == [chunk.chunk_id for chunk in saved]
    assert all(chunk.created_at <= chunk.updated_at for chunk in listed)
    assert reloaded.get_chunk(saved[0].chunk_id) is not None
    manifest = reloaded.read_manifest()
    assert manifest["chunk_count"] == len(saved)
    assert manifest["active_chunk_count"] == len(saved)
    assert manifest["source_count"] == 1


def test_retrieval_index_store_replacement_is_per_source_and_can_delete(tmp_path: Path) -> None:
    store = RetrievalIndexStore(root_dir=tmp_path / "retrieval_index", clock=_Clock())
    note_chunks = _chunks(
        source_type=RetrievalSourceType.NOTE,
        source_id="note_rag_review",
        text="RAG 复盘。 " * 80,
    )
    question_chunks = _chunks(
        source_type=RetrievalSourceType.INTERVIEW_QUESTION,
        source_id="question_rag_chunk_strategy",
        text="RAG chunk 策略如何设计？ " * 80,
    )
    store.replace_source_chunks(
        source_type=RetrievalSourceType.NOTE,
        source_id="note_rag_review",
        chunks=note_chunks,
    )
    store.replace_source_chunks(
        source_type=RetrievalSourceType.INTERVIEW_QUESTION,
        source_id="question_rag_chunk_strategy",
        chunks=question_chunks,
    )

    store.replace_source_chunks(
        source_type=RetrievalSourceType.NOTE,
        source_id="note_rag_review",
        chunks=[],
    )

    assert store.list_chunks(source_type=RetrievalSourceType.NOTE) == []
    assert store.list_chunks(source_type=RetrievalSourceType.INTERVIEW_QUESTION)


def test_retrieval_index_store_archives_source_chunks(tmp_path: Path) -> None:
    store = RetrievalIndexStore(root_dir=tmp_path / "retrieval_index", clock=_Clock())
    chunks = _chunks(
        source_type=RetrievalSourceType.EXTERNAL_RESOURCE,
        source_id="resource_stargazer_interview",
        text="星河智能面经会问 RAG 评估。 " * 100,
    )
    saved = store.replace_source_chunks(
        source_type=RetrievalSourceType.EXTERNAL_RESOURCE,
        source_id="resource_stargazer_interview",
        chunks=chunks,
    )

    archived = store.archive_source_chunks(
        source_type=RetrievalSourceType.EXTERNAL_RESOURCE,
        source_id="resource_stargazer_interview",
    )

    assert [chunk.chunk_id for chunk in archived] == [chunk.chunk_id for chunk in saved]
    assert store.list_chunks(source_type=RetrievalSourceType.EXTERNAL_RESOURCE) == []
    all_chunks = store.list_chunks(
        include_archived=True,
        source_type=RetrievalSourceType.EXTERNAL_RESOURCE,
    )
    assert all(chunk.status == RetrievalChunkStatus.ARCHIVED for chunk in all_chunks)


def test_retrieval_index_store_rejects_cross_source_replacement(tmp_path: Path) -> None:
    store = RetrievalIndexStore(root_dir=tmp_path / "retrieval_index", clock=_Clock())
    chunks = _chunks(
        source_type=RetrievalSourceType.NOTE,
        source_id="note_rag_review",
        text="RAG 复盘。 " * 80,
    )

    with pytest.raises(ValidationError):
        store.replace_source_chunks(
            source_type=RetrievalSourceType.NOTE,
            source_id="note_other",
            chunks=chunks,
        )


def test_retrieval_index_store_fails_stably_on_corrupted_jsonl(tmp_path: Path) -> None:
    store = RetrievalIndexStore(root_dir=tmp_path / "retrieval_index", clock=_Clock())
    (tmp_path / "retrieval_index" / "chunks.jsonl").write_text("{bad json", encoding="utf-8")

    with pytest.raises(StorageError):
        store.list_chunks()


def _chunks(
    *,
    source_type: RetrievalSourceType,
    source_id: str,
    text: str,
) -> list[RetrievalChunk]:
    now = datetime(2026, 5, 15, 9, 0, tzinfo=APP_TIMEZONE)
    return build_retrieval_chunks(
        text=text,
        source_ref=RetrievalSourceRef(source_type=source_type, source_id=source_id, source_session_id="sess_alpha"),
        source_title=source_id,
        source_updated_at=now,
        tags=["RAG"],
        metadata={"fixture": True},
        options=ChunkingOptions(target_tokens=80, max_tokens=120, overlap_tokens=10, min_chunk_tokens=10),
        now=now,
    )
