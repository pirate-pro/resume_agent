"""Helpers for conservative structured metadata refresh."""

from __future__ import annotations

__all__ = ["build_metadata_refresh_patch"]

_STALE_SOURCE_KIND_VALUES = {
    "legacy_memory_backfill",
    "memory_manager",
    "memory_update_query",
    "memory_update_tool",
    "memory_write_tool",
}


def build_metadata_refresh_patch(
    *,
    existing_metadata: dict[str, str],
    classified_metadata: dict[str, str],
) -> dict[str, str]:
    patch: dict[str, str] = {}
    for key, new_value in classified_metadata.items():
        current_value = str(existing_metadata.get(key, "")).strip()
        if not current_value:
            patch[key] = new_value
            continue
        if key == "source_kind" and current_value in _STALE_SOURCE_KIND_VALUES and current_value != new_value:
            patch[key] = new_value
            continue
        if key == "classification_version" and current_value != new_value:
            patch[key] = new_value
    return patch
