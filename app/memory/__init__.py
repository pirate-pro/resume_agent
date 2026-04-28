"""Memory subsystem package."""

from __future__ import annotations

from app.memory.admission import MemoryAdmissionDecision, MemoryAdmissionResult, evaluate_memory_admission
from app.memory.classification import MemoryClassification, classify_memory
from app.memory.facade import FileMemoryFacade
from app.memory.index import MemoryIndex, SqliteMemoryIndex
from app.memory.intake import build_candidate_request
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
    MemoryType,
    MemoryWriteCandidateRequest,
)
from app.memory.policies import (
    MemoryCanonicalKey,
    MemoryKind,
    MemoryLane,
    MemoryPolicy,
    MemorySourceKind,
    default_memory_policy,
)

__all__ = [
    "CandidateResult",
    "CompactResult",
    "ConsolidateResult",
    "FileMemoryFacade",
    "ForgetResult",
    "MemoryAdmissionDecision",
    "MemoryAdmissionResult",
    "MemoryCandidate",
    "MemoryCanonicalKey",
    "MemoryClassification",
    "MemoryCompactRequest",
    "MemoryConsolidateRequest",
    "MemoryForgetRequest",
    "MemoryIndex",
    "MemoryKind",
    "MemoryLane",
    "MemoryPolicy",
    "MemoryReadBundle",
    "MemoryReadRequest",
    "MemoryRecord",
    "MemoryScope",
    "MemorySourceKind",
    "MemoryStatus",
    "MemoryType",
    "MemoryWriteCandidateRequest",
    "SqliteMemoryIndex",
    "build_candidate_request",
    "classify_memory",
    "default_memory_policy",
    "evaluate_memory_admission",
]
