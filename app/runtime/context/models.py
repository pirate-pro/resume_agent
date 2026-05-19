"""Data models for context assembly."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.core.errors import ValidationError
from app.domain.models import EventRecord, MemoryItem
from app.runtime.agent_events import AgentResultSummaryPayload, AgentTaskAssignedPayload
from app.state.models import StateRecord


class ContextAssemblyRole(str, Enum):
    MAIN_AGENT = "main_agent"
    OTHER_AGENT = "other_agent"


@dataclass(slots=True)
class AgentCatalogItem:
    """Prompt-safe metadata for a child agent the current agent may invoke."""

    agent_id: str
    display_name: str
    role: str
    description: str

    def __post_init__(self) -> None:
        self.agent_id = _normalize_non_empty("agent_id", self.agent_id)
        self.display_name = _normalize_non_empty("display_name", self.display_name)
        self.role = _normalize_non_empty("role", self.role)
        self.description = _normalize_non_empty("description", self.description)


@dataclass(slots=True)
class ContextSection:
    """One renderable prompt section with a stable internal name."""

    name: str
    content: str
    item_count: int = 1
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("section name must be a non-empty string.")
        self.name = self.name.strip()
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValidationError("section content must be a non-empty string.")
        if self.item_count < 0:
            raise ValidationError("section item_count cannot be negative.")
        if not isinstance(self.metadata, dict):
            raise ValidationError("section metadata must be a dictionary.")


@dataclass(slots=True)
class ContextAssemblyPlan:
    """Role-aware section plan for one model invocation."""

    role: ContextAssemblyRole
    sections: list[ContextSection]

    def __post_init__(self) -> None:
        if not isinstance(self.role, ContextAssemblyRole):
            raise ValidationError("role must be ContextAssemblyRole.")
        if not isinstance(self.sections, list):
            raise ValidationError("sections must be a list.")

    def render_prompt(self) -> str:
        return "\n\n".join(section.content for section in self.sections)

    def section_names(self) -> list[str]:
        return [section.name for section in self.sections]

    def summary(self) -> dict[str, int | str | list[str]]:
        return {
            "role": self.role.value,
            "section_count": len(self.sections),
            "sections": self.section_names(),
        }


@dataclass(slots=True)
class CurrentWorkflowState:
    """Compact current-turn product refs derived from successful tool results."""

    refs: dict[str, str] = field(default_factory=dict)
    source_tools: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.refs, dict):
            raise ValidationError("workflow state refs must be a dictionary.")
        if not isinstance(self.source_tools, dict):
            raise ValidationError("workflow state source_tools must be a dictionary.")
        normalized_refs: dict[str, str] = {}
        for raw_key, raw_value in self.refs.items():
            key = _normalize_non_empty("workflow state key", str(raw_key))
            value = _normalize_non_empty("workflow state value", str(raw_value))
            normalized_refs[key] = value
        normalized_sources: dict[str, str] = {}
        for raw_key, raw_value in self.source_tools.items():
            key = _normalize_non_empty("workflow state source key", str(raw_key))
            value = _normalize_non_empty("workflow state source value", str(raw_value))
            if key in normalized_refs:
                normalized_sources[key] = value
        self.refs = normalized_refs
        self.source_tools = normalized_sources

    def is_empty(self) -> bool:
        return not self.refs


@dataclass(slots=True)
class CareerFlowState:
    """Semantic career workflow state derived from deterministic runtime facts."""

    refs: dict[str, str] = field(default_factory=dict)
    multi_refs: dict[str, list[str]] = field(default_factory=dict)
    completed_steps: list[str] = field(default_factory=list)
    missing_steps: list[str] = field(default_factory=list)
    do_not_repeat_tools: list[str] = field(default_factory=list)
    next_action_hint: str | None = None
    final_answer_ready: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.refs, dict):
            raise ValidationError("career flow refs must be a dictionary.")
        if not isinstance(self.multi_refs, dict):
            raise ValidationError("career flow multi_refs must be a dictionary.")
        self.refs = {
            _normalize_non_empty("career flow ref key", str(key)): _normalize_non_empty(
                "career flow ref value", str(value)
            )
            for key, value in self.refs.items()
        }
        normalized_multi_refs: dict[str, list[str]] = {}
        for raw_key, raw_values in self.multi_refs.items():
            key = _normalize_non_empty("career flow multi ref key", str(raw_key))
            if not isinstance(raw_values, list):
                raise ValidationError("career flow multi ref values must be lists.")
            values: list[str] = []
            seen: set[str] = set()
            for raw_value in raw_values:
                value = _normalize_non_empty("career flow multi ref value", str(raw_value))
                if value in seen:
                    continue
                values.append(value)
                seen.add(value)
            if values:
                normalized_multi_refs[key] = values
        self.multi_refs = normalized_multi_refs
        self.completed_steps = _normalize_string_list("completed_steps", self.completed_steps)
        self.missing_steps = _normalize_string_list("missing_steps", self.missing_steps)
        self.do_not_repeat_tools = _normalize_string_list("do_not_repeat_tools", self.do_not_repeat_tools)
        if self.next_action_hint is not None:
            self.next_action_hint = _normalize_non_empty("next_action_hint", self.next_action_hint)
        if not isinstance(self.final_answer_ready, bool):
            raise ValidationError("final_answer_ready must be a boolean.")

    def is_empty(self) -> bool:
        return (
            not self.refs
            and not self.multi_refs
            and not self.completed_steps
            and not self.missing_steps
            and not self.do_not_repeat_tools
            and self.next_action_hint is None
            and not self.final_answer_ready
        )


@dataclass(slots=True)
class ShortTermContextPlan:
    """Role-aware short-term context selected for one invocation."""

    role: ContextAssemblyRole
    agent_state: list[StateRecord]
    orchestration_state: list[StateRecord]
    recent_events: list[EventRecord]
    context_summaries: list[EventRecord]
    assigned_tasks: list[AgentTaskAssignedPayload]
    child_result_summaries: list[AgentResultSummaryPayload]
    workflow_state: CurrentWorkflowState = field(default_factory=CurrentWorkflowState)
    career_flow_state: CareerFlowState = field(default_factory=CareerFlowState)

    def __post_init__(self) -> None:
        if not isinstance(self.role, ContextAssemblyRole):
            raise ValidationError("short-term role must be ContextAssemblyRole.")
        if not isinstance(self.agent_state, list):
            raise ValidationError("agent_state must be a list.")
        if not isinstance(self.orchestration_state, list):
            raise ValidationError("orchestration_state must be a list.")
        if not isinstance(self.recent_events, list):
            raise ValidationError("recent_events must be a list.")
        if not isinstance(self.context_summaries, list):
            raise ValidationError("context_summaries must be a list.")
        if not isinstance(self.assigned_tasks, list):
            raise ValidationError("assigned_tasks must be a list.")
        if not isinstance(self.child_result_summaries, list):
            raise ValidationError("child_result_summaries must be a list.")
        if not isinstance(self.workflow_state, CurrentWorkflowState):
            raise ValidationError("workflow_state must be CurrentWorkflowState.")
        if not isinstance(self.career_flow_state, CareerFlowState):
            raise ValidationError("career_flow_state must be CareerFlowState.")


@dataclass(slots=True)
class MemoryContextSlices:
    long_term_summaries: list[MemoryItem]
    facts_by_lane: dict[str, list[MemoryItem]]
    mid_term_items: list[MemoryItem]


def _normalize_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _normalize_string_list(name: str, values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(f"{name} must be a list.")
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = _normalize_non_empty(name, str(raw))
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output
