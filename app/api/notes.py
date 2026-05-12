"""Note asset HTTP endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import TypeVar, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_note_store
from app.api.presenters import note_collection_view, note_view
from app.api.responses import ok
from app.core.errors import ValidationError
from app.core.time import app_now
from app.notes.models import Note, NoteCollection, NoteCollectionKind, NoteRecordStatus, NoteSourceRef
from app.notes.store import NoteStore
from app.schemas.common import StandardResponse
from app.schemas.notes import (
    NoteAppendRequest,
    NoteCollectionCreateRequest,
    NoteCollectionUpdateRequest,
    NoteCollectionView,
    NoteCreateRequest,
    NoteSourceRefPayload,
    NoteUpdateRequest,
    NoteView,
)

__all__ = ["router"]

router = APIRouter(prefix="/api/notes", tags=["notes"])
_RecordT = TypeVar("_RecordT", Note, NoteCollection)


@router.get("", response_model=StandardResponse[list[NoteView]])
def list_notes(
    include_archived: bool = Query(default=False),
    collection_id: str | None = Query(default=None),
    related_application_id: str | None = Query(default=None),
    store: NoteStore = Depends(get_note_store),
) -> StandardResponse[list[NoteView]]:
    return ok([
        note_view(item)
        for item in store.list_notes(
            include_archived=include_archived,
            collection_id=collection_id,
            related_application_id=related_application_id,
        )
    ])


@router.post("", response_model=StandardResponse[NoteView])
def create_note(
    request: NoteCreateRequest,
    store: NoteStore = Depends(get_note_store),
) -> StandardResponse[NoteView]:
    record = Note(
        note_id=request.note_id or _new_note_id(),
        status=NoteRecordStatus.ACTIVE,
        source_session_id=request.source_session_id,
        source_artifact_id=request.source_artifact_id,
        evidence_refs=request.evidence_refs,
        created_at=_placeholder_time(),
        updated_at=_placeholder_time(),
        title=request.title,
        body_markdown=request.body_markdown,
        body_format=request.body_format,
        collection_id=request.collection_id,
        tags=request.tags,
        source_refs=_source_refs(request.source_refs),
        related_application_id=request.related_application_id,
        summary=request.summary,
    )
    return ok(note_view(store.save_note(record)))


@router.get("/collections", response_model=StandardResponse[list[NoteCollectionView]])
def list_collections(
    include_archived: bool = Query(default=False),
    store: NoteStore = Depends(get_note_store),
) -> StandardResponse[list[NoteCollectionView]]:
    return ok([
        note_collection_view(item)
        for item in store.list_collections(include_archived=include_archived)
    ])


@router.post("/collections", response_model=StandardResponse[NoteCollectionView])
def create_collection(
    request: NoteCollectionCreateRequest,
    store: NoteStore = Depends(get_note_store),
) -> StandardResponse[NoteCollectionView]:
    record = NoteCollection(
        collection_id=request.collection_id or _new_collection_id(),
        status=NoteRecordStatus.ACTIVE,
        source_session_id=request.source_session_id,
        created_at=_placeholder_time(),
        updated_at=_placeholder_time(),
        name=request.name,
        description=request.description,
        kind=cast(NoteCollectionKind, request.kind),
        tags=request.tags,
    )
    return ok(note_collection_view(store.save_collection(record)))


@router.get("/collections/{collection_id}", response_model=StandardResponse[NoteCollectionView])
def get_collection(
    collection_id: str,
    include_archived: bool = Query(default=False),
    store: NoteStore = Depends(get_note_store),
) -> StandardResponse[NoteCollectionView]:
    record = _require_visible(
        store.get_collection(collection_id),
        include_archived=include_archived,
        record_type="NoteCollection",
        record_id=collection_id,
    )
    return ok(note_collection_view(record))


@router.patch("/collections/{collection_id}", response_model=StandardResponse[NoteCollectionView])
def update_collection(
    collection_id: str,
    request: NoteCollectionUpdateRequest,
    store: NoteStore = Depends(get_note_store),
) -> StandardResponse[NoteCollectionView]:
    _require_visible(
        store.get_collection(collection_id),
        include_archived=False,
        record_type="NoteCollection",
        record_id=collection_id,
    )
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise ValidationError("NoteCollection update must include at least one editable field.")
    return ok(note_collection_view(store.update_collection(collection_id, updates=updates)))


@router.post("/collections/{collection_id}/archive", response_model=StandardResponse[NoteCollectionView])
def archive_collection(
    collection_id: str,
    store: NoteStore = Depends(get_note_store),
) -> StandardResponse[NoteCollectionView]:
    record = store.archive_collection(collection_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NoteCollection not found: {collection_id}",
        )
    return ok(note_collection_view(record))


@router.get("/{note_id}", response_model=StandardResponse[NoteView])
def get_note(
    note_id: str,
    include_archived: bool = Query(default=False),
    store: NoteStore = Depends(get_note_store),
) -> StandardResponse[NoteView]:
    record = _require_visible(
        store.get_note(note_id),
        include_archived=include_archived,
        record_type="Note",
        record_id=note_id,
    )
    return ok(note_view(record))


@router.patch("/{note_id}", response_model=StandardResponse[NoteView])
def update_note(
    note_id: str,
    request: NoteUpdateRequest,
    store: NoteStore = Depends(get_note_store),
) -> StandardResponse[NoteView]:
    _require_visible(
        store.get_note(note_id),
        include_archived=False,
        record_type="Note",
        record_id=note_id,
    )
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise ValidationError("Note update must include at least one editable field.")
    return ok(note_view(store.update_note(note_id, updates=updates)))


@router.post("/{note_id}/append", response_model=StandardResponse[NoteView])
def append_note(
    note_id: str,
    request: NoteAppendRequest,
    store: NoteStore = Depends(get_note_store),
) -> StandardResponse[NoteView]:
    _require_visible(
        store.get_note(note_id),
        include_archived=False,
        record_type="Note",
        record_id=note_id,
    )
    record = store.append_note(
        note_id,
        body_markdown=request.body_markdown,
        source_refs=_source_refs(request.source_refs),
        evidence_refs=request.evidence_refs,
    )
    return ok(note_view(record))


@router.post("/{note_id}/archive", response_model=StandardResponse[NoteView])
def archive_note(
    note_id: str,
    store: NoteStore = Depends(get_note_store),
) -> StandardResponse[NoteView]:
    record = store.archive_note(note_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Note not found: {note_id}")
    return ok(note_view(record))


def _require_visible(
    record: _RecordT | None,
    *,
    include_archived: bool,
    record_type: str,
    record_id: str,
) -> _RecordT:
    if record is None or (record.status == NoteRecordStatus.ARCHIVED and not include_archived):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{record_type} not found: {record_id}",
        )
    return record


def _source_refs(values: list[NoteSourceRefPayload]) -> list[NoteSourceRef]:
    return [
        NoteSourceRef(
            source_type=item.source_type,
            source_id=item.source_id,
            source_session_id=item.source_session_id,
            title=item.title,
            quote=item.quote,
        )
        for item in values
    ]


def _new_note_id() -> str:
    return f"note_{uuid4().hex}"


def _new_collection_id() -> str:
    return f"collection_{uuid4().hex}"


def _placeholder_time() -> datetime:
    return app_now()
