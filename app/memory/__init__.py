"""Memory subsystem package."""

from __future__ import annotations

from app.memory.admission import MemoryAdmissionDecision, MemoryAdmissionResult, evaluate_memory_admission
from app.memory.classification import MemoryClassification, classify_memory
from app.memory.facade import FileMemoryFacade
from app.memory.intake import build_candidate_request
from app.memory.metadata_refresh import build_metadata_refresh_patch
from app.memory.models import (
    CandidateResult,
    CompactResult,
    ConsolidateResult,
    ForgetResult,
    MemoryCandidate,
    MemoryCompactRequest,
    MemoryConsolidateRequest,
    MemoryForgetRequest,
    MemoryReadBundle,
    MemoryReadRequest,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryStructuredBackfillRequest,
    MemoryStructuredBackfillResult,
    MemoryType,
    MemoryWriteCandidateRequest,
)
from app.memory.policies import MemoryPolicy, default_memory_policy

__all__ = [
    "CandidateResult",
    "CompactResult",
    "ConsolidateResult",
    "FileMemoryFacade",
    "ForgetResult",
    "MemoryAdmissionDecision",
    "MemoryAdmissionResult",
    "MemoryCandidate",
    "MemoryClassification",
    "MemoryCompactRequest",
    "MemoryConsolidateRequest",
    "MemoryForgetRequest",
    "MemoryPolicy",
    "MemoryReadBundle",
    "MemoryReadRequest",
    "MemoryRecord",
    "MemoryScope",
    "MemoryStatus",
    "MemoryStructuredBackfillRequest",
    "MemoryStructuredBackfillResult",
    "MemoryType",
    "MemoryWriteCandidateRequest",
    "build_candidate_request",
    "build_metadata_refresh_patch",
    "classify_memory",
    "default_memory_policy",
    "evaluate_memory_admission",
]
