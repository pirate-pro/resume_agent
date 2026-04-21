"""Internal domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.errors import ValidationError

__all__ = [
    "AgentRunInput",
    "AgentRunOutput",
    "ContextBundle",
    "EventRecord",
    "MemoryItem",
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
class SessionMeta:
    session_id: str
    title: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.title = _require_non_empty("title", self.title)
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at cannot be earlier than created_at.")


@dataclass(slots=True)
class EventRecord:
    event_id: str
    session_id: str
    type: str
    payload: dict[str, Any]
    created_at: datetime

    def __post_init__(self) -> None:
        self.event_id = _require_non_empty("event_id", self.event_id)
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.type = _require_non_empty("type", self.type)
        if not isinstance(self.payload, dict):
            raise ValidationError("payload must be a dictionary.")


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

    def __post_init__(self) -> None:
        self.session_id = _require_non_empty("session_id", self.session_id)
        self.user_message = _require_non_empty("user_message", self.user_message)
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
