"""Session file upload, active-file, and workspace preview use cases."""

from __future__ import annotations

import logging
from base64 import b64decode
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.models import SessionFile
from app.domain.protocols import SessionRepository
from app.infra.locks.session_lock_manager import SessionLockManager
from app.runtime.session_manager import SessionManager
from app.schemas.chat import (
    ActiveFilesRequest,
    FileUploadRequest,
    SessionFileView,
    SessionFilesResponse,
    WorkspaceFilePreviewResponse,
)
from app.services.answer_normalizer import AnswerNormalizer

__all__ = ["SessionFileService"]

_logger = logging.getLogger(__name__)
_SUPPORTED_FILE_EXTENSIONS = {".pdf", ".md", ".markdown", ".json", ".txt", ".png", ".jpg", ".jpeg", ".webp"}
_MAX_UPLOAD_SIZE_BYTES = 12 * 1024 * 1024


class SessionFileService:
    """Handle all session file operations."""

    def __init__(
        self,
        session_manager: SessionManager,
        session_repository: SessionRepository,
        session_lock_manager: SessionLockManager,
        answer_normalizer: AnswerNormalizer,
    ) -> None:
        self._session_manager = session_manager
        self._session_repository = session_repository
        self._session_lock_manager = session_lock_manager
        self._answer_normalizer = answer_normalizer

    async def upload_session_file(
        self,
        session_id: str,
        filename: str,
        content_bytes: bytes,
        *,
        auto_activate: bool = True,
    ) -> SessionFileView:
        if not isinstance(filename, str):
            raise ValidationError("filename must be string.")
        if not isinstance(content_bytes, bytes):
            raise ValidationError("content_bytes must be bytes.")
        session = self._session_manager.get_or_create_session(session_id)
        lock = self._session_lock_manager.get_lock(session.session_id)
        async with lock:
            filename = _sanitize_filename(filename)
            extension = _normalized_extension(filename)
            if extension not in _SUPPORTED_FILE_EXTENSIONS:
                supported = ", ".join(sorted(_SUPPORTED_FILE_EXTENSIONS))
                raise ValidationError(f"Unsupported file type '{extension}'. supported={supported}")

            size_bytes = len(content_bytes)
            if size_bytes <= 0:
                raise ValidationError("Uploaded file is empty.")
            if size_bytes > _MAX_UPLOAD_SIZE_BYTES:
                raise ValidationError(f"Uploaded file too large, max={_MAX_UPLOAD_SIZE_BYTES} bytes.")

            file_id = f"file_{uuid4().hex[:12]}"
            workspace = self._session_repository.get_workspace_path(session.session_id)
            session_root = self._session_repository.get_session_root_path(session.session_id)
            uploads_dir = workspace / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)

            storage_path = uploads_dir / f"{file_id}_{filename}"
            storage_path.write_bytes(content_bytes)

            media_type = _infer_media_type(extension)
            record = SessionFile(
                file_id=file_id,
                session_id=session.session_id,
                filename=filename,
                media_type=media_type,
                size_bytes=size_bytes,
                status="uploaded",
                uploaded_at=_utc_now(),
                storage_relpath=str(storage_path.resolve().relative_to(session_root.resolve())),
                text_relpath=None,
                error=None,
                parsed_char_count=None,
                parsed_token_estimate=None,
                parsed_at=None,
            )
            self._session_repository.add_or_update_session_file(record)
            if auto_activate:
                current = self._session_repository.get_active_file_ids(session.session_id)
                self._session_repository.set_active_file_ids(session.session_id, [*current, file_id])

            _logger.info(
                "上传会话文件完成: session_id=%s file_id=%s filename=%s status=%s size=%s",
                session.session_id,
                file_id,
                filename,
                record.status,
                size_bytes,
            )
            return _to_file_view(record)

    async def upload_session_file_from_request(
        self,
        session_id: str,
        request: FileUploadRequest,
    ) -> SessionFileView:
        if not isinstance(request, FileUploadRequest):
            raise ValidationError("request must be FileUploadRequest.")
        try:
            file_bytes = b64decode(request.content_base64, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"Invalid base64 content: {exc}") from exc
        return await self.upload_session_file(
            session_id=session_id,
            filename=request.filename,
            content_bytes=file_bytes,
            auto_activate=request.auto_activate,
        )

    def list_session_files(self, session_id: str) -> SessionFilesResponse:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        normalized = session_id.strip()
        files = self._session_repository.list_session_files(normalized)
        active_file_ids = self._session_repository.get_active_file_ids(normalized)
        return SessionFilesResponse(
            session_id=normalized,
            active_file_ids=active_file_ids,
            files=[_to_file_view(item) for item in files],
        )

    def set_active_files(self, session_id: str, request: ActiveFilesRequest) -> SessionFilesResponse:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        if not isinstance(request, ActiveFilesRequest):
            raise ValidationError("request must be ActiveFilesRequest.")
        normalized = session_id.strip()
        active = self._session_repository.set_active_file_ids(normalized, request.file_ids)
        files = self._session_repository.list_session_files(normalized)
        return SessionFilesResponse(
            session_id=normalized,
            active_file_ids=active,
            files=[_to_file_view(item) for item in files],
        )

    def preview_workspace_file(
        self,
        session_id: str,
        *,
        path: str,
        max_chars: int = 12000,
    ) -> WorkspaceFilePreviewResponse:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        if not isinstance(path, str) or not path.strip():
            raise ValidationError("path must be a non-empty string.")
        if not isinstance(max_chars, int) or max_chars <= 0:
            raise ValidationError("max_chars must be a positive integer.")

        normalized_session_id = session_id.strip()
        normalized_path = path.strip()
        max_chars = min(max_chars, 24000)

        workspace = self._session_repository.get_workspace_path(normalized_session_id).resolve()
        target = _resolve_workspace_preview_path(workspace, normalized_path)
        if not target.exists() or not target.is_file():
            raise ValidationError(
                f"Workspace file does not exist: session_id={normalized_session_id} path={normalized_path}"
            )

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ValidationError(f"Failed to read workspace file: {exc}") from exc

        truncated = len(content) > max_chars
        snippet = content[:max_chars]
        normalized = self._answer_normalizer.normalize_assistant_message(snippet, tool_calls=[])
        return WorkspaceFilePreviewResponse(
            session_id=normalized_session_id,
            path=normalized_path,
            content=normalized.content,
            size_bytes=target.stat().st_size,
            total_chars=len(content),
            truncated=truncated,
            answer_format=normalized.answer_format,
            render_hint=normalized.render_hint,
            layout_hint=normalized.layout_hint,
        )


