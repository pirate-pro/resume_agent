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
    "1) Reconstruct the old-to-new timeline from semantic_units.\n"
    "2) Resolve corrections by timeline order; the latest explicit correction wins.\n"
    "3) Validate atomic semantic units, especially tool CALL/RESULT pairs.\n"
    "4) Extract reusable context, decisions, progress, open questions, and candidate long-term memories.\n"
    "5) Bind every extracted statement to evidence_event_ids.\n"
    "6) Calibrate confidence conservatively when evidence is weak or conflicting.\n"
    "7) Never silently omit explicit user corrections, current goals, architecture decisions, open questions, "
    "artifact references, or tool outcomes.\n"
    "Hard constraints:\n"
    "- Use semantic_units as the source of content. event_index is only for event id/type validation.\n"
    "- Use only facts supported by provided semantic_units.\n"
    "- Never fabricate missing tool results or user intent.\n"
    "- If uncertainty exists, keep lower confidence and explicit open_questions.\n"
    "- If a tool_pair semantic unit affects task progress, progress must include both call and result evidence.\n"
    "- Progress should prioritize high-signal, latest, corrective, failed, decision-supporting, or artifact-related "
    "tool pairs. Do not list repetitive low-value tool pairs as progress.\n"
    "- If a later tool_result verifies a corrected value or latest state, include that exact tool_result in progress.\n"
    "- If the user changes a preference, name, goal, or constraint, keep the latest value and mention the correction.\n"
    "- Candidate long-term memories must be reusable beyond this single run, not raw logs.\n"
    "- Preserve the user's language and exact technical terms, file paths, tool names, variable names, and quoted values. "
    "If source events are Chinese, output Chinese.\n"
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
        "source_of_truth": "semantic_units",
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
        "semantic_units": [_semantic_unit_for_prompt(item) for item in pack.semantic_units if isinstance(item, dict)],
        "event_index": [
            {
                "event_id": str(item.get("event_id", "")),
                "type": str(item.get("type", "")),
                "created_at": str(item.get("created_at", "")),
            }
            for item in pack.events
            if isinstance(item, dict)
        ],
    }
    return (
        "Task: distill this batch into structured mid-term memory JSON.\n"
        "Execution requirements:\n"
        "1) Rebuild timeline in provided old-to-new order.\n"
        "2) Treat each semantic unit as atomic, especially tool_pair units.\n"
        "3) Keep only reusable, evidence-backed information.\n"
        "4) Every output item must include evidence_event_ids from event_index.\n"
        "5) Use conservative confidence when evidence is weak.\n"
        "6) For tool_pair units that contributed to progress, write one progress item with both [call,result] evidence ids.\n"
        "7) Progress selection rule: keep high-signal/latest/corrective tool results; skip repetitive noise results.\n"
        "8) For conflicting facts, keep the latest explicit correction and do not preserve obsolete values as active facts.\n"
        "9) Coverage checklist before final JSON: explicit user corrections/latest values, current goals, "
        "architecture decisions/rules, tool outcomes, open questions, artifact/file references.\n"
        "10) Preserve original language and key terms verbatim, especially Chinese phrases like user names, goals, "
        "tool_call/tool_result rules, file names, and quoted tool results.\n"
        "11) Output strict JSON object only.\n"
        f"Required schema:\n{json.dumps(schema, ensure_ascii=False)}\n"
        f"Event pack:\n{json.dumps(input_payload, ensure_ascii=False)}\n"
    )


def _semantic_unit_for_prompt(unit: dict[str, Any]) -> dict[str, Any]:
    """Keep prompt input compact; event_index already carries event id/type metadata."""
    return {
        "unit_id": str(unit.get("unit_id", "")),
        "unit_type": str(unit.get("unit_type", "")),
        "event_ids": [str(item) for item in unit.get("event_ids", []) if isinstance(item, str) and item.strip()],
        "created_at": str(unit.get("created_at", "")),
        "summary": unit.get("summary") if isinstance(unit.get("summary"), dict) else {},
        "estimated_tokens": unit.get("estimated_tokens"),
    }
