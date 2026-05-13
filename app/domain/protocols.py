"""Protocol definitions for pluggable components."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.domain.models import (
    AgentIdentityDocuments,
    EventRecord,
    RunContext,
    SessionArtifact,
    SessionMeta,
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
)

__all__ = [
    "AgentDocumentRepository",
    "ChatModelClient",
    "ModelResponse",
    "StreamChunk",
    "SessionRepository",
    "SkillSummaryRecord",
    "SkillRepository",
    "ToolExecutor",
]


@dataclass(slots=True)
class ModelResponse:
    content: str
    tool_calls: list[ToolCall]
    reasoning_content: str = ""


@dataclass(slots=True)
class StreamChunk:
    delta: str = ""
    reasoning_delta: str = ""
    tool_calls: list[ToolCall] | None = None
    finished: bool = False
    has_tool_call_delta: bool = False


class SessionRepository(Protocol):
    def create_session(self, session_id: str) -> SessionMeta: ...

    def get_session(self, session_id: str) -> SessionMeta | None: ...

    def update_session_title(self, session_id: str, title: str) -> SessionMeta: ...

    def update_session_pin(self, session_id: str, is_pinned: bool) -> SessionMeta: ...

    def list_sessions(self) -> list[SessionMeta]: ...

    def list_session_messages(self, session_id: str) -> list[dict[str, object]]: ...

    def delete_session(self, session_id: str) -> None: ...

    def append_event(self, session_id: str, event: EventRecord) -> None: ...

    def append_agent_event(self, session_id: str, agent_id: str, event: EventRecord) -> None: ...

    def append_orchestration_event(self, session_id: str, event: EventRecord) -> None: ...

    def replace_events(self, session_id: str, events: list[EventRecord]) -> None: ...

    def replace_events_if_unchanged(
        self,
        session_id: str,
        events: list[EventRecord],
        *,
        expected_last_event_id: str,
    ) -> bool: ...

    def replace_agent_events_if_unchanged(
        self,
        session_id: str,
        agent_id: str,
        events: list[EventRecord],
        *,
        expected_last_event_id: str,
    ) -> bool: ...

    def list_events(self, session_id: str) -> list[EventRecord]: ...

    def list_agent_events(self, session_id: str, agent_id: str) -> list[EventRecord]: ...

    def list_orchestration_events(self, session_id: str) -> list[EventRecord]: ...

    def list_run_events(self, session_id: str, agent_id: str, run_id: str) -> list[EventRecord]: ...

    def list_recent_events(self, session_id: str, limit: int) -> list[EventRecord]: ...

    def get_workspace_path(self, session_id: str) -> Path: ...

    def get_agent_workspace_path(self, session_id: str, agent_id: str) -> Path: ...

    def get_session_root_path(self, session_id: str) -> Path: ...

    def add_or_update_session_artifact(self, artifact: SessionArtifact) -> None: ...

    def list_session_artifacts(self, session_id: str) -> list[SessionArtifact]: ...

    def get_session_artifact(self, session_id: str, artifact_id: str) -> SessionArtifact | None: ...

    def set_active_artifact_ids(self, session_id: str, artifact_ids: list[str]) -> list[str]: ...

    def get_active_artifact_ids(self, session_id: str) -> list[str]: ...

    def read_session_artifact_text(self, session_id: str, artifact_id: str) -> str: ...


class SkillSummaryRecord(Protocol):
    name: str
    description: str


class SkillRepository(Protocol):
    def load_skills(self, skill_names: list[str]) -> dict[str, str]: ...

    def list_skills(self) -> Sequence[SkillSummaryRecord]: ...


class AgentDocumentRepository(Protocol):
    def load_documents(self, agent_id: str) -> AgentIdentityDocuments: ...


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
