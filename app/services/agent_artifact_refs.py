"""Validation helpers for artifact refs passed between agents."""

from __future__ import annotations

import re

from app.core.errors import ValidationError

__all__ = ["normalize_agent_artifact_refs"]

_ARTIFACT_ID_PATTERN = re.compile(r"^artifact_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def normalize_agent_artifact_refs(field_name: str, values: list[str]) -> list[str]:
    """Normalize child-agent artifact refs and reject path-like inputs.

    `artifact_refs` are cross-agent references, not file paths. Only current
    SessionArtifact ids are accepted.
    """
    if not isinstance(values, list):
        raise ValidationError(f"{field_name} must be a list.")
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        normalized = _normalize_artifact_ref(field_name, raw)
        if normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output


def _normalize_artifact_ref(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} items must be non-empty strings.")
    normalized = value.strip()
    if _ARTIFACT_ID_PATTERN.fullmatch(normalized):
        return normalized
    raise ValidationError(
        f"{field_name} must contain session artifact ids, not workspace paths or filenames: {normalized}"
    )
