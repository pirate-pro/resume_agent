"""Coverage contracts for safe context compaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.domain.models import EventRecord, RunContext

__all__ = [
    "AllowAllCompactionCoverage",
    "CompactionCoverageChecker",
    "CompactionCoverageResult",
]


@dataclass(slots=True)
class CompactionCoverageResult:
    covered: bool
    reason: str
    missing_event_ids: list[str] = field(default_factory=list)


class CompactionCoverageChecker(Protocol):
    """Checks whether events can be safely removed from the short-term stream."""

    def check_compaction_coverage(
        self,
        *,
        context: RunContext,
        all_events: list[EventRecord],
        compressed_events: list[EventRecord],
    ) -> CompactionCoverageResult:
        """Return whether compressed events are already covered by durable flush state."""


class AllowAllCompactionCoverage:
    """Default policy for isolated tests or deployments without mid-term flush."""

    def check_compaction_coverage(
        self,
        *,
        context: RunContext,
        all_events: list[EventRecord],
        compressed_events: list[EventRecord],
    ) -> CompactionCoverageResult:
        return CompactionCoverageResult(covered=True, reason="coverage_not_required")
