"""Memory subsystem package."""

from __future__ import annotations

from app.memory.facade import FileMemoryFacade
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
from app.memory.policies import MemoryPolicy, default_memory_policy

__all__ = [
    "CandidateResult",
    "CompactResult",
    "ConsolidateResult",
    "FileMemoryFacade",
    "ForgetResult",
    "MemoryCandidate",
    "MemoryCompactRequest",
    "MemoryConsolidateRequest",
    "MemoryForgetRequest",
    "MemoryPolicy",
    "MemoryReadBundle",
    "MemoryReadRequest",
    "MemoryRecord",
    "MemoryScope",
    "MemoryStatus",
    "MemoryType",
    "MemoryWriteCandidateRequest",
    "build_candidate_request",
    "default_memory_policy",
]
