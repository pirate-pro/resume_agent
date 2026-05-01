"""Context lane grouping for memory injection."""

from __future__ import annotations

from app.domain.models import MemoryItem
from app.memory.models import MemoryRecord
from app.memory.policies import CONTEXT_LANE_LIMITS, CONTEXT_LANE_ORDER, memory_lane_for_metadata
from app.runtime.memory.serializers import to_memory_item


def group_records_by_context_lane(records: list[MemoryRecord]) -> dict[str, list[MemoryItem]]:
    lanes: dict[str, list[MemoryItem]] = {lane: [] for lane in CONTEXT_LANE_ORDER}
    for record in records:
        lane = context_lane_for_record(record)
        lanes.setdefault(lane, []).append(to_memory_item(record))
    return lanes


def context_lane_for_record(record: MemoryRecord) -> str:
    return memory_lane_for_metadata(record.canonical_key, record.kind)


def limit_memory_lanes(
    lanes: dict[str, list[MemoryItem]],
    *,
    max_total: int,
) -> dict[str, list[MemoryItem]]:
    limited: dict[str, list[MemoryItem]] = {}
    remaining = max(0, max_total)
    for lane in CONTEXT_LANE_ORDER:
        if remaining <= 0:
            break
        items = lanes.get(lane, [])
        if not items:
            continue
        lane_limit = min(CONTEXT_LANE_LIMITS[lane], remaining)
        selected = dedupe_memory_items(items)[:lane_limit]
        if not selected:
            continue
        limited[lane] = selected
        remaining -= len(selected)
    return limited


def flatten_memory_lanes(lanes: dict[str, list[MemoryItem]]) -> list[MemoryItem]:
    flattened: list[MemoryItem] = []
    for lane in CONTEXT_LANE_ORDER:
        flattened.extend(lanes.get(lane, []))
    return dedupe_memory_items(flattened)


def dedupe_records(records: list[MemoryRecord]) -> list[MemoryRecord]:
    output: list[MemoryRecord] = []
    seen: set[str] = set()
    for record in records:
        if record.memory_id in seen:
            continue
        seen.add(record.memory_id)
        output.append(record)
    return output


def dedupe_memory_items(items: list[MemoryItem]) -> list[MemoryItem]:
    output: list[MemoryItem] = []
    seen: set[str] = set()
    for item in items:
        if item.memory_id in seen:
            continue
        seen.add(item.memory_id)
        output.append(item)
    return output
