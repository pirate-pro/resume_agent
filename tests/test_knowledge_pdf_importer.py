"""Tests for importing PDF files into external knowledge and RAG index."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.knowledge.models import ResourceType
from app.knowledge.pdf_importer import KnowledgePdfImporter
from app.knowledge.store import KnowledgeStore
from app.retrieval.index_store import RetrievalIndexStore
from app.retrieval.models import RetrievalQuery, RetrievalSourceType
from app.retrieval.search import build_index_hits

__all__ = []


def test_knowledge_pdf_importer_creates_artifact_resource_and_index(tmp_path: Path) -> None:
    pdf_path = tmp_path / "代码随想录知识星球精华-Cpp篇.pdf"
    _write_minimal_pdf(
        pdf_path,
        "RAG chunk strategy recall evaluation failure recovery Cpp interview notes",
    )
    session_repository = JsonlSessionRepository(data_dir=tmp_path / "data")
    knowledge_store = KnowledgeStore(root_dir=tmp_path / "knowledge")
    index_store = RetrievalIndexStore(root_dir=tmp_path / "retrieval_index")
    importer = KnowledgePdfImporter(
        session_repository=session_repository,
        knowledge_store=knowledge_store,
        retrieval_index_store=index_store,
    )

    result = importer.import_pdf(
        pdf_path,
        session_id="sess_knowledge_import",
        skill_tags=["RAG"],
        target_roles=["AI 后端工程师"],
    )

    artifact = session_repository.get_session_artifact(result.session_id, result.artifact_id)
    resource = knowledge_store.get_external_resource(result.resource_id)
    chunks = index_store.list_chunks(
        source_type=RetrievalSourceType.EXTERNAL_RESOURCE,
        source_id=result.resource_id,
    )
    hits = build_index_hits(
        index_store,
        RetrievalQuery(
            query="RAG chunk strategy recall evaluation",
            session_id="sess_knowledge_import",
            top_k=5,
        ),
    )

    assert artifact is not None
    assert artifact.status == "ready"
    assert artifact.text_relpath is not None
    assert artifact.media_type == "application/pdf"
    assert resource is not None
    assert resource.resource_type == ResourceType.UPLOADED_FILE
    assert resource.raw_artifact_id == result.artifact_id
    assert resource.source_artifact_id == result.artifact_id
    assert "C++" in resource.skill_tags
    assert "RAG" in resource.skill_tags
    assert resource.target_roles == ["AI 后端工程师"]
    assert result.text_char_count > 0
    assert chunks
    assert any("RAG chunk strategy" in chunk.text for chunk in chunks)
    assert {hit.source.source_id for hit in hits} == {result.resource_id}


def test_knowledge_pdf_importer_rejects_non_pdf(tmp_path: Path) -> None:
    path = tmp_path / "resource.txt"
    path.write_text("not pdf", encoding="utf-8")
    importer = KnowledgePdfImporter(
        session_repository=JsonlSessionRepository(data_dir=tmp_path / "data"),
        knowledge_store=KnowledgeStore(root_dir=tmp_path / "knowledge"),
        retrieval_index_store=RetrievalIndexStore(root_dir=tmp_path / "retrieval_index"),
    )

    with pytest.raises(ValidationError, match="only supports PDF"):
        importer.import_pdf(path)


def _write_minimal_pdf(path: Path, text: str) -> None:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(f'BT /F1 14 Tf 72 720 Td ({escaped}) Tj ET'.encode('latin-1'))} >>\n"
        f"stream\nBT /F1 14 Tf 72 720 Td ({escaped}) Tj ET\nendstream".encode("latin-1"),
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{index} 0 obj\n".encode("latin-1"))
        content.extend(obj)
        content.extend(b"\nendobj\n")
    xref_offset = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
    content.extend(
        f"trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("latin-1")
    )
    path.write_bytes(bytes(content))
