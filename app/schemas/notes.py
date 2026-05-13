"""HTTP schemas for note asset endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "NoteAppendRequest",
    "NoteCollectionCreateRequest",
    "NoteCollectionUpdateRequest",
    "NoteCollectionView",
    "NoteCreateRequest",
    "NoteSourceRefPayload",
    "NoteUpdateRequest",
    "NoteView",
]


class NoteSourceRefPayload(BaseModel):
    source_type: str
    source_id: str | None = None
    source_session_id: str | None = None
    title: str = ""
    quote: str = ""


class NoteView(BaseModel):
    note_id: str
    status: str
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    title: str
    body_markdown: str
    body_format: str = "markdown"
    note_type: str = "note"
    collection_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_refs: list[NoteSourceRefPayload] = Field(default_factory=list)
    related_application_id: str | None = None
    summary: str = ""


class NoteCollectionView(BaseModel):
    collection_id: str
    status: str
    source_session_id: str
    created_at: datetime
    updated_at: datetime
    name: str
    description: str = ""
    kind: str = "general"
    tags: list[str] = Field(default_factory=list)


class NoteCreateRequest(BaseModel):
    note_id: str | None = None
    source_session_id: str
    source_artifact_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    title: str
    body_markdown: str
    body_format: str = "markdown"
    note_type: str = "note"
    collection_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_refs: list[NoteSourceRefPayload] = Field(default_factory=list)
    related_application_id: str | None = None
    summary: str = ""


class NoteUpdateRequest(BaseModel):
    source_artifact_id: str | None = None
    evidence_refs: list[str] | None = None
    title: str | None = None
    body_markdown: str | None = None
    body_format: str | None = None
    note_type: str | None = None
    collection_id: str | None = None
    tags: list[str] | None = None
    source_refs: list[NoteSourceRefPayload] | None = None
    related_application_id: str | None = None
    summary: str | None = None


class NoteAppendRequest(BaseModel):
    body_markdown: str
    source_refs: list[NoteSourceRefPayload] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class NoteCollectionCreateRequest(BaseModel):
    collection_id: str | None = None
    source_session_id: str
    name: str
    description: str = ""
    kind: str = "general"
    tags: list[str] = Field(default_factory=list)


class NoteCollectionUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    kind: str | None = None
    tags: list[str] | None = None
