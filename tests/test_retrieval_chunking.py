"""Tests for deterministic retrieval chunking."""

from __future__ import annotations

from datetime import datetime

from app.core.time import APP_TIMEZONE
from app.retrieval.chunking import ChunkingOptions, build_retrieval_chunks, chunk_text, estimate_tokens
from app.retrieval.index_models import RetrievalChunkStatus
from app.retrieval.models import RetrievalSourceRef, RetrievalSourceType

__all__ = []


def test_markdown_chunking_preserves_code_blocks_and_offsets() -> None:
    text = """# RAG 复盘

## Chunk 策略
RAG chunk 策略要说明标题切分、段落切分、overlap、召回评估。

```python
def split_text(value):
    return value.split("\\n\\n")
```

| 指标 | 说明 |
| --- | --- |
| recall@5 | 命中预期来源 |

## 失败恢复
需要说明索引可重建，损坏 JSON 稳定失败。
"""

    spans = chunk_text(
        text,
        options=ChunkingOptions(
            target_tokens=80,
            max_tokens=120,
            overlap_tokens=10,
            min_chunk_tokens=10,
        ),
    )

    assert spans
    assert all(span.text == text[span.char_start : span.char_end].strip() for span in spans)
    code_hits = [span for span in spans if "def split_text" in span.text]
    assert len(code_hits) == 1
    assert "```python" in code_hits[0].text
    assert "```" in code_hits[0].text.split("def split_text", 1)[1]
    assert any("| recall@5 |" in span.text for span in spans)


def test_long_text_chunking_uses_overlap_and_token_bounds() -> None:
    text = " ".join(["RAG chunk 策略 召回评估 失败恢复 多 Agent 工程化"] * 180)
    options = ChunkingOptions(
        target_tokens=80,
        max_tokens=110,
        overlap_tokens=15,
        min_chunk_tokens=20,
    )

    spans = chunk_text(text, options=options)

    assert len(spans) > 3
    assert all(span.token_estimate <= options.max_tokens + 2 for span in spans)
    assert spans[1].char_start < spans[0].char_end
    assert all(spans[index].char_start < spans[index].char_end for index in range(len(spans)))


def test_build_retrieval_chunks_sets_source_refs_and_stable_ids() -> None:
    source_ref = RetrievalSourceRef(
        source_type=RetrievalSourceType.NOTE,
        source_id="note_rag_review",
        source_session_id="sess_alpha",
        artifact_id="artifact_note_raw",
    )
    now = datetime(2026, 5, 15, 9, 30, tzinfo=APP_TIMEZONE)
    text = "RAG chunk 策略要可解释。\n\n召回评估要有 recall@5 和 citation_valid。"

    chunks = build_retrieval_chunks(
        text=text,
        source_ref=source_ref,
        source_title="RAG 复盘",
        source_updated_at=now,
        tags=["RAG", "面试复盘"],
        metadata={"note_type": "learning"},
        options=ChunkingOptions(target_tokens=80, max_tokens=120, overlap_tokens=10, min_chunk_tokens=10),
        now=now,
    )
    rebuilt = build_retrieval_chunks(
        text=text,
        source_ref=source_ref,
        source_title="RAG 复盘",
        source_updated_at=now,
        tags=["RAG", "面试复盘"],
        metadata={"note_type": "learning"},
        options=ChunkingOptions(target_tokens=80, max_tokens=120, overlap_tokens=10, min_chunk_tokens=10),
        now=now,
    )

    assert [chunk.chunk_id for chunk in chunks] == [chunk.chunk_id for chunk in rebuilt]
    assert chunks[0].chunk_id.startswith("chunk_note_note_rag_review_")
    assert chunks[0].source_ref.source_session_id == "sess_alpha"
    assert chunks[0].status == RetrievalChunkStatus.ACTIVE
    assert chunks[0].token_estimate == estimate_tokens(chunks[0].text)
    assert chunks[0].metadata == {"note_type": "learning"}


def test_chunk_text_ignores_blank_input() -> None:
    assert chunk_text(" \n\n ") == []
