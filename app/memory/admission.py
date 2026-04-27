"""Admission rules for deciding whether content should enter memory."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "MemoryAdmissionDecision",
    "MemoryAdmissionResult",
    "evaluate_memory_admission",
]

_STATE_TAGS = {"todo", "next_step", "scratch", "temp", "ephemeral", "working_state", "session_state"}
_LONG_OR_SHARED_TAGS = {
    "long",
    "long_term",
    "preference",
    "constraint",
    "policy",
    "profile",
    "memory",
    "shared",
    "global",
    "cross_agent",
}
_WORKING_STATE_PATTERNS = [
    re.compile(
        r"^(当前目标|当前任务|下一步|待办|工作备注|工作笔记|临时(?:记录|备注|说明|约束|决定)?|本轮(?:目标|计划)?|本次(?:任务|会话))\s*[:：\-]?",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"^(current\s+goal|current\s+task|next\s+step|todo|to-do|working\s+note|temporary\s+(?:note|plan|decision))\b\s*[:\-]?",
        flags=re.IGNORECASE,
    ),
]


class MemoryAdmissionDecision(str, Enum):
    ACCEPT_MEMORY = "accept_memory"
    REJECT_USE_STATE = "reject_use_state"
    REJECT_NOT_MEMORY = "reject_not_memory"


@dataclass(slots=True)
class MemoryAdmissionResult:
    decision: MemoryAdmissionDecision
    reason: str

    @property
    def accepted(self) -> bool:
        return self.decision == MemoryAdmissionDecision.ACCEPT_MEMORY


def evaluate_memory_admission(content: str, tags: list[str]) -> MemoryAdmissionResult:
    normalized_content = content.strip()
    normalized_tags = {tag.strip().lower() for tag in tags if isinstance(tag, str) and tag.strip()}

    if _looks_like_working_state(normalized_content, normalized_tags):
        return MemoryAdmissionResult(
            decision=MemoryAdmissionDecision.REJECT_USE_STATE,
            reason="This looks like session working state; use state_set instead of memory_write.",
        )

    if _looks_like_non_memory_blob(normalized_content):
        return MemoryAdmissionResult(
            decision=MemoryAdmissionDecision.REJECT_NOT_MEMORY,
            reason="This looks like raw file/tool output, not reusable memory. Summarize the stable takeaway first.",
        )

    return MemoryAdmissionResult(
        decision=MemoryAdmissionDecision.ACCEPT_MEMORY,
        reason="accepted",
    )


def _looks_like_working_state(content: str, tags: set[str]) -> bool:
    if tags.intersection(_STATE_TAGS):
        return True
    if "plan" in tags and not tags.intersection(_LONG_OR_SHARED_TAGS):
        lowered = content.lower()
        if lowered.startswith(("下一步", "待办", "todo", "to-do", "next step", "current goal", "current task")):
            return True
    for pattern in _WORKING_STATE_PATTERNS:
        if pattern.search(content):
            return True
    return False


def _looks_like_non_memory_blob(content: str) -> bool:
    if "```" in content:
        return True
    stripped = content.strip()
    if not stripped:
        return False
    if stripped[0] in {"{", "["} and stripped[-1] in {"}", "]"}:
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return False
        if isinstance(parsed, dict) and len(parsed) >= 2:
            return True
        if isinstance(parsed, list) and len(parsed) >= 2:
            return True
    return False
