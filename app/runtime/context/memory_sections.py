"""Memory slicing and formatting helpers for context assembly."""

from __future__ import annotations

from app.domain.models import MemoryItem
from app.runtime.context.models import MemoryContextSlices


def flatten_memory_lanes(lanes: dict[str, list[MemoryItem]]) -> list[MemoryItem]:
    flattened: list[MemoryItem] = []
    seen: set[str] = set()
    for items in lanes.values():
        for item in items:
            if item.memory_id in seen:
                continue
            seen.add(item.memory_id)
            flattened.append(item)
    return flattened


def split_memory_lanes(
    memory_lanes: dict[str, list[MemoryItem]],
) -> MemoryContextSlices:
    long_term_summaries: list[MemoryItem] = []
    facts_by_lane: dict[str, list[MemoryItem]] = {}
    mid_term_items: list[MemoryItem] = []
    for lane, items in memory_lanes.items():
        for item in items:
            layer = memory_layer(item)
            if layer == "mid_term":
                mid_term_items.append(item)
                continue
            if layer == "long_term":
                long_term_summaries.append(item)
                continue
            facts_by_lane.setdefault(lane, []).append(item)
    return MemoryContextSlices(
        long_term_summaries=dedupe_memory_items(long_term_summaries),
        facts_by_lane={lane: dedupe_memory_items(items) for lane, items in facts_by_lane.items()},
        mid_term_items=dedupe_memory_items(mid_term_items),
    )


def memory_layer(item: MemoryItem) -> str:
    raw_layer = item.memory_layer or item.metadata.get("memory_layer")
    layer = raw_layer.strip().lower() if isinstance(raw_layer, str) else ""
    if layer:
        return layer
    tags = {tag.strip().lower() for tag in item.tags}
    source_kind = item.source_kind.strip().lower() if isinstance(item.source_kind, str) else ""
    if "mid_term" in tags or item.memory_id.startswith("mid_"):
        return "mid_term"
    if "long_term" in tags and (source_kind == "long_term_summary" or item.memory_id.startswith("long_")):
        return "long_term"
    return "facts"


def group_memory_items_by_scope(items: list[MemoryItem]) -> dict[str, list[MemoryItem]]:
    grouped: dict[str, list[MemoryItem]] = {}
    for item in items:
        scope_key = memory_scope_key(item)
        grouped.setdefault(scope_key, []).append(item)
    return grouped


def memory_scope_key(item: MemoryItem) -> str:
    if item.scope:
        return item.scope.strip().lower()
    raw_scope = item.metadata.get("memory_scope") or item.metadata.get("storage_scope")
    if isinstance(raw_scope, str) and raw_scope.strip():
        return raw_scope.strip().lower()
    return "unknown"


def format_memory_lines(items: list[MemoryItem]) -> list[str]:
    return [format_memory_line(item) for item in items]


def format_memory_line(item: MemoryItem) -> str:
    meta_parts: list[str] = []
    if item.scope:
        meta_parts.append(f"scope: {item.scope}")
    if item.tags:
        meta_parts.append(f"tags: {', '.join(item.tags)}")
    suffix = f" [{'; '.join(meta_parts)}]" if meta_parts else ""
    return f"- ({item.memory_id}) {item.content}{suffix}"


def section_key(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or "unknown"


def dedupe_memory_items(items: list[MemoryItem]) -> list[MemoryItem]:
    output: list[MemoryItem] = []
    seen: set[str] = set()
    for item in items:
        if item.memory_id in seen:
            continue
        seen.add(item.memory_id)
        output.append(item)
    return output