def _to_file_view(item: SessionFile) -> SessionFileView:
    return SessionFileView(
        file_id=item.file_id,
        filename=item.filename,
        media_type=item.media_type,
        size_bytes=item.size_bytes,
        status=item.status,
        uploaded_at=item.uploaded_at,
        error=item.error,
        parsed_char_count=item.parsed_char_count,
        parsed_token_estimate=item.parsed_token_estimate,
        parsed_at=item.parsed_at,
    )


def _sanitize_filename(raw: str) -> str:
    candidate = Path(raw).name.strip()
    if not candidate:
        raise ValidationError("filename cannot be empty.")
    return candidate.replace("/", "_").replace("\\", "_")


def _resolve_workspace_preview_path(workspace: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValidationError("Absolute paths are not allowed.")
    workspace_resolved = workspace.resolve()
    target = (workspace_resolved / candidate).resolve()
    if not target.is_relative_to(workspace_resolved):
        raise ValidationError("Path traversal is not allowed.")
    return target


def _normalized_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower().strip()
    if not suffix:
        raise ValidationError("filename must have extension.")
    return suffix


def _infer_media_type(extension: str) -> str:
    mapping = {
        ".pdf": "application/pdf",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".json": "application/json",
        ".txt": "text/plain",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    return mapping.get(extension, "application/octet-stream")


def _utc_now() -> datetime:
    return datetime.now(UTC)
