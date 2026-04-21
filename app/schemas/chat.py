"""HTTP request/response schemas for chat endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "EventView",
    "MemoryView",
    "ToolCallView",
]


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    skill_names: list[str] = Field(default_factory=list)
    max_tool_rounds: int = Field(default=3, ge=0, le=10)

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
    type: str
    payload: dict[str, Any]
    created_at: datetime
