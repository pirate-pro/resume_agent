"""Policy kernel for memory admission, classification, routing, and retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.core.errors import ValidationError
from app.memory.models import MemoryScope, MemoryType

__all__ = [
    "ALWAYS_ON_CONTEXT_CANONICAL_KEYS",
    "CONTEXT_LANE_LIMITS",
    "CONTEXT_LANE_ORDER",
    "CONSTRAINT_TAGS",
    "EXPLICIT_RULE_SOURCES",
    "EXPLICIT_RULE_TAGS",
    "FEEDBACK_TAGS",
    "HIGH_CONFIDENCE_TAGS",
    "INFERRED_TAGS",
    "INTERACTION_TAGS",
    "LONG_OR_SHARED_TAGS",
    "LONG_SCOPE_TAGS",
    "MemoryCanonicalKey",
    "MemoryKind",
    "MemoryLane",
    "MemoryPolicy",
    "MemorySourceKind",
    "PLAN_TAGS",
    "PREFERENCE_TAGS",
    "SCRATCH_TAGS",
    "SHARED_SCOPE_TAGS",
    "SOURCE_PRIORITY",
    "STATE_TAGS",
    "TEXT_SEARCH_NAME_EXPANSIONS",
    "TEXT_SEARCH_NAME_QUERY_TRIGGERS",
    "VERIFIED_TAGS",
    "default_memory_policy",
    "infer_confidence_from_tags",
    "infer_memory_kind",
    "infer_memory_type_from_tags",
    "infer_scope_from_tags",
    "infer_source_kind_from_tags",
    "is_explicit_rule_identity",
    "is_name_query",
    "memory_lane_for_metadata",
    "normalize_memory_tags",
    "should_expand_name_query",
    "source_priority_for_kind",
]


class MemoryKind(str, Enum):
    USER_FACT = "user_fact"
    USER_PREFERENCE = "user_preference"
    FEEDBACK_MEMORY = "feedback_memory"
    INTERACTION_PATTERN = "interaction_pattern"


class MemorySourceKind(str, Enum):
    SYSTEM_POLICY = "system_policy"
    EXPLICIT_USER_RULE = "explicit_user_rule"
    EXPLICIT_USER = "explicit_user"
    USER_FEEDBACK = "user_feedback"
    TOOL_VERIFIED = "tool_verified"
    REPEATED_BEHAVIOR = "repeated_behavior"
    ASSISTANT_INFERRED = "assistant_inferred"


class MemoryCanonicalKey(str, Enum):
    PREFERRED_NAME = "preferred_name"
    PREFERRED_LANGUAGE = "preferred_language"
    RESPONSE_STYLE = "response_style"
    PREFERRED_FORMAT = "preferred_format"
    DISLIKED_FORMAT = "disliked_format"
    INTERACTION_STYLE = "interaction_style"
    LONG_TERM_GOAL = "long_term_goal"
    PRIMARY_STACK = "primary_stack"


class MemoryLane(str, Enum):
    IDENTITY = "identity"
    RESPONSE_PREFERENCES = "response_preferences"
    INTERACTION_FEEDBACK = "interaction_feedback"
    USER_PROFILE = "user_profile"
    OTHER_MEMORIES = "other_memories"


STATE_TAGS = {"todo", "next_step", "scratch", "temp", "ephemeral", "working_state", "session_state"}
SHARED_SCOPE_TAGS = {"shared", "global", "cross_agent"}
LONG_SCOPE_TAGS = {"long", "long_term", "preference", "constraint", "policy", "profile", "memory"}
LONG_OR_SHARED_TAGS = LONG_SCOPE_TAGS | SHARED_SCOPE_TAGS

PREFERENCE_TAGS = {"preference", "style", "habit"}
CONSTRAINT_TAGS = {"constraint", "rule", "policy", "limit"}
FEEDBACK_TAGS = {"feedback"}
INTERACTION_TAGS = {"interaction_pattern"}
PLAN_TAGS = {"plan", "todo", "next_step"}
SCRATCH_TAGS = {"scratch", "temp", "ephemeral"}

VERIFIED_TAGS = {"verified", "tool_verified"}
INFERRED_TAGS = {"assistant_inferred", "guess", "draft"}
HIGH_CONFIDENCE_TAGS = {"verified", "tool_verified", "user_confirmed"}
EXPLICIT_RULE_TAGS = {MemorySourceKind.EXPLICIT_USER_RULE.value, MemorySourceKind.SYSTEM_POLICY.value}
EXPLICIT_RULE_SOURCES = {MemorySourceKind.EXPLICIT_USER_RULE.value, MemorySourceKind.SYSTEM_POLICY.value}

SOURCE_PRIORITY = {
    MemorySourceKind.SYSTEM_POLICY.value: 100,
    MemorySourceKind.EXPLICIT_USER_RULE.value: 95,
    MemorySourceKind.EXPLICIT_USER.value: 90,
    MemorySourceKind.USER_FEEDBACK.value: 80,
    MemorySourceKind.TOOL_VERIFIED.value: 70,
    MemorySourceKind.REPEATED_BEHAVIOR.value: 60,
    MemorySourceKind.ASSISTANT_INFERRED.value: 10,
}

CONTEXT_LANE_ORDER = (
    MemoryLane.IDENTITY.value,
    MemoryLane.RESPONSE_PREFERENCES.value,
    MemoryLane.INTERACTION_FEEDBACK.value,
    MemoryLane.USER_PROFILE.value,
    MemoryLane.OTHER_MEMORIES.value,
)
CONTEXT_LANE_LIMITS = {
    MemoryLane.IDENTITY.value: 2,
    MemoryLane.RESPONSE_PREFERENCES.value: 4,
    MemoryLane.INTERACTION_FEEDBACK.value: 3,
    MemoryLane.USER_PROFILE.value: 4,
    MemoryLane.OTHER_MEMORIES.value: 2,
}
ALWAYS_ON_CONTEXT_CANONICAL_KEYS = (
    MemoryCanonicalKey.PREFERRED_LANGUAGE.value,
    MemoryCanonicalKey.RESPONSE_STYLE.value,
    MemoryCanonicalKey.PREFERRED_FORMAT.value,
    MemoryCanonicalKey.DISLIKED_FORMAT.value,
    MemoryCanonicalKey.INTERACTION_STYLE.value,
)
_NAME_QUERY_TRIGGERS = (
    "你叫什么名字",
    "叫什么名字",
    "你的名字",
    "叫你什么",
    "怎么称呼",
    "如何称呼",
    "怎么叫你",
)
TEXT_SEARCH_NAME_QUERY_TRIGGERS = _NAME_QUERY_TRIGGERS + ("称呼", "名字")
TEXT_SEARCH_NAME_EXPANSIONS = ("名字", "称呼", "叫我", "叫你", "名称")


@dataclass(slots=True)
class MemoryPolicy:
    default_scopes: list[MemoryScope] = field(
        default_factory=lambda: [MemoryScope.AGENT_SHORT, MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG]
    )
    per_scope_limit: dict[MemoryScope, int] = field(
        default_factory=lambda: {
            MemoryScope.AGENT_SHORT: 6,
            MemoryScope.AGENT_LONG: 6,
            MemoryScope.SHARED_LONG: 6,
        }
    )
    short_ttl_seconds: int = 24 * 60 * 60
    agent_long_promotion_min_confidence: float = 0.7
    agent_long_promotion_min_repeat: int = 2
    shared_promotion_min_confidence: float = 0.85
    shared_promotion_min_repeat: int = 2

    def __post_init__(self) -> None:
        if not self.default_scopes:
            raise ValidationError("default_scopes cannot be empty.")
        for item in self.default_scopes:
            if not isinstance(item, MemoryScope):
                raise ValidationError("default_scopes must contain MemoryScope items.")
        if not isinstance(self.per_scope_limit, dict):
            raise ValidationError("per_scope_limit must be dictionary.")
        for scope, value in self.per_scope_limit.items():
            if not isinstance(scope, MemoryScope):
                raise ValidationError("per_scope_limit key must be MemoryScope.")
            if not isinstance(value, int) or value <= 0:
                raise ValidationError("per_scope_limit value must be positive integer.")
        if self.short_ttl_seconds <= 0:
            raise ValidationError("short_ttl_seconds must be positive.")
        if self.agent_long_promotion_min_confidence < 0 or self.agent_long_promotion_min_confidence > 1:
            raise ValidationError("agent_long_promotion_min_confidence must be in range [0,1].")
        if self.agent_long_promotion_min_repeat <= 0:
            raise ValidationError("agent_long_promotion_min_repeat must be positive.")
        if self.shared_promotion_min_confidence < 0 or self.shared_promotion_min_confidence > 1:
            raise ValidationError("shared_promotion_min_confidence must be in range [0,1].")
        if self.shared_promotion_min_repeat <= 0:
            raise ValidationError("shared_promotion_min_repeat must be positive.")


def default_memory_policy() -> MemoryPolicy:
    return MemoryPolicy()


def normalize_memory_tags(tags: list[str]) -> list[str]:
    dedup: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        if not isinstance(raw, str):
            continue
        tag = raw.strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        dedup.append(tag)
    return dedup


def infer_scope_from_tags(tags: list[str]) -> MemoryScope:
    values = set(normalize_memory_tags(tags))
    if values.intersection(SHARED_SCOPE_TAGS):
        return MemoryScope.SHARED_LONG
    if values.intersection(LONG_SCOPE_TAGS):
        return MemoryScope.AGENT_LONG
    return MemoryScope.AGENT_SHORT


def infer_memory_type_from_tags(tags: list[str]) -> MemoryType:
    values = set(normalize_memory_tags(tags))
    if values.intersection(PREFERENCE_TAGS):
        return MemoryType.PREFERENCE
    if values.intersection(CONSTRAINT_TAGS):
        return MemoryType.CONSTRAINT
    if values.intersection(PLAN_TAGS):
        return MemoryType.PLAN
    if values.intersection(SCRATCH_TAGS):
        return MemoryType.SCRATCH
    return MemoryType.FACT


def infer_confidence_from_tags(tags: list[str]) -> float:
    values = set(normalize_memory_tags(tags))
    if values.intersection(HIGH_CONFIDENCE_TAGS):
        return 0.9
    if "guess" in values or "draft" in values:
        return 0.5
    return 0.7


def infer_source_kind_from_tags(tags: set[str], source: str) -> str:
    normalized_source = source.strip().lower()
    if MemorySourceKind.SYSTEM_POLICY.value in tags or normalized_source == MemorySourceKind.SYSTEM_POLICY.value:
        return MemorySourceKind.SYSTEM_POLICY.value
    if MemorySourceKind.EXPLICIT_USER_RULE.value in tags or normalized_source == MemorySourceKind.EXPLICIT_USER_RULE.value:
        return MemorySourceKind.EXPLICIT_USER_RULE.value
    if tags.intersection(VERIFIED_TAGS):
        return MemorySourceKind.TOOL_VERIFIED.value
    if tags.intersection(INFERRED_TAGS):
        return MemorySourceKind.ASSISTANT_INFERRED.value
    return MemorySourceKind.EXPLICIT_USER.value


def infer_memory_kind(tags: set[str], lowered_content: str, canonical_key: str | None) -> str:
    if tags.intersection(FEEDBACK_TAGS) or _looks_like_feedback(lowered_content):
        return MemoryKind.FEEDBACK_MEMORY.value
    if tags.intersection(INTERACTION_TAGS) or canonical_key == MemoryCanonicalKey.INTERACTION_STYLE.value:
        return MemoryKind.INTERACTION_PATTERN.value
    if canonical_key in {
        MemoryCanonicalKey.PREFERRED_NAME.value,
        MemoryCanonicalKey.PREFERRED_LANGUAGE.value,
        MemoryCanonicalKey.RESPONSE_STYLE.value,
        MemoryCanonicalKey.PREFERRED_FORMAT.value,
        MemoryCanonicalKey.DISLIKED_FORMAT.value,
    }:
        return MemoryKind.USER_PREFERENCE.value
    if tags.intersection(PREFERENCE_TAGS) or tags.intersection(CONSTRAINT_TAGS):
        return MemoryKind.USER_PREFERENCE.value
    return MemoryKind.USER_FACT.value


def source_priority_for_kind(source_kind: str) -> int:
    return SOURCE_PRIORITY.get(source_kind.strip().lower(), 50)


def is_explicit_rule_identity(tags: list[str] | set[str], source: str | None, source_kind: str | None) -> bool:
    normalized_tags = set(normalize_memory_tags(list(tags)))
    if normalized_tags.intersection(EXPLICIT_RULE_TAGS):
        return True
    normalized_source = "" if source is None else source.strip().lower()
    normalized_source_kind = "" if source_kind is None else source_kind.strip().lower()
    return normalized_source in EXPLICIT_RULE_SOURCES or normalized_source_kind in EXPLICIT_RULE_SOURCES


def is_name_query(query: str) -> bool:
    compact_query = query.strip().lower().replace(" ", "")
    return any(trigger in compact_query for trigger in _NAME_QUERY_TRIGGERS)


def should_expand_name_query(query: str) -> bool:
    compact_query = query.strip().lower().replace(" ", "")
    return any(trigger in compact_query for trigger in TEXT_SEARCH_NAME_QUERY_TRIGGERS)


def memory_lane_for_metadata(canonical_key: str | None, kind: str | None) -> str:
    normalized_key = "" if canonical_key is None else canonical_key.strip()
    normalized_kind = "" if kind is None else kind.strip()
    if normalized_key == MemoryCanonicalKey.PREFERRED_NAME.value:
        return MemoryLane.IDENTITY.value
    if normalized_key in {
        MemoryCanonicalKey.PREFERRED_LANGUAGE.value,
        MemoryCanonicalKey.RESPONSE_STYLE.value,
        MemoryCanonicalKey.PREFERRED_FORMAT.value,
        MemoryCanonicalKey.DISLIKED_FORMAT.value,
    }:
        return MemoryLane.RESPONSE_PREFERENCES.value
    if normalized_key == MemoryCanonicalKey.INTERACTION_STYLE.value or normalized_kind in {
        MemoryKind.INTERACTION_PATTERN.value,
        MemoryKind.FEEDBACK_MEMORY.value,
    }:
        return MemoryLane.INTERACTION_FEEDBACK.value
    if normalized_key in {
        MemoryCanonicalKey.LONG_TERM_GOAL.value,
        MemoryCanonicalKey.PRIMARY_STACK.value,
    } or normalized_kind == MemoryKind.USER_FACT.value:
        return MemoryLane.USER_PROFILE.value
    if normalized_kind == MemoryKind.USER_PREFERENCE.value:
        return MemoryLane.RESPONSE_PREFERENCES.value
    return MemoryLane.OTHER_MEMORIES.value


def _looks_like_feedback(lowered_content: str) -> bool:
    return any(token in lowered_content for token in ("不要再", "别再", "以后保持", "这个格式很好", "keep this format"))
