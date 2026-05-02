"""Prompt builders for short-term context compaction."""

from __future__ import annotations

import json
from typing import Any

from app.domain.models import RunContext

__all__ = ["CONTEXT_COMPACTOR_SYSTEM_PROMPT", "build_context_compaction_prompt"]

CONTEXT_COMPACTOR_SYSTEM_PROMPT = """You are a session context compactor.
Your job is to compress old short-term runtime events into a faithful summary for future turns.

Rules:
1. Reconstruct the timeline in old-to-new order.
2. Treat semantic units as atomic. Tool call/result pairs must stay semantically paired.
3. Preserve user intent, agent decisions, unresolved questions, tool outcomes, file/artifact references, and memory-relevant facts.
4. Do not invent facts. If evidence is unclear, omit it.
5. Keep the summary concise but operationally useful for continuing the same session.
6. Preserve the user's language and exact technical terms, file paths, tool names, variable names, and quoted values.
7. If source events are Chinese, output Chinese.
8. evidence_event_ids must come only from compressed_units, never from retained_units_preview.
9. If an earlier proposal is later rejected or superseded, do not quote the obsolete proposal as an active fact. Summarize it as an abandoned/superseded candidate and foreground the latest decision.
10. Output strict JSON only, with no Markdown fence.
"""


def build_context_compaction_prompt(
    *,
    context: RunContext,
    compressed_units: list[dict[str, Any]],
    retained_units_preview: list[dict[str, Any]],
    original_event_count: int,
    original_estimated_tokens: int,
    input_budget_tokens: int,
) -> str:
    schema = {
        "summary": "string",
        "timeline": ["string"],
        "decisions": ["string"],
        "open_threads": ["string"],
        "tool_progress": [
            {
                "tool_name": "string",
                "call_summary": "string",
                "result_summary": "string",
                "success": True,
                "evidence_event_ids": ["evt_call", "evt_result"],
            }
        ],
        "agent_activity": ["string"],
        "memory_relevant": ["string"],
        "evidence_event_ids": ["evt_xxx"],
    }
    payload = {
        "task": "Compress only compressed_units. retained_units stay as raw events after the summary.",
        "session_id": context.session_id,
        "agent_id": context.agent_id,
        "timeline_order": "old_to_new",
        "original_event_count": original_event_count,
        "original_estimated_tokens": original_estimated_tokens,
        "input_budget_tokens": input_budget_tokens,
        "required_schema": schema,
        "allowed_evidence_event_ids": _event_ids_from_units(compressed_units),
        "forbidden_retained_preview_event_ids": _event_ids_from_units(retained_units_preview),
        "compressed_units": compressed_units,
        "retained_units_preview": retained_units_preview,
    }
    return (
        "Compress these old session events into one structured context summary.\n"
        "Think through the timeline internally, but output only the required JSON object.\n"
        "The summary will be prepended before retained raw events, so avoid duplicating recent retained details.\n"
        "Use evidence_event_ids only from allowed_evidence_event_ids; never cite forbidden_retained_preview_event_ids.\n"
        "Preserve key terms verbatim, especially tool_call, tool_result, file names, user names, and Chinese phrases.\n"
        "For superseded proposals, avoid repeating obsolete wording verbatim; keep the correction and latest decision.\n"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )


def _event_ids_from_units(units: list[dict[str, Any]]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for unit in units:
        raw_ids = unit.get("event_ids")
        if not isinstance(raw_ids, list):
            continue
        for raw in raw_ids:
            if not isinstance(raw, str):
                continue
            event_id = raw.strip()
            if not event_id or event_id in seen:
                continue
            output.append(event_id)
            seen.add(event_id)
    return output
