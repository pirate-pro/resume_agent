"""Protocol definitions for pluggable components."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.domain.models import (
    EventRecord,
    MemoryItem,
    RunContext,
    SessionFile,
    SessionMeta,
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
)

__all__ = [
    "ChatModelClient",
    "MemoryRepository",
    "ModelResponse",
    "StreamChunk",
    "SessionRepository",
    "SkillRepository",
    "ToolExecutor",
]


@dataclass(slots=True)
class ModelResponse:
    content: str
    tool_calls: list[ToolCall]


@dataclass(slots=True)
class StreamChunk:
    delta: str = ""
    tool_calls: list[ToolCall] | None = None
    finished: bool = False
    has_tool_call_delta: bool = False


class SessionRepository(Protocol):
    def create_session(self, session_id: str) -> SessionMeta: ...

    def get_session(self, session_id: str) -> SessionMeta | None: ...

    def list_sessions(self) -> list[SessionMeta]: ...

    def list_session_messages(self, session_id: str) -> list[dict[str, object]]: ...

    def delete_session(self, session_id: str) -> None: ...

    def append_event(self, session_id: str, event: EventRecord) -> None: ...

    def list_events(self, session_id: str) -> list[EventRecord]: ...

    def list_recent_events(self, session_id: str, limit: int) -> list[EventRecord]: ...

    def get_workspace_path(self, session_id: str) -> Path: ...

    def get_session_root_path(self, session_id: str) -> Path: ...

    def add_or_update_session_file(self, file_record: SessionFile) -> None: ...

    def list_session_files(self, session_id: str) -> list[SessionFile]: ...

    def get_session_file(self, session_id: str, file_id: str) -> SessionFile | None: ...

    def set_active_file_ids(self, session_id: str, file_ids: list[str]) -> list[str]: ...

    def get_active_file_ids(self, session_id: str) -> list[str]: ...

    def read_session_file_text(self, session_id: str, file_id: str) -> str: ...


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

    def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]: ...


class ToolExecutor(Protocol):
    def list_definitions(self) -> list[ToolDefinition]: ...

    def execute(self, call: ToolCall, context: RunContext) -> ToolExecutionResult: ...
