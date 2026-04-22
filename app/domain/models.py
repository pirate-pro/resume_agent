"""Internal domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.errors import ValidationError

__all__ = [
    "AgentRunInput",
    "AgentRunOutput",
    "ContextBundle",
    "EventRecord",
    "MemoryItem",
    "RunContext",
    "SessionFile",
    "SessionMeta",
    "ToolCall",
    "ToolDefinition",
    "ToolExecutionResult",
]



def _require_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


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
    participants: list[str] = field(default_factory=list)
    entry_agent_id: str | None = None

    def __post_init__(self) -> None:
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.title = _require_non_empty("title", self.title)
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at cannot be earlier than created_at.")
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
class SessionFile:
    file_id: str
    session_id: str
    filename: str
    media_type: str
    size_bytes: int
    status: str
    uploaded_at: datetime
    storage_relpath: str
    text_relpath: str | None = None
    error: str | None = None
    parsed_char_count: int | None = None
    parsed_token_estimate: int | None = None
    parsed_at: datetime | None = None

    def __post_init__(self) -> None:
        self.file_id = _require_non_empty("file_id", self.file_id)
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.filename = _require_non_empty("filename", self.filename)
        self.media_type = _require_non_empty("media_type", self.media_type)
        self.storage_relpath = _require_non_empty("storage_relpath", self.storage_relpath)
        if self.size_bytes < 0:
            raise ValidationError("size_bytes cannot be negative.")
        normalized_status = _require_non_empty("status", self.status).lower()
        if normalized_status not in {"uploaded", "ready", "failed"}:
            raise ValidationError("status must be one of uploaded/ready/failed.")
        self.status = normalized_status
        if self.text_relpath is not None:
            self.text_relpath = _require_non_empty("text_relpath", self.text_relpath)
        if self.error is not None:
            self.error = _require_non_empty("error", self.error)
        if self.parsed_char_count is not None and self.parsed_char_count < 0:
            raise ValidationError("parsed_char_count cannot be negative.")
        if self.parsed_token_estimate is not None and self.parsed_token_estimate < 0:
            raise ValidationError("parsed_token_estimate cannot be negative.")


@dataclass(slots=True)
class MemoryItem:
    memory_id: str
    session_id: str | None
    content: str
    tags: list[str]
    created_at: datetime
    source_event_id: str | None

    def __post_init__(self) -> None:
        self.memory_id = _require_non_empty("memory_id", self.memory_id)
        self.content = _require_non_empty("content", self.content)
        if self.session_id is not None:
            self.session_id = _require_non_empty("session_id", self.session_id)
        if self.source_event_id is not None:
            self.source_event_id = _require_non_empty("source_event_id", self.source_event_id)
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

    def __post_init__(self) -> None:
        self.system_prompt = _require_non_empty("system_prompt", self.system_prompt)
        if not isinstance(self.messages, list):
            raise ValidationError("messages must be a list.")
        if not isinstance(self.memory_hits, list):
            raise ValidationError("memory_hits must be a list.")
        if not isinstance(self.tool_definitions, list):
            raise ValidationError("tool_definitions must be a list.")


@dataclass(slots=True)
class AgentRunInput:
    session_id: str
    user_message: str
    skill_names: list[str]
    max_tool_rounds: int
    context: RunContext | None = None

    def __post_init__(self) -> None:
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.user_message = _require_non_empty("user_message", self.user_message)
        if self.context is not None:
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
        if self.max_tool_rounds < 0 or self.max_tool_rounds > 10:
            raise ValidationError("max_tool_rounds must be in range 0..10.")


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
