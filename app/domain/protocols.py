"""Protocol definitions for pluggable components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.domain.models import EventRecord, MemoryItem, SessionMeta, ToolCall, ToolDefinition, ToolExecutionResult

__all__ = [
    "ChatModelClient",
    "MemoryRepository",
    "ModelResponse",
    "SessionRepository",
    "SkillRepository",
    "ToolExecutor",
]


@dataclass(slots=True)
class ModelResponse:
    content: str
    tool_calls: list[ToolCall]


class SessionRepository(Protocol):
    def create_session(self, session_id: str) -> SessionMeta: ...

    def get_session(self, session_id: str) -> SessionMeta | None: ...

    def append_event(self, session_id: str, event: EventRecord) -> None: ...

    def list_events(self, session_id: str) -> list[EventRecord]: ...

    def list_recent_events(self, session_id: str, limit: int) -> list[EventRecord]: ...

    def get_workspace_path(self, session_id: str) -> Path: ...


class MemoryRepository(Protocol):
    def add_memory(self, item: MemoryItem) -> None: ...

    def search(self, query: str, limit: int) -> list[MemoryItem]: ...

    def list_memories(self, limit: int) -> list[MemoryItem]: ...


class SkillRepository(Protocol):
    def load_skills(self, skill_names: list[str]) -> dict[str, str]: ...


class ChatModelClient(Protocol):
    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse: ...


class ToolExecutor(Protocol):
    def list_definitions(self) -> list[ToolDefinition]: ...

    def execute(self, call: ToolCall, session_id: str) -> ToolExecutionResult: ...
