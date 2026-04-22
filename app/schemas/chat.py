"""HTTP request/response schemas for chat endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "ActiveFilesRequest",
    "ChatRequest",
    "ChatResponse",
    "EventView",
    "FileUploadRequest",
    "SessionFileView",
    "SessionFilesResponse",
    "MemoryView",
    "ToolCallView",
]


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    skill_names: list[str] = Field(default_factory=list)
    max_tool_rounds: int = Field(default=3, ge=0, le=10)
    active_file_ids: list[str] | None = None
    entry_agent_id: str = "agent_main"
    trace_level: Literal["basic", "verbose"] = "basic"

    @field_validator("session_id")
    @classmethod
    def _validate_optional_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message cannot be empty.")
        return normalized

    @field_validator("skill_names")
    @classmethod
    def _validate_skill_names(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for skill_name in value:
            skill = skill_name.strip()
            if not skill:
                raise ValueError("skill_names cannot contain blank entries.")
            normalized.append(skill)
        return normalized

    @field_validator("active_file_ids")
    @classmethod
    def _validate_active_file_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for file_id in value:
            item = file_id.strip()
            if not item:
                raise ValueError("active_file_ids cannot contain blank entries.")
            if item in seen:
                continue
            normalized.append(item)
            seen.add(item)
        return normalized

    @field_validator("entry_agent_id")
    @classmethod
    def _validate_entry_agent_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("entry_agent_id cannot be empty.")
        return normalized


class ToolCallView(BaseModel):
    name: str
    arguments: dict[str, Any]


class MemoryView(BaseModel):
    memory_id: str
    content: str
    tags: list[str]


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    tool_calls: list[ToolCallView]
    memory_hits: list[MemoryView]


class EventView(BaseModel):
    event_id: str
    session_id: str
    agent_id: str
    run_id: str
    parent_run_id: str | None = None
    event_version: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


class SessionFileView(BaseModel):
    file_id: str
    filename: str
    media_type: str
    size_bytes: int
    status: str
    uploaded_at: datetime
    error: str | None = None
    parsed_char_count: int | None = None
    parsed_token_estimate: int | None = None
    parsed_at: datetime | None = None


class SessionFilesResponse(BaseModel):
    session_id: str
    active_file_ids: list[str]
    files: list[SessionFileView]


class ActiveFilesRequest(BaseModel):
    file_ids: list[str] = Field(default_factory=list)

    @field_validator("file_ids")
    @classmethod
    def _validate_file_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for file_id in value:
            item = file_id.strip()
            if not item:
                raise ValueError("file_ids cannot contain blank entries.")
            if item in seen:
                continue
            normalized.append(item)
            seen.add(item)
        return normalized


class FileUploadRequest(BaseModel):
    filename: str
    content_base64: str
    auto_activate: bool = True

    @field_validator("filename")
    @classmethod
    def _validate_filename(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("filename cannot be empty.")
        return normalized

    @field_validator("content_base64")
    @classmethod
    def _validate_content_base64(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content_base64 cannot be empty.")
        return normalized
