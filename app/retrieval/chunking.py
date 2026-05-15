"""Deterministic chunking for retrieval index projections."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.errors import ValidationError
from app.core.time import app_now, normalize_app_datetime
from app.retrieval.index_models import (
    RetrievalChunk,
    RetrievalChunkStatus,
    build_chunk_id,
    content_hash_for_text,
)
from app.retrieval.models import RetrievalSourceRef

__all__ = [
    "ChunkingOptions",
    "TextChunkSpan",
    "build_retrieval_chunks",
    "chunk_text",
    "estimate_tokens",
]

_TOKEN_RE = re.compile(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")
_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True, slots=True)
class ChunkingOptions:
    """Configuration for deterministic chunking."""

    target_tokens: int = 700
    max_tokens: int = 900
    overlap_tokens: int = 100
    min_chunk_tokens: int = 80

    def __post_init__(self) -> None:
        _validate_int_range("target_tokens", self.target_tokens, min_value=80, max_value=4000)
        _validate_int_range("max_tokens", self.max_tokens, min_value=self.target_tokens, max_value=6000)
        _validate_int_range("overlap_tokens", self.overlap_tokens, min_value=0, max_value=800)
        _validate_int_range("min_chunk_tokens", self.min_chunk_tokens, min_value=1, max_value=self.target_tokens)


@dataclass(frozen=True, slots=True)
class TextChunkSpan:
    """Text span produced by chunking with source character offsets."""

    chunk_index: int
    char_start: int
    char_end: int
    text: str
    token_estimate: int


@dataclass(frozen=True, slots=True)
class _Unit:
    start: int
    end: int
    text: str
    kind: str

    @property
    def token_estimate(self) -> int:
        return estimate_tokens(self.text)


def build_retrieval_chunks(
    *,
    text: str,
    source_ref: RetrievalSourceRef,
    source_title: str,
    source_updated_at: datetime,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    status: RetrievalChunkStatus | str = RetrievalChunkStatus.ACTIVE,
    options: ChunkingOptions | None = None,
    now: datetime | None = None,
) -> list[RetrievalChunk]:
    """Build retrieval chunks for one source text."""

    if not isinstance(source_ref, RetrievalSourceRef):
        raise ValidationError("source_ref must be RetrievalSourceRef.")
    normalized_title = _normalize_text("source_title", source_title, allow_empty=False)
    normalized_source_updated_at = normalize_app_datetime(source_updated_at)
    timestamp = normalize_app_datetime(now or app_now())
    spans = chunk_text(text, options=options)
    chunks: list[RetrievalChunk] = []
    for span in spans:
        chunk_id = build_chunk_id(
            source_type=source_ref.source_type,
            source_id=source_ref.source_id,
            chunk_index=span.chunk_index,
            text=span.text,
        )
        chunks.append(
            RetrievalChunk(
                chunk_id=chunk_id,
                source_type=source_ref.source_type,
                source_id=source_ref.source_id,
                source_ref=source_ref.copy(),
                source_title=normalized_title,
                source_updated_at=normalized_source_updated_at,
                content_hash=content_hash_for_text(span.text),
                chunk_index=span.chunk_index,
                char_start=span.char_start,
                char_end=span.char_end,
                text=span.text,
                token_estimate=span.token_estimate,
                tags=list(tags or []),
                metadata=dict(metadata or {}),
                status=status,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    return chunks


def chunk_text(text: str, *, options: ChunkingOptions | None = None) -> list[TextChunkSpan]:
    """Split markdown or plain text into deterministic retrieval chunks."""

    if not isinstance(text, str):
        raise ValidationError("text must be a string.")
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized_text.strip():
        return []
    resolved = options or ChunkingOptions()
    units = _split_markdown_units(normalized_text)
    spans = _build_spans(normalized_text, units, resolved)
    return [
        TextChunkSpan(
            chunk_index=index,
            char_start=span.char_start,
            char_end=span.char_end,
            text=span.text.strip(),
            token_estimate=estimate_tokens(span.text),
        )
        for index, span in enumerate(spans)
        if span.text.strip()
    ]


def estimate_tokens(text: str) -> int:
    """Return a deterministic rough token estimate for mixed Chinese/English text."""

    if not isinstance(text, str):
        raise ValidationError("text must be a string.")
    normalized = text.strip()
    if not normalized:
        return 0
    matches = _TOKEN_RE.findall(normalized)
    punctuation_cost = max(math.ceil((len(normalized) - sum(len(item) for item in matches)) / 8), 0)
    return max(len(matches) + punctuation_cost, 1)


def _build_spans(text: str, units: list[_Unit], options: ChunkingOptions) -> list[TextChunkSpan]:
    spans: list[TextChunkSpan] = []
    active_start: int | None = None
    active_end: int | None = None
    active_tokens = 0

    def flush() -> None:
        nonlocal active_start, active_end, active_tokens
        if active_start is None or active_end is None:
            return
        _append_span(spans, text, active_start, active_end)
        active_start = None
        active_end = None
        active_tokens = 0

    for unit in units:
        if not unit.text.strip():
            continue
        if unit.token_estimate > options.max_tokens:
            flush()
            spans.extend(_split_long_unit(text, unit, options))
            continue
        if active_start is None:
            active_start = unit.start
            active_end = unit.end
            active_tokens = unit.token_estimate
            continue
        next_tokens = estimate_tokens(text[active_start:unit.end])
        if next_tokens > options.max_tokens:
            flush()
            overlap_start = _overlap_start(text, spans[-1].char_start, spans[-1].char_end, options.overlap_tokens)
            active_start = min(overlap_start, unit.start)
            active_end = unit.end
            active_tokens = estimate_tokens(text[active_start:active_end])
            if active_tokens > options.max_tokens:
                flush()
                spans.extend(_split_long_unit(text, unit, options))
            continue
        active_end = unit.end
        active_tokens = next_tokens
        if active_tokens >= options.target_tokens:
            flush()
    flush()
    return _merge_tiny_tail(text, spans, options)


def _split_long_unit(text: str, unit: _Unit, options: ChunkingOptions) -> list[TextChunkSpan]:
    max_chars = _tokens_to_chars(options.max_tokens)
    overlap_chars = _tokens_to_chars(options.overlap_tokens)
    spans: list[TextChunkSpan] = []
    cursor = unit.start
    while cursor < unit.end:
        hard_end = min(unit.end, cursor + max_chars)
        end = _find_soft_break(text, cursor, hard_end, minimum=cursor + max(max_chars // 2, 1))
        if end <= cursor:
            end = hard_end
        while estimate_tokens(text[cursor:end]) > options.max_tokens and end > cursor + 1:
            next_end = cursor + max((end - cursor) * 4 // 5, 1)
            if next_end >= end:
                next_end = end - 1
            end = next_end
        _append_span(spans, text, cursor, end)
        if end >= unit.end:
            break
        cursor = max(end - overlap_chars, cursor + 1)
    return spans


def _merge_tiny_tail(text: str, spans: list[TextChunkSpan], options: ChunkingOptions) -> list[TextChunkSpan]:
    if len(spans) < 2:
        return spans
    tail = spans[-1]
    previous = spans[-2]
    if tail.token_estimate >= options.min_chunk_tokens:
        return spans
    merged_tokens = estimate_tokens(text[previous.char_start:tail.char_end])
    if merged_tokens > options.max_tokens:
        return spans
    merged = TextChunkSpan(
        chunk_index=previous.chunk_index,
        char_start=previous.char_start,
        char_end=tail.char_end,
        text=text[previous.char_start:tail.char_end].strip(),
        token_estimate=merged_tokens,
    )
    return [*spans[:-2], merged]


def _append_span(spans: list[TextChunkSpan], text: str, start: int, end: int) -> None:
    normalized_start, normalized_end = _trim_span(text, start, end)
    if normalized_end <= normalized_start:
        return
    span_text = text[normalized_start:normalized_end]
    spans.append(
        TextChunkSpan(
            chunk_index=len(spans),
            char_start=normalized_start,
            char_end=normalized_end,
            text=span_text.strip(),
            token_estimate=estimate_tokens(span_text),
        )
    )


def _split_markdown_units(text: str) -> list[_Unit]:
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)
    units: list[_Unit] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        start = offsets[index]
        if not line.strip():
            index += 1
            continue
        if _FENCE_RE.match(line):
            end_index = index + 1
            while end_index < len(lines):
                if _FENCE_RE.match(lines[end_index]):
                    end_index += 1
                    break
                end_index += 1
            end = offsets[end_index] if end_index < len(offsets) else len(text)
            units.append(_Unit(start=start, end=end, text=text[start:end], kind="code"))
            index = end_index
            continue
        if _TABLE_RE.match(line):
            end_index = index + 1
            while end_index < len(lines) and _TABLE_RE.match(lines[end_index]):
                end_index += 1
            end = offsets[end_index] if end_index < len(offsets) else len(text)
            units.append(_Unit(start=start, end=end, text=text[start:end], kind="table"))
            index = end_index
            continue
        if _HEADING_RE.match(line):
            end = offsets[index + 1] if index + 1 < len(offsets) else len(text)
            units.append(_Unit(start=start, end=end, text=text[start:end], kind="heading"))
            index += 1
            continue
        end_index = index + 1
        while end_index < len(lines):
            next_line = lines[end_index]
            if not next_line.strip() or _HEADING_RE.match(next_line) or _FENCE_RE.match(next_line) or _TABLE_RE.match(next_line):
                break
            end_index += 1
        end = offsets[end_index] if end_index < len(offsets) else len(text)
        units.append(_Unit(start=start, end=end, text=text[start:end], kind="paragraph"))
        index = end_index
    return units


def _find_soft_break(text: str, start: int, hard_end: int, *, minimum: int) -> int:
    window = text[start:hard_end]
    candidates = [
        window.rfind("\n\n"),
        window.rfind("\n"),
        window.rfind("。"),
        window.rfind(". "),
        window.rfind("；"),
        window.rfind("; "),
    ]
    best = max(candidates)
    if best <= 0:
        return hard_end
    end = start + best + 1
    return end if end >= minimum else hard_end


def _overlap_start(text: str, start: int, end: int, overlap_tokens: int) -> int:
    if overlap_tokens <= 0:
        return end
    overlap_chars = _tokens_to_chars(overlap_tokens)
    candidate = max(start, end - overlap_chars)
    soft = text.rfind("\n", start, candidate)
    return soft + 1 if soft >= start else candidate


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _tokens_to_chars(tokens: int) -> int:
    return max(tokens * 3, 1)


def _validate_int_range(field_name: str, value: int, *, min_value: int, max_value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{field_name} must be int.")
    if value < min_value or value > max_value:
        raise ValidationError(f"{field_name} must be in range {min_value}..{max_value}.")


def _normalize_text(field_name: str, value: str, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string.")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return normalized
