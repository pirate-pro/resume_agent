"""Tests for building retrieval index projections from fact sources."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from app.core.time import APP_TIMEZONE
from app.domain.models import SessionArtifact
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.knowledge.models import (
    ExternalResource,
    InterviewDifficulty,
    InterviewQuestion,
    KnowledgeRecordStatus,
    QuestionType,
    ResourceType,
)
from app.knowledge.store import KnowledgeStore
from app.notes.models import Note, NoteOrigin, NoteRecordStatus, NoteType
from app.notes.store import NoteStore
from app.retrieval.chunking import ChunkingOptions
from app.retrieval.index_models import RetrievalChunkSensitivity, RetrievalChunkStatus, RetrievalIndexScope
from app.retrieval.index_store import RetrievalIndexStore
from app.retrieval.indexer import RetrievalIndexer
from app.retrieval.models import RetrievalSourceType

__all__ = []


class _Clock:
    def __init__(self) -> None:
        self._value = datetime(2026, 5, 16, 14, 0, tzinfo=APP_TIMEZONE)

    def __call__(self) -> datetime:
        current = self._value
        self._value = self._value + timedelta(minutes=1)
        return current


def test_retrieval_indexer_syncs_notes_and_archives_inactive_notes(tmp_path: Path) -> None:
    clock = _Clock()
    note_store = NoteStore(root_dir=tmp_path / "notes", clock=clock)
    index_store = RetrievalIndexStore(root_dir=tmp_path / "retrieval_index", clock=clock)
    indexer = _indexer(index_store, clock)
    note_store.save_note(_note())

    result = indexer.sync_notes(note_store)

    assert result.source_count == 1
    assert result.indexed_source_ids == ["note_rag_review"]
    chunks = index_store.list_chunks(source_type=RetrievalSourceType.NOTE, source_id="note_rag_review")
    assert chunks
    assert chunks[0].scope == RetrievalIndexScope.USER_PRIVATE
    assert chunks[0].sensitivity == RetrievalChunkSensitivity.PRIVATE
    assert chunks[0].metadata["note_type"] == "learning"
    assert chunks[0].metadata["origin"] == "user"
    assert "用户手写" in chunks[0].text
    assert "RAG chunk 策略" in chunks[0].text

    note_store.archive_note("note_rag_review")
    archived_result = indexer.sync_notes(note_store)

    assert archived_result.archived_source_ids == ["note_rag_review"]
    assert index_store.list_chunks(source_type=RetrievalSourceType.NOTE, source_id="note_rag_review") == []
    archived_chunks = index_store.list_chunks(
        include_archived=True,
        source_type=RetrievalSourceType.NOTE,
        source_id="note_rag_review",
    )
    assert archived_chunks
    assert all(chunk.status == RetrievalChunkStatus.ARCHIVED for chunk in archived_chunks)


def test_retrieval_indexer_syncs_knowledge_records_with_user_library_scope(tmp_path: Path) -> None:
    clock = _Clock()
    knowledge_store = KnowledgeStore(root_dir=tmp_path / "knowledge", clock=clock)
    index_store = RetrievalIndexStore(root_dir=tmp_path / "retrieval_index", clock=clock)
    indexer = _indexer(index_store, clock)
    knowledge_store.save_external_resource(_external_resource())
    knowledge_store.save_interview_question(_interview_question())

    result = indexer.sync_knowledge(knowledge_store)

    assert result.source_count == 2
    assert set(result.indexed_source_ids) == {"resource_stargazer_rag", "question_rag_chunk_strategy"}
    chunks = index_store.list_chunks(include_archived=True)
    assert chunks
    assert {chunk.source_type for chunk in chunks} == {
        RetrievalSourceType.EXTERNAL_RESOURCE,
        RetrievalSourceType.INTERVIEW_QUESTION,
    }
    assert all(chunk.scope == RetrievalIndexScope.USER_LIBRARY for chunk in chunks)
    assert all(chunk.sensitivity == RetrievalChunkSensitivity.INTERNAL for chunk in chunks)
    joined = "\n".join(chunk.text for chunk in chunks)
    assert "星河智能 RAG 面经" in joined
    assert "召回评估" in joined
    assert "chunk 策略如何设计" in joined


def test_retrieval_indexer_syncs_session_artifacts_and_archives_not_ready_artifacts(tmp_path: Path) -> None:
    clock = _Clock()
    repository = JsonlSessionRepository(tmp_path / "data")
    repository.create_session("sess_alpha")
    ready = _session_artifact(
        repository,
        artifact_id="artifact_rag_note",
        status="ready",
        text="这是一份 RAG 学习资料，包含 chunk 策略、召回评估和失败恢复。",
    )
    repository.add_or_update_session_artifact(ready)
    failed = _session_artifact(
        repository,
        artifact_id="artifact_failed_note",
        status="failed",
        text="不会被索引",
    )
    repository.add_or_update_session_artifact(failed)
    index_store = RetrievalIndexStore(root_dir=tmp_path / "retrieval_index", clock=clock)
    indexer = _indexer(index_store, clock)

    result = indexer.sync_session_artifacts(repository, session_id="sess_alpha")

    assert result.source_count == 2
    assert result.indexed_source_ids == ["artifact_rag_note"]
    assert result.archived_source_ids == ["artifact_failed_note"]
    chunks = index_store.list_chunks(source_type=RetrievalSourceType.SESSION_ARTIFACT)
    assert len({chunk.source_id for chunk in chunks}) == 1
    assert chunks[0].source_id == "artifact_rag_note"
    assert chunks[0].scope == RetrievalIndexScope.SESSION_ONLY
    assert chunks[0].source_ref.artifact_id == "artifact_rag_note"
    assert "召回评估" in chunks[0].text

    repository.add_or_update_session_artifact(
        _session_artifact(
            repository,
            artifact_id="artifact_rag_note",
            status="failed",
            text="这份资料已经解析失败",
        )
    )
    indexer.sync_session_artifacts(repository, session_id="sess_alpha")

    assert index_store.list_chunks(source_type=RetrievalSourceType.SESSION_ARTIFACT) == []
    archived_chunks = index_store.list_chunks(
        include_archived=True,
        source_type=RetrievalSourceType.SESSION_ARTIFACT,
        source_id="artifact_rag_note",
    )
    assert archived_chunks
    assert all(chunk.status == RetrievalChunkStatus.ARCHIVED for chunk in archived_chunks)


def _indexer(index_store: RetrievalIndexStore, clock: _Clock) -> RetrievalIndexer:
    return RetrievalIndexer(
        index_store=index_store,
        chunking_options=ChunkingOptions(target_tokens=80, max_tokens=120, overlap_tokens=10, min_chunk_tokens=10),
        clock=clock,
    )


def _note() -> Note:
    now = datetime(2026, 5, 16, 13, 0, tzinfo=APP_TIMEZONE)
    return Note(
        note_id="note_rag_review",
        status=NoteRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=None,
        evidence_refs=["sess_alpha"],
        created_at=now,
        updated_at=now,
        title="RAG 复盘",
        body_markdown="RAG chunk 策略要说明标题切分、overlap、召回评估和失败恢复。",
        note_type=NoteType.LEARNING,
        origin=NoteOrigin.USER,
        tags=["RAG", "检索"],
        summary="学习 RAG 检索质量评估。",
    )


def _external_resource() -> ExternalResource:
    now = datetime(2026, 5, 16, 13, 0, tzinfo=APP_TIMEZONE)
    return ExternalResource(
        resource_id="resource_stargazer_rag",
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=None,
        evidence_refs=["sess_alpha"],
        created_at=now,
        updated_at=now,
        title="星河智能 RAG 面经",
        resource_type=ResourceType.PASTED_TEXT,
        provider="用户导入",
        company="星河智能",
        position="AI Agent 后端工程师",
        target_roles=["AI Agent 后端工程师"],
        skill_tags=["RAG", "Agent", "FastAPI"],
        summary="面试重点关注 RAG 召回评估和 Agent 工程化。",
        key_points=["准备 chunk 策略", "解释 recall@5", "说明失败恢复"],
    )


def _interview_question() -> InterviewQuestion:
    now = datetime(2026, 5, 16, 13, 0, tzinfo=APP_TIMEZONE)
    return InterviewQuestion(
        question_id="question_rag_chunk_strategy",
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=None,
        evidence_refs=["sess_alpha"],
        created_at=now,
        updated_at=now,
        question_text="RAG 的 chunk 策略如何设计？",
        question_type=QuestionType.SYSTEM_DESIGN,
        difficulty=InterviewDifficulty.MEDIUM,
        skill_tags=["RAG", "检索"],
        company="星河智能",
        position="AI Agent 后端工程师",
        answer_outline="说明标题切分、段落切分、overlap、召回评估和引用追踪。",
        evaluation_points=["能解释 chunk 大小", "能说明召回评估"],
        common_pitfalls=["只谈 embedding，不谈质量评估"],
    )


def _session_artifact(
    repository: JsonlSessionRepository,
    *,
    artifact_id: str,
    status: str,
    text: str,
) -> SessionArtifact:
    now = datetime(2026, 5, 16, 13, 0, tzinfo=APP_TIMEZONE)
    root = repository.get_session_root_path("sess_alpha")
    artifact_dir = root / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    storage_path = artifact_dir / "original.txt"
    text_path = artifact_dir / "parsed.txt"
    storage_path.write_text(text, encoding="utf-8")
    text_path.write_text(text, encoding="utf-8")
    return SessionArtifact(
        artifact_id=artifact_id,
        session_id="sess_alpha",
        kind="uploaded_file",
        title=f"{artifact_id}.txt",
        media_type="text/plain",
        size_bytes=len(text.encode("utf-8")),
        status=status,
        visibility="session_shared",
        created_at=now,
        updated_at=now,
        storage_relpath=str(storage_path.relative_to(root)),
        text_relpath=str(text_path.relative_to(root)) if status == "ready" else None,
        description="测试资料",
        source_type="upload",
        text_char_count=len(text),
        token_estimate=20,
        parsed_at=now if status == "ready" else None,
    )
