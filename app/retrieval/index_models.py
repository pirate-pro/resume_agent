"""RAG index projection models for retrieval."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any, Self

from app.core.errors import ValidationError
from app.core.time import from_app_iso, normalize_app_datetime, to_app_iso
from app.retrieval.models import RetrievalSourceRef, RetrievalSourceType, validate_source_type

__all__ = [
    "RetrievalChunk",
    "RetrievalChunkStatus",
    "build_chunk_id",
    "content_hash_for_text",
    "retrieval_chunk_from_payload",
    "retrieval_chunk_to_payload",
    "validate_chunk_id",
]

_CHUNK_ID_PATTERN = re.compile(r"^chunk_[a-z0-9_]+_[A-Za-z0-9][A-Za-z0-9_-]{0,160}_[a-f0-9]{8,16}$")
_HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class RetrievalChunkStatus(str, Enum):
    """Lifecycle status for retrieval index chunks."""

    ACTIVE = "active"
    ARCHIVED = "archived"


@dataclass(slots=True)
class RetrievalChunk:
    """One searchable text projection derived from a source record."""

    chunk_id: str
    source_type: RetrievalSourceType | str
    source_id: str
    source_ref: RetrievalSourceRef
    source_title: str
    source_updated_at: datetime
    content_hash: str
    chunk_index: int
    char_start: int
    char_end: int
    text: str
    token_estimate: int
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    status: RetrievalChunkStatus | str = RetrievalChunkStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        self.source_type = validate_source_type(self.source_type)
        self.source_id = _normalize_source_id(self.source_id)
        if not isinstance(self.source_ref, RetrievalSourceRef):
            raise ValidationError("source_ref must be RetrievalSourceRef.")
        self.source_ref = self.source_ref.copy()
        if self.source_ref.source_type != self.source_type:
            raise ValidationError("source_ref.source_type must match source_type.")
        if self.source_ref.source_id != self.source_id:
            raise ValidationError("source_ref.source_id must match source_id.")
        self.chunk_id = validate_chunk_id(self.chunk_id)
        self.source_title = _normalize_text("source_title", self.source_title, allow_empty=False)
        self.source_updated_at = _normalize_datetime("source_updated_at", self.source_updated_at)
        self.content_hash = _normalize_content_hash(self.content_hash)
        self.chunk_index = _normalize_int("chunk_index", self.chunk_index, min_value=0)
        self.char_start = _normalize_int("char_start", self.char_start, min_value=0)
        self.char_end = _normalize_int("char_end", self.char_end, min_value=1)
        if self.char_end <= self.char_start:
            raise ValidationError("char_end must be greater than char_start.")
        self.text = _normalize_text("text", self.text, allow_empty=False)
        self.token_estimate = _normalize_int("token_estimate", self.token_estimate, min_value=1)
        self.tags = _normalize_string_list("tags", self.tags)
        self.metadata = _normalize_metadata(self.metadata)
        self.status = _normalize_status(self.status)
        self.created_at = _normalize_datetime("created_at", self.created_at)
        self.updated_at = _normalize_datetime("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at cannot be earlier than created_at.")

    def copy(self) -> Self:
        return type(self)(
            chunk_id=self.chunk_id,
            source_type=self.source_type,
            source_id=self.source_id,
            source_ref=self.source_ref.copy(),
            source_title=self.source_title,
            source_updated_at=self.source_updated_at,
            content_hash=self.content_hash,
            chunk_index=self.chunk_index,
            char_start=self.char_start,
            char_end=self.char_end,
            text=self.text,
            token_estimate=self.token_estimate,
            tags=list(self.tags),
            metadata=deepcopy(self.metadata),
            status=self.status,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    def with_timestamps(self, *, created_at: datetime, updated_at: datetime) -> Self:
        return replace(
            self,
            created_at=normalize_app_datetime(created_at),
            updated_at=normalize_app_datetime(updated_at),
        )

    def with_status(self, status: RetrievalChunkStatus | str, *, updated_at: datetime) -> Self:
        return replace(
            self,
            status=_normalize_status(status),
            updated_at=normalize_app_datetime(updated_at),
        )


def build_chunk_id(
    *,
    source_type: RetrievalSourceType | str,
    source_id: str,
    chunk_index: int,
    text: str,
) -> str:
    normalized_source_type = validate_source_type(source_type).value
    normalized_source_id = _normalize_source_id(source_id)
    normalized_index = _normalize_int("chunk_index", chunk_index, min_value=0)
    digest = hashlib.sha256(f"{normalized_source_type}:{normalized_source_id}:{normalized_index}:{text}".encode()).hexdigest()
    return f"chunk_{normalized_source_type}_{normalized_source_id}_{digest[:10]}"


def content_hash_for_text(text: str) -> str:
    normalized = _normalize_text("text", text, allow_empty=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def validate_chunk_id(value: str) -> str:
    normalized = _normalize_text("chunk_id", value, allow_empty=False)
    if "/" in normalized or "\\" in normalized or ".." in normalized:
        raise ValidationError("chunk_id must not contain path segments.")
    if not _CHUNK_ID_PATTERN.fullmatch(normalized):
        raise ValidationError(f"chunk_id has invalid format: {normalized}")
    return normalized


def retrieval_chunk_to_payload(chunk: RetrievalChunk) -> dict[str, Any]:
    if not isinstance(chunk, RetrievalChunk):
        raise ValidationError("chunk must be RetrievalChunk.")
    item = chunk.copy()
    source_type = validate_source_type(item.source_type)
    status = _normalize_status(item.status)
    return {
        "char_end": item.char_end,
        "char_start": item.char_start,
        "chunk_id": item.chunk_id,
        "chunk_index": item.chunk_index,
        "content_hash": item.content_hash,
        "created_at": to_app_iso(item.created_at),
        "metadata": deepcopy(item.metadata),
        "source_id": item.source_id,
        "source_ref": item.source_ref.to_payload(),
        "source_title": item.source_title,
        "source_type": source_type.value,
        "source_updated_at": to_app_iso(item.source_updated_at),
        "status": status.value,
        "tags": list(item.tags),
        "text": item.text,
        "token_estimate": item.token_estimate,
        "updated_at": to_app_iso(item.updated_at),
    }


def retrieval_chunk_from_payload(payload: dict[str, Any]) -> RetrievalChunk:
    if not isinstance(payload, dict):
        raise ValidationError("chunk payload must be dict.")
    source_ref_payload = payload.get("source_ref")
    if not isinstance(source_ref_payload, dict):
        raise ValidationError("source_ref must be dict.")
    return RetrievalChunk(
        chunk_id=_require_key(payload, "chunk_id"),
        source_type=_require_key(payload, "source_type"),
        source_id=_require_key(payload, "source_id"),
        source_ref=RetrievalSourceRef(
            source_type=_require_key(source_ref_payload, "source_type"),
            source_id=_require_key(source_ref_payload, "source_id"),
            source_session_id=_optional_str(source_ref_payload.get("source_session_id")),
            artifact_id=_optional_str(source_ref_payload.get("artifact_id")),
        ),
        source_title=_require_key(payload, "source_title"),
        source_updated_at=from_app_iso(_require_key(payload, "source_updated_at")),
        content_hash=_require_key(payload, "content_hash"),
        chunk_index=_require_int(payload, "chunk_index"),
        char_start=_require_int(payload, "char_start"),
        char_end=_require_int(payload, "char_end"),
        text=_require_key(payload, "text"),
        token_estimate=_require_int(payload, "token_estimate"),
        tags=_require_string_list(payload, "tags"),
        metadata=_require_dict(payload, "metadata"),
        status=_require_key(payload, "status"),
        created_at=from_app_iso(_require_key(payload, "created_at")),
        updated_at=from_app_iso(_require_key(payload, "updated_at")),
    )


def _normalize_status(value: RetrievalChunkStatus | str) -> RetrievalChunkStatus:
    if isinstance(value, RetrievalChunkStatus):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        try:
            return RetrievalChunkStatus(normalized)
        except ValueError as exc:
            raise ValidationError(f"status is invalid: {value}") from exc
    raise ValidationError("status must be a string.")


def _normalize_source_id(value: str) -> str:
    normalized = _normalize_text("source_id", value, allow_empty=False)
    if "/" in normalized or "\\" in normalized or ".." in normalized:
        raise ValidationError("source_id must not contain path segments.")
    if not re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,160}$").fullmatch(normalized):
        raise ValidationError(f"source_id has invalid format: {normalized}")
    return normalized


def _normalize_content_hash(value: str) -> str:
    normalized = _normalize_text("content_hash", value, allow_empty=False).lower()
    if not _HASH_PATTERN.fullmatch(normalized):
        raise ValidationError("content_hash must be sha256 hex.")
    return normalized


def _normalize_text(field_name: str, value: str, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string.")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return normalized


def _normalize_int(field_name: str, value: int, *, min_value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{field_name} must be int.")
    if value < min_value:
        raise ValidationError(f"{field_name} must be >= {min_value}.")
    return value


def _normalize_datetime(field_name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationError(f"{field_name} must be datetime.")
    return normalize_app_datetime(value)


def _normalize_string_list(field_name: str, values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(f"{field_name} must be a list.")
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = _normalize_text(field_name, raw, allow_empty=False)
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _normalize_metadata(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("metadata must be dict.")
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError("metadata must be JSON serializable.") from exc
    return deepcopy(value)


def _require_key(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ValidationError(f"{key} must be string.")
    return value


def _require_int(payload: dict[str, Any], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{key} must be int.")
    return value


def _require_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload[key]
    if not isinstance(value, dict):
        raise ValidationError(f"{key} must be dict.")
    return deepcopy(value)


def _require_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationError(f"{key} must be list[str].")
    return list(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("optional string field must be string or null.")
    return value
