"""Prompt builders for mid-term memory flushing."""

from __future__ import annotations

import json
from typing import Any, Protocol

__all__ = ["MID_TERM_SUMMARIZER_SYSTEM_PROMPT", "build_mid_term_user_prompt"]


class MidTermEventPackLike(Protocol):
    batch_index: int
    batch_total: int
    input_budget_tokens: int
    input_estimated_tokens: int
    first_event_id: str
    last_event_id: str
    event_count: int
    delta_event_count: int
    selected_unit_count: int
    semantic_units: list[dict[str, Any]]
    events: list[dict[str, Any]]


MID_TERM_SUMMARIZER_SYSTEM_PROMPT = (
    "You are a rigorous mid-term memory distillation engine.\n"
    "You must reason internally in steps, but do not reveal chain-of-thought.\n"
    "Internal reasoning protocol:\n"
    "1) Reconstruct the event timeline from old to new.\n"
    "2) Validate semantic units, especially tool CALL/RESULT pairs.\n"
    "3) Extract reusable context, decisions, progress, open questions, and candidate long-term memories.\n"
    "4) Bind every extracted statement to evidence_event_ids.\n"
    "5) Calibrate confidence conservatively when evidence is weak or conflicting.\n"
    "Hard constraints:\n"
    "- Use only facts supported by provided events.\n"
    "- Never fabricate missing tool results or user intent.\n"
    "- If uncertainty exists, keep lower confidence and explicit open_questions.\n"
    "- Output one strict JSON object only. No markdown and no extra text."
)


def build_mid_term_user_prompt(pack: MidTermEventPackLike) -> str:
    schema = {
        "active_context": [
            {"summary": "string", "evidence_event_ids": ["evt_xxx"], "confidence": 0.7}
        ],
        "decisions": [
            {"summary": "string", "evidence_event_ids": ["evt_xxx"], "stability": "tentative|stable"}
        ],
        "progress": [
            {
                "tool_name": "string",
                "call_summary": "string",
                "result_summary": "string",
                "success": True,
                "evidence_event_ids": ["evt_call", "evt_result"],
            }
        ],
        "open_questions": [{"question": "string", "evidence_event_ids": ["evt_xxx"]}],
        "candidate_long_term": [
            {
                "content": "string",
                "tags": ["preference"],
                "confidence": 0.7,
                "why_reusable": "string",
                "evidence_event_ids": ["evt_xxx"],
            }
        ],
        "artifact_refs": [
            {"path_or_file_id": "string", "reason": "string", "evidence_event_ids": ["evt_xxx"]}
        ],
    }
    input_payload = {
        "timeline_order": "old_to_new",
        "batch": {
            "index": pack.batch_index,
            "total": pack.batch_total,
        },
        "budget": {
            "input_budget_tokens": pack.input_budget_tokens,
            "input_estimated_tokens": pack.input_estimated_tokens,
        },
        "range": {
            "first_event_id": pack.first_event_id,
            "last_event_id": pack.last_event_id,
            "event_count": pack.event_count,
            "delta_event_count": pack.delta_event_count,
            "selected_unit_count": pack.selected_unit_count,
        },
        "semantic_units": pack.semantic_units,
        "events": pack.events,
    }
    return (
        "Task: distill this batch into structured mid-term memory JSON.\n"
        "Execution requirements:\n"
        "1) Rebuild timeline in provided old-to-new order.\n"
        "2) Treat each semantic unit as atomic, especially tool_pair units.\n"
        "3) Keep only reusable, evidence-backed information.\n"
        "4) Every output item must include evidence_event_ids from provided events.\n"
        "5) Use conservative confidence when evidence is weak.\n"
        "6) Output strict JSON object only.\n"
        f"Required schema:\n{json.dumps(schema, ensure_ascii=False)}\n"
        f"Event pack:\n{json.dumps(input_payload, ensure_ascii=False)}\n"
    )
