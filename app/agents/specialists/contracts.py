from __future__ import annotations

from dataclasses import dataclass, field

from app.core.db.models.entities import JobPosting
from app.domain.models.candidate import CandidateProfile
from app.domain.models.matching import MatchResult
from app.domain.models.optimization import OptimizationDraft


@dataclass(slots=True)
class ResumeOptimizationContext:
    profile: CandidateProfile
    target_job: JobPosting
    match_result: MatchResult
    task_id: str | None = None
    context_id: str | None = None
    parent_context_id: str | None = None
    attempt: int = 0
    local_memory: dict = field(default_factory=dict)
    shared_refs: dict = field(default_factory=dict)
    objective: str = "Generate a targeted resume draft grounded only in candidate evidence."


@dataclass(slots=True)
class ReviewGuardContext:
    profile: CandidateProfile
    match_result: MatchResult
    draft: OptimizationDraft
    target_job_title: str | None = None
    task_id: str | None = None
    context_id: str | None = None
    parent_context_id: str | None = None
    attempt: int = 0
    local_memory: dict = field(default_factory=dict)
    shared_refs: dict = field(default_factory=dict)
    objective: str = "Decide whether the targeted resume draft is safe to deliver."
