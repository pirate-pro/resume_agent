"""File-backed store for user note assets."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypeVar
from uuid import uuid4

from app.core.errors import StorageError, ValidationError
from app.core.time import app_now, from_app_iso, normalize_app_datetime, to_app_iso
from app.notes.models import (
    Note,
    NoteCollection,
    NoteCollectionKind,
    NoteRecordStatus,
    NoteSourceRef,
    NoteSourceType,
    validate_collection_id,
    validate_evidence_refs,
    validate_note_id,
    validate_source_refs,
)

__all__ = ["NoteStore"]

_RecordT = TypeVar("_RecordT", Note, NoteCollection)
_NOTE_UPDATE_FIELDS = {
    "body_format",
    "body_markdown",
    "collection_id",
    "evidence_refs",
    "related_application_id",
    "source_artifact_id",
    "source_refs",
    "summary",
    "tags",
    "title",
}
_COLLECTION_UPDATE_FIELDS = {
    "description",
    "kind",
    "name",
    "tags",
}


class NoteStore:
    """Persist user note records as atomic JSON files."""

    def __init__(self, root_dir: Path, clock: Callable[[], datetime] | None = None) -> None:
        if not isinstance(root_dir, Path):
            raise ValidationError("root_dir must be pathlib.Path.")
        self._root_dir = root_dir
        self._clock = clock or _app_now
        self._notes_dir = self._root_dir / "notes"
        self._collections_dir = self._root_dir / "collections"
        for path in (self._notes_dir, self._collections_dir):
            path.mkdir(parents=True, exist_ok=True)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise ValidationError("clock must return datetime.")
        return normalize_app_datetime(value)

    def save_note(self, record: Note) -> Note:
        if not isinstance(record, Note):
            raise ValidationError("record must be Note.")
        validated = record.copy()
        path = self._note_path(validated.note_id)
        stamped = _stamp_record(validated, _read_record(path, _note_from_payload), self._now())
        _write_json_payload(path, _note_to_payload(stamped))
        return stamped.copy()

    def get_note(self, note_id: str) -> Note | None:
        return _read_record(self._note_path(validate_note_id(note_id)), _note_from_payload)

    def list_notes(
        self,
        *,
        include_archived: bool = False,
        collection_id: str | None = None,
        related_application_id: str | None = None,
    ) -> list[Note]:
        normalized_collection_id = None
        if collection_id is not None:
            normalized_collection_id = validate_collection_id(collection_id)
        records = [_read_record_required(path, _note_from_payload) for path in sorted(self._notes_dir.glob("*.json"))]
        filtered = _filter_and_sort(records, include_archived=include_archived)
        if normalized_collection_id is not None:
            filtered = [record for record in filtered if record.collection_id == normalized_collection_id]
        if related_application_id is not None:
            filtered = [record for record in filtered if record.related_application_id == related_application_id]
        return [record.copy() for record in filtered]

    def update_note(self, note_id: str, *, updates: dict[str, Any]) -> Note:
        record = self.get_note(note_id)
        if record is None:
            raise ValidationError(f"Note not found: {note_id}")
        normalized_updates = _normalize_update_payload(updates, allowed_fields=_NOTE_UPDATE_FIELDS)
        values: dict[str, Any] = {}
        for field_name, raw_value in normalized_updates.items():
            if field_name == "source_refs":
                values[field_name] = _source_refs_from_raw(raw_value)
            else:
                values[field_name] = raw_value
        updated = replace(record, **values)
        return self.save_note(updated)

    def append_note(
        self,
        note_id: str,
        *,
        body_markdown: str,
        source_refs: list[NoteSourceRef] | None = None,
        evidence_refs: list[str] | None = None,
    ) -> Note:
        record = self.get_note(note_id)
        if record is None:
            raise ValidationError(f"Note not found: {note_id}")
        append_text = _require_non_empty("body_markdown", body_markdown)
        merged_source_refs = record.source_refs
        if source_refs is not None:
            merged_source_refs = _merge_source_refs(record.source_refs, validate_source_refs(source_refs))
        merged_evidence_refs = record.evidence_refs
        if evidence_refs is not None:
            merged_evidence_refs = _merge_string_lists(record.evidence_refs, validate_evidence_refs(evidence_refs))
        updated = replace(
            record,
            body_markdown=f"{record.body_markdown}\n\n{append_text}",
            source_refs=merged_source_refs,
            evidence_refs=merged_evidence_refs,
        )
        return self.save_note(updated)

    def archive_note(self, note_id: str) -> Note | None:
        record = self.get_note(note_id)
        if record is None:
            return None
        return self.save_note(replace(record, status=NoteRecordStatus.ARCHIVED))

    def save_collection(self, record: NoteCollection) -> NoteCollection:
        if not isinstance(record, NoteCollection):
            raise ValidationError("record must be NoteCollection.")
        validated = record.copy()
        path = self._collection_path(validated.collection_id)
        stamped = _stamp_record(validated, _read_record(path, _collection_from_payload), self._now())
        _write_json_payload(path, _collection_to_payload(stamped))
        return stamped.copy()

    def get_collection(self, collection_id: str) -> NoteCollection | None:
        return _read_record(
            self._collection_path(validate_collection_id(collection_id)),
            _collection_from_payload,
        )

    def list_collections(self, *, include_archived: bool = False) -> list[NoteCollection]:
        records = [
            _read_record_required(path, _collection_from_payload)
            for path in sorted(self._collections_dir.glob("*.json"))
        ]
        return _filter_and_sort(records, include_archived=include_archived)

    def update_collection(self, collection_id: str, *, updates: dict[str, Any]) -> NoteCollection:
        record = self.get_collection(collection_id)
        if record is None:
            raise ValidationError(f"NoteCollection not found: {collection_id}")
        normalized_updates = _normalize_update_payload(updates, allowed_fields=_COLLECTION_UPDATE_FIELDS)
        updated = replace(record, **normalized_updates)
        return self.save_collection(updated)

    def archive_collection(self, collection_id: str) -> NoteCollection | None:
        record = self.get_collection(collection_id)
        if record is None:
            return None
        return self.save_collection(replace(record, status=NoteRecordStatus.ARCHIVED))

    def _note_path(self, note_id: str) -> Path:
        return self._notes_dir / f"{note_id}.json"

    def _collection_path(self, collection_id: str) -> Path:
        return self._collections_dir / f"{collection_id}.json"


def _note_to_payload(record: Note) -> dict[str, Any]:
    return {
        "body_format": record.body_format,
        "body_markdown": record.body_markdown,
        "collection_id": record.collection_id,
        "created_at": _to_iso(record.created_at),
        "evidence_refs": record.evidence_refs,
        "note_id": record.note_id,
        "related_application_id": record.related_application_id,
        "source_artifact_id": record.source_artifact_id,
        "source_refs": [_source_ref_to_payload(source_ref) for source_ref in record.source_refs],
        "source_session_id": record.source_session_id,
        "status": record.status.value,
        "summary": record.summary,
        "tags": record.tags,
        "title": record.title,
        "updated_at": _to_iso(record.updated_at),
    }


def _note_from_payload(payload: dict[str, Any]) -> Note:
    return Note(
        note_id=payload["note_id"],
        status=payload["status"],
        source_session_id=payload["source_session_id"],
        source_artifact_id=payload["source_artifact_id"],
        evidence_refs=payload["evidence_refs"],
        created_at=_from_iso(payload["created_at"]),
        updated_at=_from_iso(payload["updated_at"]),
        title=payload["title"],
        body_markdown=payload["body_markdown"],
        body_format=payload.get("body_format", "markdown"),
        collection_id=payload.get("collection_id"),
        tags=payload.get("tags", []),
        source_refs=_source_refs_from_payload(payload.get("source_refs", [])),
        related_application_id=payload.get("related_application_id"),
        summary=payload.get("summary", ""),
    )


def _collection_to_payload(record: NoteCollection) -> dict[str, Any]:
    return {
        "collection_id": record.collection_id,
        "created_at": _to_iso(record.created_at),
        "description": record.description,
        "kind": record.kind.value,
        "name": record.name,
        "source_session_id": record.source_session_id,
        "status": record.status.value,
        "tags": record.tags,
        "updated_at": _to_iso(record.updated_at),
    }


def _collection_from_payload(payload: dict[str, Any]) -> NoteCollection:
    return NoteCollection(
        collection_id=payload["collection_id"],
        status=payload["status"],
        source_session_id=payload["source_session_id"],
        created_at=_from_iso(payload["created_at"]),
        updated_at=_from_iso(payload["updated_at"]),
        name=payload["name"],
        description=payload.get("description", ""),
        kind=payload.get("kind", NoteCollectionKind.GENERAL.value),
        tags=payload.get("tags", []),
    )


def _source_ref_to_payload(record: NoteSourceRef) -> dict[str, Any]:
    return {
        "quote": record.quote,
        "source_id": record.source_id,
        "source_session_id": record.source_session_id,
        "source_type": _source_type_value(record.source_type),
        "title": record.title,
    }


def _source_refs_from_payload(value: Any) -> list[NoteSourceRef]:
    if not isinstance(value, list):
        raise ValidationError("source_refs must be a list.")
    refs: list[NoteSourceRef] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValidationError("source_refs values must be objects.")
        refs.append(
            NoteSourceRef(
                source_type=item["source_type"],
                source_id=item.get("source_id"),
                source_session_id=item.get("source_session_id"),
                title=item.get("title", ""),
                quote=item.get("quote", ""),
            )
        )
    return validate_source_refs(refs)


def _source_refs_from_raw(value: Any) -> list[NoteSourceRef]:
    if isinstance(value, list) and all(isinstance(item, NoteSourceRef) for item in value):
        return validate_source_refs(value)
    return _source_refs_from_payload(value)


def _read_record(path: Path, parser: Callable[[dict[str, Any]], _RecordT]) -> _RecordT | None:
    if not path.exists():
        return None
    return _read_record_required(path, parser)


def _read_record_required(path: Path, parser: Callable[[dict[str, Any]], _RecordT]) -> _RecordT:
    payload = _read_json_payload(path)
    try:
        return parser(payload)
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise StorageError(f"Invalid note product record '{path}': {exc}") from exc


def _read_json_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StorageError(f"Invalid note product JSON '{path}': {exc}") from exc
    except OSError as exc:
        raise StorageError(f"Failed to read note product record '{path}': {exc}") from exc
    if not isinstance(payload, dict):
        raise StorageError(f"Invalid note product JSON '{path}': root must be object.")
    return payload


def _write_json_payload(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(path)
    except OSError as exc:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise StorageError(f"Failed to write note product record '{path}': {exc}") from exc


def _filter_and_sort(records: list[_RecordT], *, include_archived: bool) -> list[_RecordT]:
    output = [
        record
        for record in records
        if include_archived or record.status == NoteRecordStatus.ACTIVE
    ]
    output.sort(key=lambda item: (item.updated_at, item.created_at), reverse=True)
    return [record.copy() for record in output]


def _stamp_record(record: _RecordT, existing: _RecordT | None, now: datetime) -> _RecordT:
    created_at = existing.created_at if existing is not None else now
    return replace(record, created_at=created_at, updated_at=now)


def _normalize_update_payload(updates: dict[str, Any], *, allowed_fields: set[str]) -> dict[str, Any]:
    if not isinstance(updates, dict):
        raise ValidationError("updates must be a dictionary.")
    normalized: dict[str, Any] = {}
    for key, value in updates.items():
        if not isinstance(key, str) or not key.strip():
            raise ValidationError("updates keys must be non-empty strings.")
        normalized_key = key.strip()
        if normalized_key not in allowed_fields:
            raise ValidationError(f"Unsupported note update field: {normalized_key}")
        if normalized_key in normalized:
            raise ValidationError(f"Duplicate update field: {normalized_key}")
        normalized[normalized_key] = value
    return normalized


def _merge_string_lists(existing: list[str], additions: list[str]) -> list[str]:
    output = list(existing)
    seen = set(output)
    for item in additions:
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _merge_source_refs(existing: list[NoteSourceRef], additions: list[NoteSourceRef]) -> list[NoteSourceRef]:
    output = [source_ref.copy() for source_ref in existing]
    seen = {_source_ref_key(source_ref) for source_ref in output}
    for source_ref in additions:
        normalized = source_ref.copy()
        key = _source_ref_key(normalized)
        if key in seen:
            continue
        output.append(normalized)
        seen.add(key)
    return output


def _source_ref_key(source_ref: NoteSourceRef) -> tuple[str, str | None, str | None, str, str]:
    return (
        _source_type_value(source_ref.source_type),
        source_ref.source_id,
        source_ref.source_session_id,
        source_ref.title,
        source_ref.quote,
    )


def _require_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _source_type_value(value: NoteSourceType | str) -> str:
    if isinstance(value, NoteSourceType):
        return value.value
    return value


def _app_now() -> datetime:
    return app_now()


def _to_iso(value: datetime) -> str:
    return to_app_iso(value)


def _from_iso(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValidationError("timestamp must be an ISO datetime string.")
    return from_app_iso(value)
