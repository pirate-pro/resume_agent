"""Policy defaults for memory retrieval and consolidation."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.errors import ValidationError
from app.memory.models import MemoryScope

__all__ = ["MemoryPolicy", "default_memory_policy"]


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
        if self.shared_promotion_min_confidence < 0 or self.shared_promotion_min_confidence > 1:
            raise ValidationError("shared_promotion_min_confidence must be in range [0,1].")
        if self.shared_promotion_min_repeat <= 0:
            raise ValidationError("shared_promotion_min_repeat must be positive.")


def default_memory_policy() -> MemoryPolicy:
    return MemoryPolicy()

