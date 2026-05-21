"""Rule-based retrieval service over product stores."""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.career.store import CareerProductStore
from app.domain.protocols import SessionRepository
from app.knowledge.store import KnowledgeStore
from app.learning.store import LearningStore
from app.notes.store import NoteStore
from app.retrieval.adapters import (
    build_career_hits,
    build_knowledge_hits,
    build_learning_hits,
    build_note_hits,
    build_session_artifact_hits,
)
from app.retrieval.index_store import RetrievalIndexStore
from app.retrieval.models import (
    ContextPack,
    RetrievalHit,
    RetrievalQuery,
    group_for_source_type,
    validate_source_type,
)
from app.retrieval.search import build_index_hits

__all__ = ["RetrievalService"]


@dataclass(slots=True)
class RetrievalService:
    """Read-only service that recalls product context and builds context packs."""

    career_store: CareerProductStore | None = None
    note_store: NoteStore | None = None
    knowledge_store: KnowledgeStore | None = None
    learning_store: LearningStore | None = None
    session_repository: SessionRepository | None = None
    index_store: RetrievalIndexStore | None = None

    def search(self, request: RetrievalQuery) -> list[RetrievalHit]:
        """Return ranked retrieval hits."""

        hits = self._collect_hits(request)
        ranked = _rank_hits(hits)
        return [hit.copy() for hit in ranked[: request.top_k]]

    def build_context_pack(self, request: RetrievalQuery) -> ContextPack:
        """Return a budgeted context pack grouped by product source."""

        candidates = _rank_hits(self._collect_hits(request))
        candidates = _rank_hits(self._expand_project_context(request, candidates))
        selected: list[RetrievalHit] = []
        omitted: list[RetrievalHit] = []
        per_type_counts: dict[str, int] = {}
        used_chars = 0
        for index, hit in enumerate(candidates):
            source_type = validate_source_type(hit.source.source_type).value
            count = per_type_counts.get(source_type, 0)
            if count >= request.per_source_type_limit:
                omitted.append(hit)
                continue
            remaining_chars = request.max_chars - used_chars
            if remaining_chars <= 0:
                omitted.append(hit)
                continue
            budgeted_hit = _fit_hit_to_budget(hit, remaining_chars)
            hit_chars = max(budgeted_hit.content_length(), 1)
            if selected and used_chars + hit_chars > request.max_chars:
                omitted.append(hit)
                continue
            selected.append(budgeted_hit)
            per_type_counts[source_type] = count + 1
            used_chars += hit_chars
            if len(selected) >= request.top_k:
                omitted.extend(candidates[index + 1 :])
                break
        grouped = _group_hits(selected)
        citations = [hit.source.copy() for hit in selected]
        return ContextPack(
            query=request.query,
            hits=selected,
            grouped_context=grouped,
            citations=citations,
            omitted=omitted,
        )

    def _collect_hits(self, request: RetrievalQuery) -> list[RetrievalHit]:
        hits: list[RetrievalHit] = []
        if self.career_store is not None:
            hits.extend(build_career_hits(self.career_store, request))
        if self.note_store is not None:
            hits.extend(build_note_hits(self.note_store, request))
        if self.knowledge_store is not None:
            hits.extend(build_knowledge_hits(self.knowledge_store, request))
        if self.learning_store is not None:
            hits.extend(build_learning_hits(self.learning_store, request))
        if self.session_repository is not None:
            hits.extend(build_session_artifact_hits(self.session_repository, request))
        if self.index_store is not None:
            hits.extend(build_index_hits(self.index_store, request))
        return hits

    def _expand_project_context(self, request: RetrievalQuery, candidates: list[RetrievalHit]) -> list[RetrievalHit]:
        if self.career_store is None:
            return candidates
        application_ids = _context_application_ids(request, candidates)
        if not application_ids:
            return candidates
        output = [hit.copy() for hit in candidates]
        for application_id in application_ids[:1]:
            related_request = replace(
                request,
                related_application_id=application_id,
                top_k=max(request.top_k, 20),
            )
            for hit in self._collect_hits(related_request):
                output.append(_boost_project_hit(hit, application_id))
        return output


def _rank_hits(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    ranked = sorted(
        hits,
        key=lambda hit: (
            -hit.score,
            -hit.updated_at.timestamp(),
            validate_source_type(hit.source.source_type).value,
            hit.source.source_id,
        ),
    )
    return _dedupe_ranked_hits(ranked)


def _dedupe_ranked_hits(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    output: list[RetrievalHit] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = (validate_source_type(hit.source.source_type).value, hit.source.source_id)
        if key in seen:
            continue
        output.append(hit)
        seen.add(key)
    return output


def _context_application_ids(request: RetrievalQuery, candidates: list[RetrievalHit]) -> list[str]:
    output: list[str] = []
    if request.related_application_id is not None:
        output.append(request.related_application_id)
    for hit in candidates:
        for value in _hit_related_ids(hit):
            if value.startswith("application_") and value not in output:
                output.append(value)
        if len(output) >= 2:
            break
    return output


def _hit_related_ids(hit: RetrievalHit) -> list[str]:
    values = [
        hit.source.source_id,
        hit.source.artifact_id,
        *hit.evidence_refs,
    ]
    related_ids = hit.metadata.get("related_ids")
    if isinstance(related_ids, list):
        values.extend(str(item) for item in related_ids)
    return [item for item in values if isinstance(item, str) and item]


def _boost_project_hit(hit: RetrievalHit, application_id: str) -> RetrievalHit:
    item = hit.copy()
    related_ids = _hit_related_ids(item)
    if application_id in related_ids:
        item.score = min(round(item.score + 0.18, 4), 1.0)
        item.metadata["related_application_id"] = application_id
        if item.match_reason:
            item.match_reason = f"项目上下文扩展；{item.match_reason}"
        else:
            item.match_reason = "项目上下文扩展"
    return item


def _fit_hit_to_budget(hit: RetrievalHit, max_chars: int) -> RetrievalHit:
    item = hit.copy()
    if item.content_length() <= max_chars:
        return item
    if max_chars <= 0:
        item.summary = ""
        item.snippet = ""
        return item
    title_budget = min(len(item.title), max_chars)
    item.title = _truncate_text(item.title, title_budget)
    remaining = max(max_chars - len(item.title), 0)
    if remaining <= 0:
        item.summary = ""
        item.snippet = ""
        return item
    summary_budget = min(len(item.summary), max(remaining // 3, 0))
    item.summary = _truncate_text(item.summary, summary_budget)
    remaining = max(max_chars - len(item.title) - len(item.summary), 0)
    item.snippet = _truncate_text(item.snippet, remaining)
    return item


def _truncate_text(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars <= 1:
        return value[:max_chars]
    return value[: max_chars - 1].rstrip() + "…"


def _group_hits(hits: list[RetrievalHit]) -> dict[str, list[RetrievalHit]]:
    grouped: dict[str, list[RetrievalHit]] = {
        "artifacts": [],
        "career": [],
        "knowledge": [],
        "learning": [],
        "notes": [],
    }
    for hit in hits:
        group = group_for_source_type(hit.source.source_type)
        grouped[group].append(hit.copy())
    return grouped
