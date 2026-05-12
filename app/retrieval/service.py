"""Rule-based retrieval service over product stores."""

from __future__ import annotations

from dataclasses import dataclass

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
from app.retrieval.models import ContextPack, RetrievalHit, RetrievalQuery, group_for_source_type, validate_source_type

__all__ = ["RetrievalService"]


@dataclass(slots=True)
class RetrievalService:
    """Read-only service that recalls product context and builds context packs."""

    career_store: CareerProductStore | None = None
    note_store: NoteStore | None = None
    knowledge_store: KnowledgeStore | None = None
    learning_store: LearningStore | None = None
    session_repository: SessionRepository | None = None

    def search(self, request: RetrievalQuery) -> list[RetrievalHit]:
        """Return ranked retrieval hits."""

        hits = self._collect_hits(request)
        ranked = _rank_hits(hits)
        return [hit.copy() for hit in ranked[: request.top_k]]

    def build_context_pack(self, request: RetrievalQuery) -> ContextPack:
        """Return a budgeted context pack grouped by product source."""

        candidates = _rank_hits(self._collect_hits(request))
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
            hit_chars = max(hit.content_length(), 1)
            if selected and used_chars + hit_chars > request.max_chars:
                omitted.append(hit)
                continue
            selected.append(hit)
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
        return hits


def _rank_hits(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    return sorted(
        hits,
        key=lambda hit: (
            -hit.score,
            -hit.updated_at.timestamp(),
            validate_source_type(hit.source.source_type).value,
            hit.source.source_id,
        ),
    )


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
