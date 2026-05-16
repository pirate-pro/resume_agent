"""Sparse search over retrieval index chunks."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from enum import Enum
from typing import Any

from app.core.errors import ValidationError
from app.core.time import to_app_iso
from app.retrieval.index_models import (
    RetrievalChunk,
    RetrievalChunkSensitivity,
    RetrievalChunkStatus,
    RetrievalIndexScope,
)
from app.retrieval.index_store import RetrievalIndexStore
from app.retrieval.models import RetrievalHit, RetrievalQuery, validate_source_type

__all__ = ["build_index_hits"]

_QUERY_TERM_RE = re.compile(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]{2,}")
_MAX_SNIPPET_FALLBACK = 500


def build_index_hits(index_store: RetrievalIndexStore, request: RetrievalQuery) -> list[RetrievalHit]:
    """Build retrieval hits from indexed chunks using deterministic sparse scoring."""

    if not isinstance(index_store, RetrievalIndexStore):
        raise ValidationError("index_store must be RetrievalIndexStore.")
    if not isinstance(request, RetrievalQuery):
        raise ValidationError("request must be RetrievalQuery.")
    hits: list[RetrievalHit] = []
    for chunk in index_store.list_chunks(include_archived=request.include_archived):
        if not request.allows(validate_source_type(chunk.source_type)):
            continue
        if not _is_chunk_allowed(chunk, request):
            continue
        score, reason = _score_chunk(chunk, request)
        if score <= 0:
            continue
        hits.append(
            RetrievalHit(
                source=chunk.source_ref.copy(),
                title=chunk.source_title,
                summary=_snippet(chunk.text, request.query, max_chars=min(request.max_snippet_chars, 500)),
                snippet=_snippet(chunk.text, request.query, max_chars=request.max_snippet_chars),
                tags=list(chunk.tags),
                score=score,
                match_reason=reason,
                updated_at=chunk.source_updated_at,
                evidence_refs=_evidence_refs(chunk),
                metadata={
                    "retrieval": "chunk",
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "source_updated_at": to_app_iso(chunk.source_updated_at),
                },
            )
        )
    hits.sort(
        key=lambda hit: (
            -hit.score,
            -hit.updated_at.timestamp(),
            validate_source_type(hit.source.source_type).value,
            hit.source.source_id,
        )
    )
    return [hit.copy() for hit in hits[: request.top_k]]


def _is_chunk_allowed(chunk: RetrievalChunk, request: RetrievalQuery) -> bool:
    if _status_value(chunk.status) != RetrievalChunkStatus.ACTIVE.value and not request.include_archived:
        return False
    sensitivity = _sensitivity_value(chunk.sensitivity)
    if sensitivity == RetrievalChunkSensitivity.SENSITIVE.value:
        return False
    scope = _scope_value(chunk.scope)
    if scope == RetrievalIndexScope.MEMORY_PRIVATE.value:
        return False
    if scope == RetrievalIndexScope.SESSION_ONLY.value:
        return chunk.source_ref.source_session_id == request.session_id
    return True


def _score_chunk(chunk: RetrievalChunk, request: RetrievalQuery) -> tuple[float, str]:
    query = request.query.casefold()
    searchable_text = _join_text(
        [
            chunk.source_title,
            chunk.text,
            chunk.source_id,
            chunk.source_ref.artifact_id,
            _metadata_text(chunk.metadata),
            *chunk.tags,
        ]
    ).casefold()
    score = 0.0
    reasons: list[str] = []
    if request.related_application_id is not None and request.related_application_id.casefold() in searchable_text:
        score += 0.32
        reasons.append("关联求职项目")
    terms = _query_terms(query)
    if not terms and request.related_application_id is None:
        return 0.08, "索引默认候选"
    title_text = chunk.source_title.casefold()
    tags_text = " ".join(tag.casefold() for tag in chunk.tags)
    body_text = chunk.text.casefold()
    for term in terms:
        if term in title_text:
            score += 0.2
            reasons.append(f"标题命中 {term}")
        if term in tags_text:
            score += 0.16
            reasons.append(f"标签命中 {term}")
        if term in body_text:
            score += 0.1
            reasons.append(f"片段命中 {term}")
        if term in chunk.source_id.casefold():
            score += 0.12
            reasons.append(f"来源命中 {term}")
    if len(query) >= 4 and query in body_text:
        score += 0.14
        reasons.append("片段命中完整查询")
    score += _source_type_weight(validate_source_type(chunk.source_type).value)
    score -= _length_penalty(chunk.token_estimate)
    if score <= 0:
        return 0.0, ""
    return min(round(score, 4), 1.0), "；".join(_dedupe(reasons)[:5]) or "索引召回"


def _source_type_weight(source_type: str) -> float:
    if source_type == "note":
        return 0.08
    if source_type in {"external_resource", "experience_post", "interview_question"}:
        return 0.07
    if source_type in {"company_profile", "skill_requirement"}:
        return 0.05
    if source_type == "session_artifact":
        return 0.04
    return 0.03


def _length_penalty(token_estimate: int) -> float:
    if token_estimate <= 700:
        return 0.0
    if token_estimate <= 1200:
        return 0.02
    return 0.04


def _snippet(value: str, query: str, *, max_chars: int) -> str:
    text = " ".join(value.split())
    resolved_max = max(min(max_chars, 5000), 80)
    if len(text) <= resolved_max:
        return text
    lowered = text.casefold()
    start = -1
    for term in _query_terms(query.casefold()):
        start = lowered.find(term)
        if start >= 0:
            break
    if start < 0:
        return text[: min(resolved_max, _MAX_SNIPPET_FALLBACK)].rstrip()
    left = max(start - resolved_max // 3, 0)
    right = min(left + resolved_max, len(text))
    return text[left:right].strip()


def _query_terms(query: str) -> list[str]:
    terms = [term.strip().casefold() for term in _QUERY_TERM_RE.findall(query) if term.strip()]
    return _dedupe([term for term in terms if len(term) >= 2])


def _metadata_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, dict):
        return _join_text([str(key), _metadata_text(item)] for key, item in value.items())
    if isinstance(value, list | tuple | set):
        return _join_text(_metadata_text(item) for item in value)
    return str(value)


def _evidence_refs(chunk: RetrievalChunk) -> list[str]:
    return _clean_strings([chunk.source_id, chunk.source_ref.artifact_id])


def _join_text(values: Iterable[Any]) -> str:
    return " ".join(_clean_strings(values))


def _clean_strings(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if isinstance(raw, list | tuple | set):
            candidates: Sequence[Any] = list(raw)
        else:
            candidates = [raw]
        for candidate in candidates:
            if candidate is None:
                continue
            item = str(candidate).strip()
            if not item or item in seen:
                continue
            output.append(item)
            seen.add(item)
    return output


def _dedupe(values: Sequence[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        output.append(value)
        seen.add(value)
    return output


def _status_value(value: RetrievalChunkStatus | str) -> str:
    if isinstance(value, RetrievalChunkStatus):
        return value.value
    return RetrievalChunkStatus(str(value)).value


def _scope_value(value: RetrievalIndexScope | str) -> str:
    if isinstance(value, RetrievalIndexScope):
        return value.value
    return RetrievalIndexScope(str(value)).value


def _sensitivity_value(value: RetrievalChunkSensitivity | str) -> str:
    if isinstance(value, RetrievalChunkSensitivity):
        return value.value
    return RetrievalChunkSensitivity(str(value)).value
