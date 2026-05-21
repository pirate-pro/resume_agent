"""Internal domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.errors import ValidationError

__all__ = [
    "AgentIdentityDocuments",
    "AgentRunInput",
    "AgentRunOutput",
    "ContextBundle",
    "EventRecord",
    "MemoryItem",
    "RunContext",
    "SessionArtifact",
    "SessionMeta",
    "ToolCall",
    "ToolDefinition",
    "ToolExecutionResult",
]



def _require_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _normalize_optional_string(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_non_empty(name, value)


def _normalize_string_metadata(metadata: dict[str, str]) -> dict[str, str]:
    if not isinstance(metadata, dict):
        raise ValidationError("metadata must be a dictionary.")
    normalized: dict[str, str] = {}
    for raw_key, raw_value in metadata.items():
        key = _require_non_empty("metadata key", str(raw_key))
        value = _require_non_empty("metadata value", str(raw_value))
        normalized[key] = value
    return normalized


@dataclass(slots=True)
class RunContext:
    session_id: str
    run_id: str
    agent_id: str
    turn_id: str
    entry_agent_id: str
    parent_run_id: str | None = None
    trace_flags: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.run_id = _require_non_empty("run_id", self.run_id)
        self.agent_id = _require_non_empty("agent_id", self.agent_id)
        self.turn_id = _require_non_empty("turn_id", self.turn_id)
        self.entry_agent_id = _require_non_empty("entry_agent_id", self.entry_agent_id)
        if self.parent_run_id is not None:
            self.parent_run_id = _require_non_empty("parent_run_id", self.parent_run_id)
        if not isinstance(self.trace_flags, dict):
            raise ValidationError("trace_flags must be a dictionary.")
        normalized_flags: dict[str, bool] = {}
        for raw_key, raw_value in self.trace_flags.items():
            key = _require_non_empty("trace_flag_key", str(raw_key))
            if not isinstance(raw_value, bool):
                raise ValidationError("trace_flags value must be bool.")
            normalized_flags[key] = raw_value
        self.trace_flags = normalized_flags


@dataclass(slots=True)
class SessionMeta:
    session_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    is_pinned: bool = False
    pinned_at: datetime | None = None
    participants: list[str] = field(default_factory=list)
    entry_agent_id: str | None = None

    def __post_init__(self) -> None:
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.title = _require_non_empty("title", self.title)
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at cannot be earlier than created_at.")
        if not isinstance(self.is_pinned, bool):
            raise ValidationError("is_pinned must be bool.")
        if self.pinned_at is not None and self.pinned_at < self.created_at:
            raise ValidationError("pinned_at cannot be earlier than created_at.")
        if self.entry_agent_id is not None:
            self.entry_agent_id = _require_non_empty("entry_agent_id", self.entry_agent_id)
        if not isinstance(self.participants, list):
            raise ValidationError("participants must be a list.")
        normalized_participants: list[str] = []
        seen: set[str] = set()
        for raw in self.participants:
            participant = _require_non_empty("participant", raw)
            if participant in seen:
                continue
            normalized_participants.append(participant)
            seen.add(participant)
        self.participants = normalized_participants


@dataclass(slots=True)
class EventRecord:
    event_id: str
    session_id: str
    type: str
    payload: dict[str, Any]
    created_at: datetime
    agent_id: str = "agent_main"
    run_id: str = "run_legacy"
    parent_run_id: str | None = None
    event_version: int = 2

    def __post_init__(self) -> None:
        self.event_id = _require_non_empty("event_id", self.event_id)
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.type = _require_non_empty("type", self.type)
        if not isinstance(self.payload, dict):
            raise ValidationError("payload must be a dictionary.")
        self.agent_id = _require_non_empty("agent_id", self.agent_id)
        self.run_id = _require_non_empty("run_id", self.run_id)
        if self.parent_run_id is not None:
            self.parent_run_id = _require_non_empty("parent_run_id", self.parent_run_id)
        if self.event_version <= 0:
            raise ValidationError("event_version must be positive.")


@dataclass(slots=True)
class SessionArtifact:
    artifact_id: str
    session_id: str
    kind: str
    title: str
    media_type: str
    size_bytes: int
    status: str
    visibility: str
    created_at: datetime
    updated_at: datetime
    storage_relpath: str
    text_relpath: str | None = None
    owner_agent_id: str | None = None
    description: str | None = None
    source_type: str | None = None
    source_event_id: str | None = None
    error: str | None = None
    text_char_count: int | None = None
    token_estimate: int | None = None
    parsed_at: datetime | None = None

    def __post_init__(self) -> None:
        self.artifact_id = _require_non_empty("artifact_id", self.artifact_id)
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.kind = _require_non_empty("kind", self.kind).lower()
        if self.kind not in {"uploaded_file", "pasted_text", "generated_file", "answer_file"}:
            raise ValidationError("kind must be one of uploaded_file/pasted_text/generated_file/answer_file.")
        self.title = _require_non_empty("title", self.title)
        self.media_type = _require_non_empty("media_type", self.media_type)
        self.storage_relpath = _require_non_empty("storage_relpath", self.storage_relpath)
        if self.size_bytes < 0:
            raise ValidationError("size_bytes cannot be negative.")
        self.status = _require_non_empty("status", self.status).lower()
        if self.status not in {"uploaded", "parsing", "ready", "failed"}:
            raise ValidationError("status must be one of uploaded/parsing/ready/failed.")
        self.visibility = _require_non_empty("visibility", self.visibility).lower()
        if self.visibility not in {"session_shared", "agent_private", "user_visible"}:
            raise ValidationError("visibility must be one of session_shared/agent_private/user_visible.")
        if self.text_relpath is not None:
            self.text_relpath = _require_non_empty("text_relpath", self.text_relpath)
        self.owner_agent_id = _normalize_optional_string("owner_agent_id", self.owner_agent_id)
        self.description = _normalize_optional_string("description", self.description)
        self.source_type = _normalize_optional_string("source_type", self.source_type)
        self.source_event_id = _normalize_optional_string("source_event_id", self.source_event_id)
        self.error = _normalize_optional_string("error", self.error)
        if self.text_char_count is not None and self.text_char_count < 0:
            raise ValidationError("text_char_count cannot be negative.")
        if self.token_estimate is not None and self.token_estimate < 0:
            raise ValidationError("token_estimate cannot be negative.")


@dataclass(slots=True)
class MemoryItem:
    memory_id: str
    session_id: str | None
    content: str
    tags: list[str]
    created_at: datetime
    source_event_id: str | None
    scope: str | None = None
    memory_layer: str | None = None
    source_kind: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.memory_id = _require_non_empty("memory_id", self.memory_id)
        self.content = _require_non_empty("content", self.content)
        self.session_id = _normalize_optional_string("session_id", self.session_id)
        self.source_event_id = _normalize_optional_string("source_event_id", self.source_event_id)
        self.scope = _normalize_optional_string("scope", self.scope)
        self.memory_layer = _normalize_optional_string("memory_layer", self.memory_layer)
        self.source_kind = _normalize_optional_string("source_kind", self.source_kind)
        self.metadata = _normalize_string_metadata(self.metadata)
        if not isinstance(self.tags, list):
            raise ValidationError("tags must be a list.")
        normalized_tags: list[str] = []
        for tag in self.tags:
            normalized_tags.append(_require_non_empty("tag", tag))
        self.tags = normalized_tags


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters_schema: dict[str, Any]

    def __post_init__(self) -> None:
        self.name = _require_non_empty("name", self.name)
        self.description = _require_non_empty("description", self.description)
        if not isinstance(self.parameters_schema, dict):
            raise ValidationError("parameters_schema must be a dictionary.")


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        self.name = _require_non_empty("name", self.name)
        if not isinstance(self.arguments, dict):
            raise ValidationError("arguments must be a dictionary.")
        if self.tool_call_id is not None:
            self.tool_call_id = _require_non_empty("tool_call_id", self.tool_call_id)


@dataclass(slots=True)
class ToolExecutionResult:
    tool_name: str
    success: bool
    content: str

    def __post_init__(self) -> None:
        self.tool_name = _require_non_empty("tool_name", self.tool_name)
        self.content = _require_non_empty("content", self.content)


@dataclass(slots=True)
class ContextBundle:
    system_prompt: str
    messages: list[dict[str, Any]]
    memory_hits: list[MemoryItem]
    tool_definitions: list[ToolDefinition]
    memory_summary: dict[str, Any] = field(default_factory=dict)
    memory_lanes: dict[str, list[MemoryItem]] = field(default_factory=dict)
    system_prompt_sections: list[dict[str, Any]] = field(default_factory=list)
    initial_visible_tool_names: list[str] = field(default_factory=list)
    runtime_tool_plan: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.system_prompt = _require_non_empty("system_prompt", self.system_prompt)
        if not isinstance(self.messages, list):
            raise ValidationError("messages must be a list.")
        if not isinstance(self.memory_hits, list):
            raise ValidationError("memory_hits must be a list.")
        if not isinstance(self.tool_definitions, list):
            raise ValidationError("tool_definitions must be a list.")
        if not isinstance(self.memory_summary, dict):
            raise ValidationError("memory_summary must be a dictionary.")
        if not isinstance(self.memory_lanes, dict):
            raise ValidationError("memory_lanes must be a dictionary.")
        if not isinstance(self.system_prompt_sections, list):
            raise ValidationError("system_prompt_sections must be a list.")
        if not isinstance(self.initial_visible_tool_names, list):
            raise ValidationError("initial_visible_tool_names must be a list.")
        if not isinstance(self.runtime_tool_plan, dict):
            raise ValidationError("runtime_tool_plan must be a dictionary.")
        normalized_lanes: dict[str, list[MemoryItem]] = {}
        for raw_key, raw_items in self.memory_lanes.items():
            key = _require_non_empty("memory_lane", str(raw_key))
            if not isinstance(raw_items, list):
                raise ValidationError("memory_lanes values must be lists.")
            normalized_lanes[key] = raw_items
        self.memory_lanes = normalized_lanes
        normalized_initial_tools: list[str] = []
        seen_initial_tools: set[str] = set()
        for raw_name in self.initial_visible_tool_names:
            name = _require_non_empty("initial_visible_tool_name", str(raw_name))
            if name in seen_initial_tools:
                continue
            normalized_initial_tools.append(name)
            seen_initial_tools.add(name)
        self.initial_visible_tool_names = normalized_initial_tools
        self.runtime_tool_plan = dict(self.runtime_tool_plan)


@dataclass(slots=True)
class AgentIdentityDocuments:
    agent_markdown: str | None = None
    soul_markdown: str | None = None

    def __post_init__(self) -> None:
        if self.agent_markdown is not None:
            self.agent_markdown = _require_non_empty("agent_markdown", self.agent_markdown)
        if self.soul_markdown is not None:
            self.soul_markdown = _require_non_empty("soul_markdown", self.soul_markdown)


@dataclass(slots=True)
class AgentRunInput:
    session_id: str
    user_message: str
    skill_names: list[str]
    max_tool_rounds: int
    context: RunContext

    def __post_init__(self) -> None:
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.user_message = _require_non_empty("user_message", self.user_message)
        if not isinstance(self.context, RunContext):
            raise ValidationError("context must be RunContext.")
        if self.context.session_id != self.session_id:
            raise ValidationError("context.session_id must equal session_id.")
        if not isinstance(self.skill_names, list):
            raise ValidationError("skill_names must be a list.")
        normalized_skill_names: list[str] = []
        for skill_name in self.skill_names:
            normalized_skill_names.append(_require_non_empty("skill_name", skill_name))
        self.skill_names = normalized_skill_names
        if self.max_tool_rounds < 0 or self.max_tool_rounds > 20:
            raise ValidationError("max_tool_rounds must be in range 0..20.")


@dataclass(slots=True)
class AgentRunOutput:
    session_id: str
    answer: str
    tool_calls: list[ToolCall]
    memory_hits: list[MemoryItem]

    def __post_init__(self) -> None:
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.answer = _require_non_empty("answer", self.answer)
        if not isinstance(self.tool_calls, list):
            raise ValidationError("tool_calls must be a list.")
        if not isinstance(self.memory_hits, list):
            raise ValidationError("memory_hits must be a list.")
