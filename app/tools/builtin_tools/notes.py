"""Built-in tools for user note assets."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, cast
from uuid import uuid4

from app.core.errors import StorageError, ToolExecutionError, ValidationError
from app.core.time import app_now, to_app_iso
from app.domain.models import RunContext, ToolDefinition, ToolExecutionResult
from app.domain.protocols import SessionRepository
from app.notes.models import (
    Note,
    NoteCollection,
    NoteCollectionKind,
    NoteOrigin,
    NoteRecordStatus,
    NoteSourceRef,
    NoteSourceType,
    NoteType,
)
from app.notes.store import NoteStore
from app.tools.builtin_tools.common import validate_context
from app.tools.builtin_tools.session_artifact_helpers import require_session_artifact

__all__ = [
    "NoteAppendTool",
    "NoteArchiveTool",
    "NoteCollectionArchiveTool",
    "NoteCollectionCreateTool",
    "NoteCollectionGetTool",
    "NoteCollectionListTool",
    "NoteCollectionUpdateTool",
    "NoteCreateTool",
    "NoteGetTool",
    "NoteListTool",
    "NoteUpdateTool",
]

_NOTE_UPDATE_FIELDS = {
    "body_format",
    "body_markdown",
    "collection_id",
    "evidence_refs",
    "note_type",
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
_SOURCE_TYPE_ALIASES = {
    "application": NoteSourceType.CAREER_APPLICATION.value,
    "career_application": NoteSourceType.CAREER_APPLICATION.value,
    "resume_profile": NoteSourceType.RESUME_PROFILE.value,
    "career_resume_profile": NoteSourceType.RESUME_PROFILE.value,
    "career_profile": NoteSourceType.CAREER_PROFILE.value,
    "jd": NoteSourceType.JD_ANALYSIS.value,
    "jd_analysis": NoteSourceType.JD_ANALYSIS.value,
    "career_jd_analysis": NoteSourceType.JD_ANALYSIS.value,
    "fit": NoteSourceType.JOB_FIT_REPORT.value,
    "job_fit": NoteSourceType.JOB_FIT_REPORT.value,
    "job_fit_report": NoteSourceType.JOB_FIT_REPORT.value,
    "career_job_fit_report": NoteSourceType.JOB_FIT_REPORT.value,
    "resume_version": NoteSourceType.RESUME_VERSION.value,
    "career_resume_version": NoteSourceType.RESUME_VERSION.value,
    "artifact": NoteSourceType.ARTIFACT.value,
    "chat_message": NoteSourceType.CHAT_MESSAGE.value,
    "message": NoteSourceType.CHAT_MESSAGE.value,
    "manual": NoteSourceType.MANUAL.value,
}
_TYPED_REF_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*[:=]\s*([A-Za-z0-9][A-Za-z0-9_-]*)\s*$")


class NoteCreateTool:
    """Create one user-visible note asset."""

    def __init__(self, note_store: NoteStore, session_repository: SessionRepository) -> None:
        self._note_store = note_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="note_create",
            description=(
                "Create a user-visible editable note only when the user explicitly asks to save or organize content "
                "as a note. This tool does not write memory."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "string"},
                    "source_artifact_id": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "title": {"type": "string"},
                    "body_markdown": {"type": "string"},
                    "body_format": {"type": "string", "enum": ["markdown"], "default": "markdown"},
                    "note_type": {
                        "type": "string",
                        "enum": ["note", "learning", "resource"],
                        "default": "note",
                        "description": "Use note for general records, learning for study notes, resource for links/interview materials/assets.",
                    },
                    "collection_id": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "source_refs": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": (
                            "Structured source refs: source_type, source_id, source_session_id, title, quote. "
                            "Supported source_type values are artifact, career_application, resume_profile, "
                            "career_profile, jd_analysis, job_fit_report, resume_version, chat_message, manual. "
                            "Common aliases such as application, jd, fit, career_jd_analysis, and "
                            "career_resume_profile are canonicalized."
                        ),
                    },
                    "related_application_id": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["title", "body_markdown"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            note_id = _optional_prefixed_id(args.get("note_id"), "note") or _new_id("note")
            existing = self._note_store.get_note(note_id)
            if existing is not None:
                return _record_result(
                    "note_create",
                    "note",
                    existing.note_id,
                    existing,
                    extra={"idempotent_reused": True},
                )

            source_artifact_id = _optional_current_artifact(
                self._session_repository,
                run_context.session_id,
                args.get("source_artifact_id"),
                field_name="source_artifact_id",
            )
            evidence_refs = _optional_evidence_refs(args.get("evidence_refs"))
            source_refs = _source_refs(args.get("source_refs"))
            if source_artifact_id is not None:
                evidence_refs = _append_unique_strings(evidence_refs, [source_artifact_id])
                if not any(ref.source_type == "artifact" and ref.source_id == source_artifact_id for ref in source_refs):
                    source_refs.append(
                        NoteSourceRef(
                            source_type="artifact",
                            source_id=source_artifact_id,
                            source_session_id=run_context.session_id,
                        )
                    )

            record = Note(
                note_id=note_id,
                status=NoteRecordStatus.ACTIVE,
                source_session_id=run_context.session_id,
                source_artifact_id=source_artifact_id,
                evidence_refs=evidence_refs,
                created_at=_now(),
                updated_at=_now(),
                title=_required_string(args.get("title"), field_name="title"),
                body_markdown=_required_string(args.get("body_markdown"), field_name="body_markdown"),
                body_format=_optional_string(args.get("body_format")) or "markdown",
                note_type=_optional_string(args.get("note_type")) or "note",
                origin=NoteOrigin.AGENT,
                collection_id=_optional_prefixed_id(args.get("collection_id"), "collection"),
                tags=_optional_string_list(args.get("tags"), field_name="tags"),
                source_refs=source_refs,
                related_application_id=_optional_prefixed_id(args.get("related_application_id"), "application"),
                summary=_optional_string(args.get("summary")) or "",
            )
            saved = self._note_store.save_note(record)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("note_create", "note", saved.note_id, saved)


class NoteGetTool:
    """Read one note."""

    def __init__(self, note_store: NoteStore) -> None:
        self._note_store = note_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="note_get",
            description="Read a saved note by note_id. Call note_list first if unsure.",
            parameters_schema={
                "type": "object",
                "properties": {"note_id": {"type": "string"}},
                "required": ["note_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _required_string(args.get("note_id"), field_name="note_id")
            record = self._note_store.get_note(record_id)
            if record is None:
                return _not_found_result("note_get", "note", record_id)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("note_get", "note", record.note_id, record)


class NoteListTool:
    """List notes."""

    def __init__(self, note_store: NoteStore) -> None:
        self._note_store = note_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="note_list",
            description="List saved notes. Optional filters: collection_id, related_application_id.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "include_archived": {"type": "boolean", "default": False},
                    "collection_id": {"type": "string"},
                    "related_application_id": {"type": "string"},
                },
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        args = _require_arguments(arguments)
        records = self._note_store.list_notes(
            include_archived=_optional_bool(args.get("include_archived")),
            collection_id=_optional_prefixed_id(args.get("collection_id"), "collection"),
            related_application_id=_optional_prefixed_id(args.get("related_application_id"), "application"),
        )
        return _list_result("note_list", "note", records)


class NoteUpdateTool:
    """Update editable fields on one note."""

    def __init__(self, note_store: NoteStore, session_repository: SessionRepository) -> None:
        self._note_store = note_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="note_update",
            description=(
                "Update editable note fields. Allowed fields: title, body_markdown, tags, summary, collection_id, "
                "note_type, source_refs, source_artifact_id, related_application_id, evidence_refs. "
                "This tool does not write memory."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "string"},
                    "updates": {"type": "object"},
                },
                "required": ["note_id", "updates"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _required_string(args.get("note_id"), field_name="note_id")
            updates = _note_update_payload(args.get("updates"))
            raw_source_artifact_id = updates.get("source_artifact_id")
            if raw_source_artifact_id is not None:
                updates["source_artifact_id"] = _optional_current_artifact(
                    self._session_repository,
                    run_context.session_id,
                    raw_source_artifact_id,
                    field_name="source_artifact_id",
                )
            if "collection_id" in updates:
                updates["collection_id"] = _optional_prefixed_id(updates.get("collection_id"), "collection")
            if "related_application_id" in updates:
                updates["related_application_id"] = _optional_prefixed_id(
                    updates.get("related_application_id"),
                    "application",
                )
            record = self._note_store.update_note(record_id, updates=updates)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("note_update", "note", record.note_id, record)


class NoteAppendTool:
    """Append markdown content to one note."""

    def __init__(self, note_store: NoteStore) -> None:
        self._note_store = note_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="note_append",
            description="Append markdown content to an existing note without overwriting the current note body.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "string"},
                    "body_markdown": {"type": "string"},
                    "source_refs": {"type": "array", "items": {"type": "object"}},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["note_id", "body_markdown"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record = self._note_store.append_note(
                _required_string(args.get("note_id"), field_name="note_id"),
                body_markdown=_required_string(args.get("body_markdown"), field_name="body_markdown"),
                source_refs=_source_refs(args.get("source_refs")),
                evidence_refs=_optional_evidence_refs(args.get("evidence_refs")),
            )
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("note_append", "note", record.note_id, record)


class NoteArchiveTool:
    """Archive one note."""

    def __init__(self, note_store: NoteStore) -> None:
        self._note_store = note_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="note_archive",
            description="Archive a note without deleting the underlying JSON record.",
            parameters_schema={
                "type": "object",
                "properties": {"note_id": {"type": "string"}},
                "required": ["note_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _required_string(args.get("note_id"), field_name="note_id")
            record = self._note_store.archive_note(record_id)
            if record is None:
                return _not_found_result("note_archive", "note", record_id)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("note_archive", "note", record.note_id, record)


class NoteCollectionCreateTool:
    """Create one note collection."""

    def __init__(self, note_store: NoteStore) -> None:
        self._note_store = note_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="note_collection_create",
            description="Create a user-visible note collection for grouping notes. This tool does not write memory.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "collection_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["general", "career_project", "interview", "learning", "resume", "resource"],
                    },
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            collection_id = _optional_prefixed_id(args.get("collection_id"), "collection") or _new_id("collection")
            existing = self._note_store.get_collection(collection_id)
            if existing is not None:
                return _record_result(
                    "note_collection_create",
                    "note_collection",
                    existing.collection_id,
                    existing,
                    extra={"idempotent_reused": True},
                )
            record = NoteCollection(
                collection_id=collection_id,
                status=NoteRecordStatus.ACTIVE,
                source_session_id=run_context.session_id,
                created_at=_now(),
                updated_at=_now(),
                name=_required_string(args.get("name"), field_name="name"),
                description=_optional_string(args.get("description")) or "",
                kind=cast(NoteCollectionKind, _optional_string(args.get("kind")) or "general"),
                tags=_optional_string_list(args.get("tags"), field_name="tags"),
            )
            saved = self._note_store.save_collection(record)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("note_collection_create", "note_collection", saved.collection_id, saved)


class NoteCollectionGetTool:
    """Read one note collection."""

    def __init__(self, note_store: NoteStore) -> None:
        self._note_store = note_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="note_collection_get",
            description="Read a saved note collection by collection_id.",
            parameters_schema={
                "type": "object",
                "properties": {"collection_id": {"type": "string"}},
                "required": ["collection_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _required_string(args.get("collection_id"), field_name="collection_id")
            record = self._note_store.get_collection(record_id)
            if record is None:
                return _not_found_result("note_collection_get", "note_collection", record_id)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("note_collection_get", "note_collection", record.collection_id, record)


class NoteCollectionListTool:
    """List note collections."""

    def __init__(self, note_store: NoteStore) -> None:
        self._note_store = note_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="note_collection_list",
            description="List saved note collections.",
            parameters_schema={
                "type": "object",
                "properties": {"include_archived": {"type": "boolean", "default": False}},
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        args = _require_arguments(arguments)
        records = self._note_store.list_collections(include_archived=_optional_bool(args.get("include_archived")))
        return _list_result("note_collection_list", "note_collection", records)


class NoteCollectionUpdateTool:
    """Update editable fields on one note collection."""

    def __init__(self, note_store: NoteStore) -> None:
        self._note_store = note_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="note_collection_update",
            description="Update editable note collection fields: name, description, kind, tags.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "collection_id": {"type": "string"},
                    "updates": {"type": "object"},
                },
                "required": ["collection_id", "updates"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record = self._note_store.update_collection(
                _required_string(args.get("collection_id"), field_name="collection_id"),
                updates=_collection_update_payload(args.get("updates")),
            )
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("note_collection_update", "note_collection", record.collection_id, record)


class NoteCollectionArchiveTool:
    """Archive one note collection."""

    def __init__(self, note_store: NoteStore) -> None:
        self._note_store = note_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="note_collection_archive",
            description="Archive a note collection without deleting the underlying JSON record.",
            parameters_schema={
                "type": "object",
                "properties": {"collection_id": {"type": "string"}},
                "required": ["collection_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _required_string(args.get("collection_id"), field_name="collection_id")
            record = self._note_store.archive_collection(record_id)
            if record is None:
                return _not_found_result("note_collection_archive", "note_collection", record_id)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("note_collection_archive", "note_collection", record.collection_id, record)


def _require_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ToolExecutionError("Tool arguments must be an object.")
    path_fields = {"path", "file_path", "workspace_path", "absolute_path", "relative_path"}
    store_owned_fields = {"created_at", "updated_at", "source_session_id", "status"}
    for key in arguments:
        if not isinstance(key, str) or not key.strip():
            raise ToolExecutionError("Tool argument keys must be non-empty strings.")
        normalized_key = key.strip()
        if normalized_key in path_fields:
            raise ToolExecutionError(f"Path arguments are not allowed: {key}")
        if normalized_key in store_owned_fields:
            raise ToolExecutionError(f"Store-owned fields are not accepted: {key}")
    return arguments


def _optional_current_artifact(
    session_repository: SessionRepository,
    session_id: str,
    raw: Any,
    *,
    field_name: str,
) -> str | None:
    if raw is None:
        return None
    artifact_id = _required_string(raw, field_name=field_name)
    try:
        artifact = require_session_artifact(session_repository, session_id, artifact_id)
    except ToolExecutionError as exc:
        raise ToolExecutionError(f"{field_name} must reference a current session artifact: {artifact_id}") from exc
    return artifact.artifact_id


def _required_string(raw: Any, *, field_name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ToolExecutionError(f"'{field_name}' must be a non-empty string.")
    return raw.strip()


def _optional_string(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ToolExecutionError("optional string argument must be a string.")
    normalized = raw.strip()
    return normalized or None


def _optional_prefixed_id(raw: Any, prefix: str) -> str | None:
    value = _optional_string(raw)
    if value is None:
        return None
    marker = f"{prefix}_"
    stem = value[len(marker):] if value.startswith(marker) else value
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    if not slug:
        return None
    return f"{marker}{slug[:100]}"


def _optional_string_list(raw: Any, *, field_name: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    if not isinstance(raw, list):
        raise ToolExecutionError(f"'{field_name}' must be a list of strings.")
    output: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ToolExecutionError(f"each '{field_name}' item must be a non-empty string.")
        output.append(item.strip())
    return output


def _optional_evidence_refs(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str) and raw.strip():
        return [_normalize_evidence_ref_string(raw)]
    if not isinstance(raw, list):
        raise ToolExecutionError("'evidence_refs' must be a list of strings.")
    output: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            output.append(_normalize_evidence_ref_string(item))
            continue
        if isinstance(item, dict):
            ref = _evidence_ref_from_object(item)
            if ref is not None:
                output.append(_normalize_evidence_ref_string(ref))
                continue
        raise ToolExecutionError("each 'evidence_refs' item must be a non-empty string or source ref object.")
    return _append_unique_strings([], output)


def _evidence_ref_from_object(raw: dict[str, Any]) -> str | None:
    for key in (
        "source_id",
        "record_id",
        "id",
        "artifact_id",
        "application_id",
        "resume_profile_id",
        "career_profile_id",
        "jd_analysis_id",
        "job_fit_report_id",
        "resume_version_id",
        "note_id",
        "learning_task_id",
    ):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_evidence_ref_string(raw: str) -> str:
    value = raw.strip().strip("`")
    match = _TYPED_REF_RE.fullmatch(value)
    if match is None:
        return value
    source_type = _SOURCE_TYPE_ALIASES.get(match.group(1).strip().lower())
    if source_type is None:
        return value
    return match.group(2).strip()


def _source_refs(raw: Any) -> list[NoteSourceRef]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = _json_object_or_array(raw, field_name="source_refs")
    if not isinstance(raw, list):
        raise ToolExecutionError("'source_refs' must be a list of objects.")
    refs: list[NoteSourceRef] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ToolExecutionError("each 'source_refs' item must be an object.")
        source_type = _canonical_source_type(
            _required_string(item.get("source_type"), field_name="source_type")
        )
        source_id = _normalize_source_ref_id(
            _optional_string(item.get("source_id")),
            source_type=source_type,
        )
        refs.append(
            NoteSourceRef(
                source_type=source_type,
                source_id=source_id,
                source_session_id=_optional_string(item.get("source_session_id")),
                title=_optional_string(item.get("title")) or "",
                quote=_optional_string(item.get("quote")) or "",
            )
        )
    return refs


def _canonical_source_type(raw: str) -> str:
    normalized = raw.strip().lower()
    return _SOURCE_TYPE_ALIASES.get(normalized, normalized)


def _normalize_source_ref_id(raw: str | None, *, source_type: str) -> str | None:
    if raw is None:
        return None
    value = raw.strip().strip("`")
    match = _TYPED_REF_RE.fullmatch(value)
    if match is None:
        return value
    typed_source_type = _canonical_source_type(match.group(1))
    if typed_source_type != source_type:
        return value
    return match.group(2).strip()


def _note_update_payload(raw: Any) -> dict[str, Any]:
    payload = _required_dict(raw, field_name="updates")
    _reject_unsupported_fields(payload, _NOTE_UPDATE_FIELDS, payload_name="updates")
    if "source_refs" in payload:
        payload["source_refs"] = _source_refs(payload["source_refs"])
    if "evidence_refs" in payload:
        payload["evidence_refs"] = _optional_evidence_refs(payload["evidence_refs"])
    if "tags" in payload:
        payload["tags"] = _optional_string_list(payload["tags"], field_name="tags")
    return payload


def _collection_update_payload(raw: Any) -> dict[str, Any]:
    payload = _required_dict(raw, field_name="updates")
    _reject_unsupported_fields(payload, _COLLECTION_UPDATE_FIELDS, payload_name="updates")
    if "tags" in payload:
        payload["tags"] = _optional_string_list(payload["tags"], field_name="tags")
    return payload


def _required_dict(raw: Any, *, field_name: str) -> dict[str, Any]:
    if isinstance(raw, str):
        decoded = _json_object_or_array(raw, field_name=field_name)
        raw = decoded
    if not isinstance(raw, dict):
        raise ToolExecutionError(f"'{field_name}' must be an object.")
    return dict(raw)


def _json_object_or_array(raw: str, *, field_name: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolExecutionError(f"'{field_name}' must be valid JSON.") from exc


def _reject_unsupported_fields(payload: dict[str, Any], allowed: set[str], *, payload_name: str) -> None:
    for key in payload:
        if not isinstance(key, str) or not key.strip():
            raise ToolExecutionError(f"'{payload_name}' keys must be non-empty strings.")
        if key.strip() not in allowed:
            allowed_text = ", ".join(sorted(allowed))
            raise ToolExecutionError(f"Unsupported {payload_name} field: {key}. Allowed fields: {allowed_text}")


def _optional_bool(raw: Any) -> bool:
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise ToolExecutionError("'include_archived' must be a boolean.")
    return raw


def _append_unique_strings(existing: list[str], additions: list[str]) -> list[str]:
    output = list(existing)
    seen = set(output)
    for item in additions:
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _now() -> datetime:
    return app_now()


def _record_result(
    tool_name: str,
    record_type: str,
    record_id: str,
    record: Note | NoteCollection,
    *,
    extra: dict[str, Any] | None = None,
) -> ToolExecutionResult:
    payload = {
        "record_type": record_type,
        "record_id": record_id,
        "found": True,
        "status": record.status.value,
        "source_session_id": record.source_session_id,
        "created_at": _to_iso(record.created_at),
        "updated_at": _to_iso(record.updated_at),
        "record": _record_to_payload(record),
    }
    if isinstance(record, Note):
        payload["source_artifact_id"] = record.source_artifact_id
        payload["evidence_refs"] = record.evidence_refs
        payload["origin"] = cast(NoteOrigin, record.origin).value
    if extra:
        payload.update(extra)
    return ToolExecutionResult(tool_name=tool_name, success=True, content=json.dumps(payload, ensure_ascii=False))


def _not_found_result(tool_name: str, record_type: str, record_id: str) -> ToolExecutionResult:
    payload = {
        "record_type": record_type,
        "record_id": record_id,
        "found": False,
        "message": f"{record_type} not found: {record_id}",
    }
    return ToolExecutionResult(tool_name=tool_name, success=True, content=json.dumps(payload, ensure_ascii=False))


def _list_result(tool_name: str, record_type: str, records: list[Note] | list[NoteCollection]) -> ToolExecutionResult:
    payload = {
        "record_type": record_type,
        "records": [_record_to_payload(record) for record in records],
    }
    return ToolExecutionResult(tool_name=tool_name, success=True, content=json.dumps(payload, ensure_ascii=False))


def _record_to_payload(record: Note | NoteCollection) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": record.status.value,
        "source_session_id": record.source_session_id,
        "created_at": _to_iso(record.created_at),
        "updated_at": _to_iso(record.updated_at),
    }
    if isinstance(record, Note):
        base.update(
            {
                "note_id": record.note_id,
                "source_artifact_id": record.source_artifact_id,
                "evidence_refs": record.evidence_refs,
                "title": record.title,
                "body_markdown": record.body_markdown,
                "body_format": record.body_format,
                "note_type": cast(NoteType, record.note_type).value,
                "origin": cast(NoteOrigin, record.origin).value,
                "collection_id": record.collection_id,
                "tags": record.tags,
                "source_refs": [_source_ref_to_payload(source_ref) for source_ref in record.source_refs],
                "related_application_id": record.related_application_id,
                "summary": record.summary,
            }
        )
        return base
    base.update(
        {
            "collection_id": record.collection_id,
            "name": record.name,
            "description": record.description,
            "kind": record.kind.value,
            "tags": record.tags,
        }
    )
    return base


def _source_ref_to_payload(record: NoteSourceRef) -> dict[str, Any]:
    source_type = record.source_type.value if not isinstance(record.source_type, str) else record.source_type
    return {
        "source_type": source_type,
        "source_id": record.source_id,
        "source_session_id": record.source_session_id,
        "title": record.title,
        "quote": record.quote,
    }


def _to_iso(value: datetime) -> str:
    return to_app_iso(value)
