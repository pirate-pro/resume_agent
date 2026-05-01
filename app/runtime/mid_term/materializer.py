"""Materialize mid-term candidates into long-term memory facts."""

from __future__ import annotations

import logging
from datetime import datetime
from hashlib import sha256
from typing import Any

from app.memory.file_store import FileMemoryStore
from app.memory.models import MemoryScope
from app.memory.policies import normalize_memory_tags
from app.memory.write_plan import MemoryWritePlan, build_memory_write_plan
from app.runtime.mid_term.models import MidTermFlushJob
from app.runtime.mid_term.shared import flush_id_for_pack, format_iso, normalize_evidence, optional_text, safe_text

FLUSH_LONG_TERM_MIN_CONFIDENCE = 0.55

_logger = logging.getLogger(__name__)


class MidTermCandidateFactMaterializer:
    """Write model-approved reusable candidates into agent long-term facts."""

    def __init__(self, memory_store: FileMemoryStore) -> None:
        self._memory_store = memory_store

    def materialize(
        self,
        *,
        job: MidTermFlushJob,
        summary: dict[str, Any],
        flushed_at: datetime,
    ) -> tuple[int, int]:
        raw_candidates = summary.get("candidate_long_term")
        if not isinstance(raw_candidates, list) or not raw_candidates:
            return (0, 0)
        written = 0
        skipped = 0
        valid_event_ids = {
            str(item.get("event_id", "")).strip()
            for item in job.event_pack.events
            if isinstance(item, dict) and str(item.get("event_id", "")).strip()
        }
        for index, raw in enumerate(raw_candidates):
            if not isinstance(raw, dict):
                skipped += 1
                continue
            content = optional_text(raw.get("content"))
            if content is None:
                skipped += 1
                continue
            evidence_ids = normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            if not evidence_ids:
                raw_evidence = raw.get("evidence_event_ids")
                if isinstance(raw_evidence, list):
                    evidence_ids = [str(item).strip() for item in raw_evidence if isinstance(item, str) and str(item).strip()]
            if not evidence_ids:
                skipped += 1
                continue
            candidate_tags = flush_candidate_tags(raw.get("tags"))
            source_event_id = evidence_ids[0]
            plan = build_memory_write_plan(
                agent_id=job.agent_id,
                session_id=job.session_id,
                content=content,
                tags=candidate_tags,
                source_event_id=source_event_id,
                source="mid_term_flush",
            )
            origin_key = candidate_origin_key(
                job=job,
                candidate_index=index,
                content=content,
                tags=candidate_tags,
            )
            if self._should_skip_candidate(job=job, plan=plan, content=content, origin_key=origin_key):
                skipped += 1
                continue
            metadata = flush_memory_metadata_from_plan(
                plan=plan,
                source_agent_id=job.agent_id,
                target_agent_id=job.agent_id,
            )
            metadata.update(
                {
                    "source": "mid_term_flush",
                    "origin": "mid_term_flush",
                    "origin_key": origin_key,
                    "flush_job_id": job.job_id,
                    "flush_id": flush_id_for_pack(job.event_pack),
                    "flush_batch": f"{job.event_pack.batch_index}/{job.event_pack.batch_total}",
                    "flush_at": format_iso(flushed_at),
                    "why_reusable": safe_text(raw.get("why_reusable"), max_len=300) or "reusable_context",
                    "evidence_event_ids": ",".join(evidence_ids),
                }
            )
            self._memory_store.append_fact(
                content=plan.content,
                category=plan.category,
                confidence=flush_candidate_confidence(raw.get("confidence"), fallback=plan.confidence),
                scope=MemoryScope.AGENT_LONG,
                owner_agent_id=job.agent_id,
                session_id=job.session_id,
                source_event_id=source_event_id,
                source_type="mid_term_flush",
                tags=plan.tags,
                inject_policy=plan.inject_policy,
                metadata=metadata,
            )
            written += 1
        if written > 0:
            self._refresh_agent_long_summary(job)
        return (written, skipped)

    def _should_skip_candidate(
        self,
        *,
        job: MidTermFlushJob,
        plan: MemoryWritePlan,
        content: str,
        origin_key: str,
    ) -> bool:
        if self._memory_store.has_active_fact_with_metadata(
            scope=MemoryScope.AGENT_LONG,
            agent_id=job.agent_id,
            metadata_key="origin_key",
            metadata_value=origin_key,
        ):
            return True
        if self._memory_store.find_active_fact_by_content(
            scope=MemoryScope.AGENT_LONG,
            agent_id=job.agent_id,
            content=content,
        ) is not None:
            return True
        if self._memory_store.has_archived_fact_by_content(
            scope=MemoryScope.AGENT_LONG,
            agent_id=job.agent_id,
            content=content,
        ):
            return True
        if plan.canonical_key:
            active_same_key = self._memory_store.find_active_fact_by_canonical_key(
                scope=MemoryScope.AGENT_LONG,
                agent_id=job.agent_id,
                canonical_key=plan.canonical_key,
            )
            if active_same_key is not None:
                return True
        return False

    def _refresh_agent_long_summary(self, job: MidTermFlushJob) -> None:
        try:
            self._memory_store.refresh_long_term_summary_from_facts(
                scope=MemoryScope.AGENT_LONG,
                agent_id=job.agent_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "mid-term flush refresh long-term summary failed (ignored): session_id=%s agent_id=%s error=%s",
                job.session_id,
                job.agent_id,
                exc,
            )


