"""Build memory memory write plans from raw tool/runtime input."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from app.core.errors import ValidationError
from app.memory.classification import classify_memory
from app.memory.models import MemoryScope, MemoryType
from app.memory.policies import (
    ALWAYS_ON_CONTEXT_CANONICAL_KEYS,
    MemoryCanonicalKey,
    infer_confidence_from_tags,
    infer_memory_type_from_tags,
    infer_scope_from_tags,
    normalize_memory_tags,
)

__all__ = ["MemoryWritePlan", "build_memory_write_plan", "infer_write_scope_from_tags"]


@dataclass(slots=True)
class MemoryWritePlan:
    agent_id: str
    session_id: str | None
    content: str
    tags: list[str]
    memory_type: MemoryType
    scope: MemoryScope
    category: str
    confidence: float
    kind: str
    source_kind: str
    canonical_key: str | None
    normalized_value: str | None
    subject_kind: str
    classification_version: str
    source_event_id: str | None
    write_key: str
    inject_policy: str
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.agent_id = _require_non_empty("agent_id", self.agent_id)
        self.session_id = _normalize_optional("session_id", self.session_id)
        self.content = _require_non_empty("content", self.content)
        self.tags = normalize_memory_tags(self.tags)
        if not isinstance(self.memory_type, MemoryType):
            raise ValidationError("memory_type must be MemoryType.")
        if not isinstance(self.scope, MemoryScope):
            raise ValidationError("scope must be MemoryScope.")
        self.category = _require_non_empty("category", self.category)
        self.confidence = _normalize_score("confidence", self.confidence)
        self.kind = _require_non_empty("kind", self.kind)
        self.source_kind = _require_non_empty("source_kind", self.source_kind)
        self.canonical_key = _normalize_optional("canonical_key", self.canonical_key)
        self.normalized_value = _normalize_optional("normalized_value", self.normalized_value)
        self.subject_kind = _require_non_empty("subject_kind", self.subject_kind)
        self.classification_version = _require_non_empty("classification_version", self.classification_version)
        self.source_event_id = _normalize_optional("source_event_id", self.source_event_id)
        self.write_key = _require_non_empty("write_key", self.write_key)
        self.inject_policy = _require_non_empty("inject_policy", self.inject_policy)
        self.metadata = _normalize_metadata(self.metadata)


def build_memory_write_plan(
    *,
    agent_id: str,
    session_id: str | None,
    content: str,
    tags: list[str],
    source_event_id: str | None,
    source: str,
) -> MemoryWritePlan:
    normalized_tags = normalize_memory_tags(tags)
    memory_type = infer_memory_type_from_tags(normalized_tags)
    scope = infer_write_scope_from_tags(normalized_tags)
    confidence = infer_confidence_from_tags(normalized_tags)
    classification = classify_memory(content=content, tags=normalized_tags, source=source)
    write_key = _build_write_key(
        agent_id=agent_id,
        session_id=session_id,
        source_event_id=source_event_id,
        content=content,
        tags=normalized_tags,
        source=source,
    )
    return MemoryWritePlan(
        agent_id=agent_id,
        session_id=session_id,
        content=content.strip(),
        tags=normalized_tags,
        memory_type=memory_type,
        scope=scope,
        category=_category_for_memory_type(memory_type, normalized_tags, classification.kind),
        confidence=confidence,
        kind=classification.kind,
        source_kind=classification.source_kind,
        canonical_key=classification.canonical_key,
        normalized_value=classification.normalized_value,
        subject_kind=classification.subject_kind,
        classification_version=classification.classification_version,
        source_event_id=source_event_id,
        write_key=write_key,
        inject_policy=_inject_policy(normalized_tags, scope, classification.kind, classification.canonical_key),
        metadata={
            "source": source,
        },
    )


def infer_write_scope_from_tags(tags: list[str]) -> MemoryScope:
    return infer_scope_from_tags(tags)


def _category_for_memory_type(memory_type: MemoryType, tags: list[str], kind: str) -> str:
    normalized_tags = {tag.strip().lower() for tag in tags if isinstance(tag, str) and tag.strip()}
    normalized_kind = kind.strip().lower()
    if memory_type == MemoryType.PREFERENCE:
        return "preference"
    if memory_type == MemoryType.CONSTRAINT:
        return "correction"
    if memory_type == MemoryType.PLAN or "goal" in normalized_tags:
        return "goal"
    if normalized_kind == "interaction_pattern" or "behavior" in normalized_tags:
        return "behavior"
    if "knowledge" in normalized_tags or "skill" in normalized_tags:
        return "knowledge"
    return "context"


def _inject_policy(tags: list[str], scope: MemoryScope, kind: str, canonical_key: str | None) -> str:
    normalized_tags = {tag.strip().lower() for tag in tags if isinstance(tag, str) and tag.strip()}
    normalized_key = "" if canonical_key is None else canonical_key.strip()
    if normalized_key == MemoryCanonicalKey.PREFERRED_NAME.value:
        return "always"
    if normalized_key in ALWAYS_ON_CONTEXT_CANONICAL_KEYS:
        return "always"
    if normalized_tags.intersection({"constraint", "rule", "policy", "system_policy", "explicit_user_rule"}):
        return "always"
    if scope == MemoryScope.SHARED_LONG and normalized_tags.intersection({"shared", "global", "cross_agent"}):
        return "always"
    return "retrieval"


def _build_write_key(
    *,
    agent_id: str,
    session_id: str | None,
    source_event_id: str | None,
    content: str,
    tags: list[str],
    source: str,
) -> str:
    base = "|".join(
        [
            agent_id.strip(),
            (session_id or "-").strip(),
            (source_event_id or "-").strip(),
            content.strip(),
            ",".join(tags),
            source.strip(),
        ]
    )
    digest = sha256(base.encode("utf-8")).hexdigest()
    return f"write:{digest}"


def _require_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _normalize_optional(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_non_empty(field_name, value)


def _normalize_score(field_name: str, value: float) -> float:
    if isinstance(value, int):
        value = float(value)
    if not isinstance(value, float) or value < 0 or value > 1:
        raise ValidationError(f"{field_name} must be between 0 and 1.")
    return value


def _normalize_metadata(metadata: dict[str, str]) -> dict[str, str]:
    if not isinstance(metadata, dict):
        raise ValidationError("metadata must be a dict.")
    normalized: dict[str, str] = {}
    for key, value in metadata.items():
        normalized[_require_non_empty("metadata key", key)] = _require_non_empty("metadata value", value)
    return normalized
