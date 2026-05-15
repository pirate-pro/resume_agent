"""File-backed store for retrieval index chunks."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.core.errors import StorageError, ValidationError
from app.core.time import app_now, normalize_app_datetime, to_app_iso
from app.infra.storage.session_io import write_json_atomically
from app.retrieval.index_models import (
    RetrievalChunk,
    RetrievalChunkStatus,
    retrieval_chunk_from_payload,
    retrieval_chunk_to_payload,
    validate_chunk_id,
)
from app.retrieval.models import RetrievalSourceType, validate_source_type

__all__ = ["RetrievalIndexStore"]
_SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,160}$")


class RetrievalIndexStore:
    """Persist rebuildable retrieval chunks in JSONL."""

    def __init__(self, root_dir: Path, clock: Callable[[], datetime] | None = None) -> None:
        if not isinstance(root_dir, Path):
            raise ValidationError("root_dir must be pathlib.Path.")
        self._root_dir = root_dir
        self._clock = clock or app_now
        self._chunks_path = self._root_dir / "chunks.jsonl"
        self._manifest_path = self._root_dir / "manifest.json"
        self._root_dir.mkdir(parents=True, exist_ok=True)
        if not self._manifest_path.exists():
            self._write_manifest([])
        if not self._chunks_path.exists():
            self._chunks_path.touch()

    def replace_source_chunks(
        self,
        *,
        source_type: RetrievalSourceType | str,
        source_id: str,
        chunks: list[RetrievalChunk],
    ) -> list[RetrievalChunk]:
        """Replace all chunks for one source atomically."""

        normalized_type = validate_source_type(source_type)
        normalized_source_id = _normalize_source_id(source_id)
        if not isinstance(chunks, list):
            raise ValidationError("chunks must be a list.")
        now = self._now()
        existing = self._read_all_chunks()
        existing_by_id = {chunk.chunk_id: chunk for chunk in existing}
        remaining = [
            chunk
            for chunk in existing
            if chunk.source_type != normalized_type or chunk.source_id != normalized_source_id
        ]
        stamped: list[RetrievalChunk] = []
        seen_ids: set[str] = set()
        for raw in chunks:
            if not isinstance(raw, RetrievalChunk):
                raise ValidationError("chunks entries must be RetrievalChunk.")
            chunk = raw.copy()
            if chunk.source_type != normalized_type or chunk.source_id != normalized_source_id:
                raise ValidationError("chunk source must match replace target.")
            if chunk.chunk_id in seen_ids:
                raise ValidationError(f"duplicate chunk_id in replacement: {chunk.chunk_id}")
            seen_ids.add(chunk.chunk_id)
            previous = existing_by_id.get(chunk.chunk_id)
            stamped.append(
                chunk.with_timestamps(
                    created_at=previous.created_at if previous is not None else now,
                    updated_at=now,
                )
            )
        output = [*remaining, *stamped]
        self._write_all_chunks(output)
        return [chunk.copy() for chunk in stamped]

    def archive_source_chunks(
        self,
        *,
        source_type: RetrievalSourceType | str,
        source_id: str,
    ) -> list[RetrievalChunk]:
        """Mark chunks for one source as archived."""

        normalized_type = validate_source_type(source_type)
        normalized_source_id = _normalize_source_id(source_id)
        now = self._now()
        updated: list[RetrievalChunk] = []
        output: list[RetrievalChunk] = []
        for chunk in self._read_all_chunks():
            if chunk.source_type == normalized_type and chunk.source_id == normalized_source_id:
                archived = chunk.with_status(RetrievalChunkStatus.ARCHIVED, updated_at=now)
                output.append(archived)
                updated.append(archived)
            else:
                output.append(chunk)
        self._write_all_chunks(output)
        return [chunk.copy() for chunk in updated]

    def get_chunk(self, chunk_id: str) -> RetrievalChunk | None:
        normalized = validate_chunk_id(chunk_id)
        for chunk in self._read_all_chunks():
            if chunk.chunk_id == normalized:
                return chunk.copy()
        return None

    def list_chunks(
        self,
        *,
        include_archived: bool = False,
        source_type: RetrievalSourceType | str | None = None,
        source_id: str | None = None,
    ) -> list[RetrievalChunk]:
        if not isinstance(include_archived, bool):
            raise ValidationError("include_archived must be bool.")
        normalized_type = None if source_type is None else validate_source_type(source_type)
        normalized_source_id = None if source_id is None else _normalize_source_id(source_id)
        chunks = self._read_all_chunks()
        filtered: list[RetrievalChunk] = []
        for chunk in chunks:
            if not include_archived and chunk.status != RetrievalChunkStatus.ACTIVE:
                continue
            if normalized_type is not None and chunk.source_type != normalized_type:
                continue
            if normalized_source_id is not None and chunk.source_id != normalized_source_id:
                continue
            filtered.append(chunk)
        filtered.sort(
            key=lambda item: (
                validate_source_type(item.source_type).value,
                item.source_id,
                item.chunk_index,
                item.chunk_id,
            )
        )
        return [chunk.copy() for chunk in filtered]

    def read_manifest(self) -> dict[str, object]:
        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(f"Failed to read retrieval index manifest: {exc}") from exc
        if not isinstance(data, dict):
            raise StorageError("Failed to read retrieval index manifest: root must be object.")
        return data

    def clear(self) -> None:
        self._write_all_chunks([])

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise ValidationError("clock must return datetime.")
        return normalize_app_datetime(value)

    def _read_all_chunks(self) -> list[RetrievalChunk]:
        if not self._chunks_path.exists():
            return []
        chunks: list[RetrievalChunk] = []
        try:
            for line_no, raw_line in enumerate(self._chunks_path.read_text(encoding="utf-8").splitlines(), start=1):
                if not raw_line.strip():
                    continue
                payload = json.loads(raw_line)
                if not isinstance(payload, dict):
                    raise StorageError(f"chunks.jsonl line {line_no} root must be object.")
                chunks.append(retrieval_chunk_from_payload(payload))
        except StorageError:
            raise
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, ValidationError) as exc:
            raise StorageError(f"Failed to read retrieval index chunks: {exc}") from exc
        return chunks

    def _write_all_chunks(self, chunks: list[RetrievalChunk]) -> None:
        deduped = _dedupe_chunks(chunks)
        deduped.sort(
            key=lambda item: (
                validate_source_type(item.source_type).value,
                item.source_id,
                item.chunk_index,
                item.chunk_id,
            )
        )
        temp_path = self._chunks_path.with_name(f".{self._chunks_path.name}.{uuid4().hex}.tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                for chunk in deduped:
                    handle.write(json.dumps(retrieval_chunk_to_payload(chunk), ensure_ascii=False, sort_keys=True))
                    handle.write("\n")
            temp_path.replace(self._chunks_path)
        except OSError as exc:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            raise StorageError(f"Failed to write retrieval index chunks: {exc}") from exc
        self._write_manifest(deduped)

    def _write_manifest(self, chunks: list[RetrievalChunk]) -> None:
        active_count = sum(1 for chunk in chunks if chunk.status == RetrievalChunkStatus.ACTIVE)
        sources: dict[str, dict[str, object]] = {}
        for chunk in chunks:
            source_type_value = validate_source_type(chunk.source_type).value
            key = f"{source_type_value}:{chunk.source_id}"
            entry = sources.setdefault(
                key,
                {
                    "active_chunks": 0,
                    "archived_chunks": 0,
                    "source_id": chunk.source_id,
                    "source_title": chunk.source_title,
                    "source_type": source_type_value,
                    "source_updated_at": to_app_iso(chunk.source_updated_at),
                    "updated_at": to_app_iso(chunk.updated_at),
                },
            )
            if chunk.status == RetrievalChunkStatus.ACTIVE:
                entry["active_chunks"] = _read_count(entry["active_chunks"]) + 1
            else:
                entry["archived_chunks"] = _read_count(entry["archived_chunks"]) + 1
        write_json_atomically(
            self._manifest_path,
            {
                "active_chunk_count": active_count,
                "chunk_count": len(chunks),
                "source_count": len(sources),
                "sources": sources,
                "updated_at": to_app_iso(self._now()),
            },
            error_prefix="Failed to write retrieval index manifest",
        )


def _dedupe_chunks(chunks: list[RetrievalChunk]) -> list[RetrievalChunk]:
    output: list[RetrievalChunk] = []
    seen: set[str] = set()
    for raw in chunks:
        chunk = raw.copy()
        if chunk.chunk_id in seen:
            raise ValidationError(f"duplicate chunk_id: {chunk.chunk_id}")
        output.append(chunk)
        seen.add(chunk.chunk_id)
    return output


def _normalize_source_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("source_id must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValidationError("source_id must be a non-empty string.")
    if "/" in normalized or "\\" in normalized or ".." in normalized:
        raise ValidationError("source_id must not contain path segments.")
    if not _SOURCE_ID_PATTERN.fullmatch(normalized):
        raise ValidationError(f"source_id has invalid format: {normalized}")
    return normalized


def _read_count(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise StorageError("Invalid retrieval index manifest counter state.")