def flush_candidate_tags(raw_tags: Any) -> list[str]:
    tags = [tag for tag in raw_tags if isinstance(tag, str)] if isinstance(raw_tags, list) else []
    normalized = normalize_memory_tags(tags + ["long_term", "mid_term_flush_candidate"])
    disallowed = {"shared", "global", "cross_agent", "agent_short", "short", "session_state", "working_state"}
    filtered = [tag for tag in normalized if tag not in disallowed]
    if "long_term" not in filtered:
        filtered.append("long_term")
    return normalize_memory_tags(filtered)


def flush_candidate_confidence(raw_confidence: Any, *, fallback: float) -> float:
    if isinstance(raw_confidence, (int, float)):
        value = float(raw_confidence)
        if 0 <= value <= 1:
            return round(max(FLUSH_LONG_TERM_MIN_CONFIDENCE, value), 3)
    return fallback


def candidate_origin_key(
    *,
    job: MidTermFlushJob,
    candidate_index: int,
    content: str,
    tags: list[str],
) -> str:
    base = "|".join(
        [
            "mid_term_flush",
            job.job_id,
            job.session_id,
            job.agent_id,
            job.event_pack.first_event_id,
            job.event_pack.last_event_id,
            str(candidate_index),
            content.strip(),
            ",".join(tags),
        ]
    )
    digest = sha256(base.encode("utf-8")).hexdigest()
    return f"flush:{digest}"


def flush_memory_metadata_from_plan(
    *,
    plan: MemoryWritePlan,
    source_agent_id: str,
    target_agent_id: str,
) -> dict[str, str]:
    metadata: dict[str, str] = {
        "source_agent_id": source_agent_id,
        "target_agent_id": target_agent_id,
        "memory_type": plan.memory_type.value,
        "memory_scope": MemoryScope.AGENT_LONG.value,
        "kind": plan.kind,
        "source_kind": plan.source_kind,
        "subject_kind": plan.subject_kind,
        "classification_version": plan.classification_version,
        "write_key": plan.write_key,
    }
    if plan.canonical_key:
        metadata["canonical_key"] = plan.canonical_key
    if plan.normalized_value:
        metadata["normalized_value"] = plan.normalized_value
    raw_source = plan.metadata.get("source") if isinstance(plan.metadata, dict) else None
    if isinstance(raw_source, str) and raw_source.strip():
        metadata["source"] = raw_source.strip()
    return metadata
