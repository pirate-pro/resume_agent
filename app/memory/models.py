"""Domain models for the file-based memory subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256

from app.core.errors import ValidationError

__all__ = [
    "CandidateResult",
    "CompactResult",
    "ConsolidateResult",
    "ForgetResult",
    "MemoryCandidate",
    "MemoryCompactRequest",
    "MemoryConsolidateRequest",
    "MemoryForgetRequest",
    "MemoryReadBundle",
    "MemoryReadRequest",
    "MemoryRecord",
    "MemoryScope",
    "MemoryStatus",
    "MemoryStructuredBackfillRequest",
    "MemoryStructuredBackfillResult",
    "MemoryType",
    "MemoryWriteCandidateRequest",
    "make_content_hash",
]


class MemoryScope(str, Enum):
    SHARED_LONG = "shared_long"
    AGENT_LONG = "agent_long"
    AGENT_SHORT = "agent_short"


class MemoryType(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    CONSTRAINT = "constraint"
    PLAN = "plan"
    SCRATCH = "scratch"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


@dataclass(slots=True)
class MemoryRecord:
    memory_id: str
    scope: MemoryScope
    owner_agent_id: str | None
    session_id: str | None
    memory_type: MemoryType
    content: str
    tags: list[str]
    importance: float
    confidence: float
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    source_event_id: str | None = None
    source_agent_id: str | None = None
    version: int = 1
    parent_memory_id: str | None = None
    content_hash: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.memory_id = _require_non_empty("memory_id", self.memory_id)
        self.owner_agent_id = _normalize_optional("owner_agent_id", self.owner_agent_id)
        self.session_id = _normalize_optional("session_id", self.session_id)
        self.content = _require_non_empty("content", self.content)
        self.tags = _normalize_tags(self.tags)
        self.importance = _normalize_score("importance", self.importance)
        self.confidence = _normalize_score("confidence", self.confidence)
        self.created_at = _normalize_datetime("created_at", self.created_at)
        self.updated_at = _normalize_datetime("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at cannot be earlier than created_at.")
        if self.expires_at is not None:
            self.expires_at = _normalize_datetime("expires_at", self.expires_at)
        self.source_event_id = _normalize_optional("source_event_id", self.source_event_id)
        self.source_agent_id = _normalize_optional("source_agent_id", self.source_agent_id)
        self.parent_memory_id = _normalize_optional("parent_memory_id", self.parent_memory_id)
        if self.version <= 0:
            raise ValidationError("version must be positive.")
        self.metadata = _normalize_metadata(self.metadata)
        if not self.content_hash:
            self.content_hash = make_content_hash(self.content)
        else:
            self.content_hash = _require_non_empty("content_hash", self.content_hash)
        _validate_scope_fields(
            scope=self.scope,
            owner_agent_id=self.owner_agent_id,
            session_id=self.session_id,
        )


@dataclass(slots=True)
class MemoryCandidate:
    candidate_id: str
    agent_id: str
    session_id: str | None
    scope_hint: MemoryScope
    memory_type: MemoryType
    content: str
    tags: list[str]
    confidence: float
    source_event_id: str | None
    idempotency_key: str
    created_at: datetime
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.candidate_id = _require_non_empty("candidate_id", self.candidate_id)
        self.agent_id = _require_non_empty("agent_id", self.agent_id)
        self.session_id = _normalize_optional("session_id", self.session_id)
        self.content = _require_non_empty("content", self.content)
        self.tags = _normalize_tags(self.tags)
        self.confidence = _normalize_score("confidence", self.confidence)
        self.source_event_id = _normalize_optional("source_event_id", self.source_event_id)
        self.idempotency_key = _require_non_empty("idempotency_key", self.idempotency_key)
        self.created_at = _normalize_datetime("created_at", self.created_at)
        self.metadata = _normalize_metadata(self.metadata)


@dataclass(slots=True)
class MemoryReadRequest:
    agent_id: str
    session_id: str | None
    query: str
    include_scopes: list[MemoryScope] = field(
        default_factory=lambda: [MemoryScope.AGENT_SHORT, MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG]
    )
    limit: int = 12
    token_budget: int = 1200
    allow_fallback: bool = True

    def __post_init__(self) -> None:
        self.agent_id = _require_non_empty("agent_id", self.agent_id)
        self.session_id = _normalize_optional("session_id", self.session_id)
        self.query = _require_non_empty("query", self.query)
        if self.limit <= 0:
            raise ValidationError("limit must be positive.")
        if self.token_budget <= 0:
            raise ValidationError("token_budget must be positive.")
        self.include_scopes = _normalize_scopes(self.include_scopes)


@dataclass(slots=True)
class MemoryReadBundle:
    items: list[MemoryRecord]
    searched_scopes: list[MemoryScope]
    total_scanned: int
    truncated: bool
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.total_scanned < 0:
            raise ValidationError("total_scanned cannot be negative.")
        self.searched_scopes = _normalize_scopes(self.searched_scopes)
        self.notes = [note.strip() for note in self.notes if isinstance(note, str) and note.strip()]


@dataclass(slots=True)
class MemoryWriteCandidateRequest:
    agent_id: str
    session_id: str | None
    content: str
    tags: list[str]
    memory_type: MemoryType
    scope_hint: MemoryScope
    confidence: float
    source_event_id: str | None
    idempotency_key: str
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.agent_id = _require_non_empty("agent_id", self.agent_id)
        self.session_id = _normalize_optional("session_id", self.session_id)
        self.content = _require_non_empty("content", self.content)
        self.tags = _normalize_tags(self.tags)
        self.confidence = _normalize_score("confidence", self.confidence)
        self.source_event_id = _normalize_optional("source_event_id", self.source_event_id)
        self.idempotency_key = _require_non_empty("idempotency_key", self.idempotency_key)
        self.metadata = _normalize_metadata(self.metadata)


@dataclass(slots=True)
class CandidateResult:
    candidate_id: str
    accepted: bool
    reason: str

    def __post_init__(self) -> None:
        self.candidate_id = _require_non_empty("candidate_id", self.candidate_id)
        self.reason = _require_non_empty("reason", self.reason)


@dataclass(slots=True)
class MemoryConsolidateRequest:
    max_candidates: int = 100

    def __post_init__(self) -> None:
        if self.max_candidates <= 0:
            raise ValidationError("max_candidates must be positive.")


@dataclass(slots=True)
class ConsolidateResult:
    consumed_candidates: int
    written_records: int
    merged_records: int
    promoted_shared: int
    conflicts: int
    written_memory_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.consumed_candidates < 0:
            raise ValidationError("consumed_candidates cannot be negative.")
        if self.written_records < 0:
            raise ValidationError("written_records cannot be negative.")
        if self.merged_records < 0:
            raise ValidationError("merged_records cannot be negative.")
        if self.promoted_shared < 0:
            raise ValidationError("promoted_shared cannot be negative.")
        if self.conflicts < 0:
            raise ValidationError("conflicts cannot be negative.")
        normalized_ids: list[str] = []
        for memory_id in self.written_memory_ids:
            normalized_ids.append(_require_non_empty("written_memory_id", memory_id))
        self.written_memory_ids = normalized_ids


@dataclass(slots=True)
class MemoryForgetRequest:
    agent_id: str | None = None
    session_id: str | None = None
    scopes: list[MemoryScope] = field(
        default_factory=lambda: [MemoryScope.AGENT_SHORT, MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG]
    )
    before: datetime | None = None
    memory_ids: list[str] = field(default_factory=list)
    hard_delete: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        self.agent_id = _normalize_optional("agent_id", self.agent_id)
        self.session_id = _normalize_optional("session_id", self.session_id)
        self.scopes = _normalize_scopes(self.scopes)
        if self.before is not None:
            self.before = _normalize_datetime("before", self.before)
        self.memory_ids = [_require_non_empty("memory_id", item) for item in self.memory_ids]
        self.reason = _normalize_optional("reason", self.reason)


@dataclass(slots=True)
class ForgetResult:
    touched_records: int
    deleted_records: int
    archived_records: int

    def __post_init__(self) -> None:
        if self.touched_records < 0:
            raise ValidationError("touched_records cannot be negative.")
        if self.deleted_records < 0:
            raise ValidationError("deleted_records cannot be negative.")
        if self.archived_records < 0:
            raise ValidationError("archived_records cannot be negative.")


@dataclass(slots=True)
class MemoryCompactRequest:
    scopes: list[MemoryScope] = field(
        default_factory=lambda: [MemoryScope.AGENT_SHORT, MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG]
    )
    agent_id: str | None = None
    session_id: str | None = None
    remove_deleted: bool = True
    remove_expired: bool = True
    dedupe_by_memory_id: bool = True
    dedupe_by_content_hash: bool = False
    write_index: bool = True

    def __post_init__(self) -> None:
        self.scopes = _normalize_scopes(self.scopes)
        self.agent_id = _normalize_optional("agent_id", self.agent_id)
        self.session_id = _normalize_optional("session_id", self.session_id)
        if not isinstance(self.remove_deleted, bool):
            raise ValidationError("remove_deleted must be bool.")
        if not isinstance(self.remove_expired, bool):
            raise ValidationError("remove_expired must be bool.")
        if not isinstance(self.dedupe_by_memory_id, bool):
            raise ValidationError("dedupe_by_memory_id must be bool.")
        if not isinstance(self.dedupe_by_content_hash, bool):
            raise ValidationError("dedupe_by_content_hash must be bool.")
        if not isinstance(self.write_index, bool):
            raise ValidationError("write_index must be bool.")


@dataclass(slots=True)
class CompactResult:
    scanned_files: int
    rewritten_files: int
    scanned_rows: int
    kept_rows: int
    dropped_deleted: int
    dropped_expired: int
    dropped_superseded: int
    dropped_duplicate_hash: int
    invalid_rows: int
    index_files_written: int

    def __post_init__(self) -> None:
        for field_name in (
            "scanned_files",
            "rewritten_files",
            "scanned_rows",
            "kept_rows",
            "dropped_deleted",
            "dropped_expired",
            "dropped_superseded",
            "dropped_duplicate_hash",
            "invalid_rows",
            "index_files_written",
        ):
            value = getattr(self, field_name)
            if value < 0:
                raise ValidationError(f"{field_name} cannot be negative.")


@dataclass(slots=True)
class MemoryStructuredBackfillRequest:
    scopes: list[MemoryScope] = field(
        default_factory=lambda: [MemoryScope.AGENT_SHORT, MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG]
    )
    agent_id: str | None = None
    session_id: str | None = None
    include_deleted: bool = False
    write_log: bool = True

    def __post_init__(self) -> None:
        self.scopes = _normalize_scopes(self.scopes)
        self.agent_id = _normalize_optional("agent_id", self.agent_id)
        self.session_id = _normalize_optional("session_id", self.session_id)
        if not isinstance(self.include_deleted, bool):
            raise ValidationError("include_deleted must be bool.")
        if not isinstance(self.write_log, bool):
            raise ValidationError("write_log must be bool.")


@dataclass(slots=True)
class MemoryStructuredBackfillResult:
    scanned_files: int
    rewritten_files: int
    scanned_rows: int
    patched_records: int
    skipped_structured: int
    skipped_deleted: int
    invalid_rows: int

    def __post_init__(self) -> None:
        for field_name in (
            "scanned_files",
            "rewritten_files",
            "scanned_rows",
            "patched_records",
            "skipped_structured",
            "skipped_deleted",
            "invalid_rows",
        ):
            value = getattr(self, field_name)
            if value < 0:
                raise ValidationError(f"{field_name} cannot be negative.")


def make_content_hash(content: str) -> str:
    normalized = _require_non_empty("content", content)
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _require_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _normalize_optional(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_non_empty(field_name, value)


def _normalize_datetime(field_name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationError(f"{field_name} must be datetime.")
    return value.astimezone(UTC)


def _normalize_tags(tags: list[str]) -> list[str]:
    if not isinstance(tags, list):
        raise ValidationError("tags must be a list of strings.")
    dedup: list[str] = []
    seen: set[str] = set()
    for item in tags:
        tag = _require_non_empty("tag", item).lower()
        if tag in seen:
            continue
        seen.add(tag)
        dedup.append(tag)
    return dedup


def _normalize_score(field_name: str, value: float) -> float:
    if isinstance(value, int):
        value = float(value)
    if not isinstance(value, float):
        raise ValidationError(f"{field_name} must be float.")
    if value < 0.0 or value > 1.0:
        raise ValidationError(f"{field_name} must be in range [0, 1].")
    return value


def _normalize_metadata(metadata: dict[str, str]) -> dict[str, str]:
    if not isinstance(metadata, dict):
        raise ValidationError("metadata must be a dictionary.")
    normalized: dict[str, str] = {}
    for raw_key, raw_value in metadata.items():
        key = _require_non_empty("metadata key", str(raw_key))
        value = _require_non_empty("metadata value", str(raw_value))
        normalized[key] = value
    return normalized


def _normalize_scopes(scopes: list[MemoryScope]) -> list[MemoryScope]:
    if not isinstance(scopes, list) or not scopes:
        raise ValidationError("include_scopes must be a non-empty list.")
    ordered: list[MemoryScope] = []
    seen: set[MemoryScope] = set()
    for scope in scopes:
        if not isinstance(scope, MemoryScope):
            raise ValidationError("scope item must be MemoryScope.")
        if scope in seen:
            continue
        ordered.append(scope)
        seen.add(scope)
    return ordered


def _validate_scope_fields(scope: MemoryScope, owner_agent_id: str | None, session_id: str | None) -> None:
    if scope == MemoryScope.SHARED_LONG:
        return
    if owner_agent_id is None:
        raise ValidationError("owner_agent_id is required for agent scope memories.")
    if scope == MemoryScope.AGENT_SHORT and session_id is None:
        raise ValidationError("session_id is required for agent_short memories.")
