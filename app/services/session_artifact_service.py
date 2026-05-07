"""Session artifact upload, activation, and workspace preview use cases."""

from __future__ import annotations

import logging
from base64 import b64decode
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.models import SessionArtifact
from app.domain.protocols import SessionRepository
from app.infra.locks.session_lock_manager import SessionLockManager
from app.runtime.session_manager import SessionManager
from app.schemas.chat import (
    ActiveArtifactsRequest,
    ArtifactUploadRequest,
    SessionArtifactView,
    SessionArtifactsResponse,
    WorkspaceFilePreviewResponse,
)
from app.services.answer_normalizer import AnswerNormalizer

__all__ = ["SessionArtifactService"]

_logger = logging.getLogger(__name__)
_SUPPORTED_ARTIFACT_EXTENSIONS = {".pdf", ".md", ".markdown", ".json", ".txt", ".png", ".jpg", ".jpeg", ".webp"}
_MAX_UPLOAD_SIZE_BYTES = 12 * 1024 * 1024
_MAX_UPLOAD_TOKEN_ESTIMATE = 60000


class SessionArtifactService:
    """Handle session artifact operations."""

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

    async def upload_session_artifact(
        self,
        session_id: str,
        filename: str,
        content_bytes: bytes,
        *,
        auto_activate: bool = True,
    ) -> SessionArtifactView:
        if not isinstance(filename, str):
            raise ValidationError("filename must be string.")
        if not isinstance(content_bytes, bytes):
            raise ValidationError("content_bytes must be bytes.")
        session = self._session_manager.get_or_create_session(session_id)
        lock = self._session_lock_manager.get_lock(session.session_id)
        async with lock:
            title = _sanitize_title(filename)
            extension = _normalized_extension(title)
            if extension not in _SUPPORTED_ARTIFACT_EXTENSIONS:
                supported = ", ".join(sorted(_SUPPORTED_ARTIFACT_EXTENSIONS))
                raise ValidationError(f"Unsupported artifact type '{extension}'. supported={supported}")

            size_bytes = len(content_bytes)
            if size_bytes <= 0:
                raise ValidationError("Uploaded artifact is empty.")
            if size_bytes > _MAX_UPLOAD_SIZE_BYTES:
                raise ValidationError(f"Uploaded artifact too large, max={_MAX_UPLOAD_SIZE_BYTES} bytes.")
            token_estimate = max(1, (size_bytes + 3) // 4)
            if token_estimate > _MAX_UPLOAD_TOKEN_ESTIMATE:
                raise ValidationError(
                    f"Uploaded artifact too large for context handling, max_tokens={_MAX_UPLOAD_TOKEN_ESTIMATE}."
                )

            artifact_id = f"artifact_{uuid4().hex[:12]}"
            session_root = self._session_repository.get_session_root_path(session.session_id)
            artifact_dir = session_root / "artifacts" / artifact_id
            artifact_dir.mkdir(parents=True, exist_ok=False)

            storage_path = artifact_dir / "original.bin"
            storage_path.write_bytes(content_bytes)

            now = _utc_now()
            record = SessionArtifact(
                artifact_id=artifact_id,
                session_id=session.session_id,
                kind="uploaded_file",
                title=title,
                description=f"Uploaded artifact: {title}",
                media_type=_infer_media_type(extension),
                size_bytes=size_bytes,
                status="uploaded",
                visibility="session_shared",
                owner_agent_id=None,
                source_type="upload",
                source_event_id=None,
                created_at=now,
                updated_at=now,
                storage_relpath=str(storage_path.resolve().relative_to(session_root.resolve())),
                text_relpath=None,
                error=None,
                text_char_count=None,
                token_estimate=token_estimate,
                parsed_at=None,
            )
            self._session_repository.add_or_update_session_artifact(record)
            if auto_activate:
                current = self._session_repository.get_active_artifact_ids(session.session_id)
                self._session_repository.set_active_artifact_ids(session.session_id, [*current, artifact_id])

            _logger.info(
                "上传会话 artifact 完成: session_id=%s artifact_id=%s title=%s status=%s size=%s",
                session.session_id,
                artifact_id,
                title,
                record.status,
                size_bytes,
            )
            return _to_artifact_view(record)

    async def upload_session_artifact_from_request(
        self,
        session_id: str,
        request: ArtifactUploadRequest,
    ) -> SessionArtifactView:
        if not isinstance(request, ArtifactUploadRequest):
            raise ValidationError("request must be ArtifactUploadRequest.")
        try:
            artifact_bytes = b64decode(request.content_base64, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"Invalid base64 content: {exc}") from exc
        return await self.upload_session_artifact(
            session_id=session_id,
            filename=request.filename,
            content_bytes=artifact_bytes,
            auto_activate=request.auto_activate,
        )

    def list_session_artifacts(self, session_id: str) -> SessionArtifactsResponse:
        normalized = _normalize_session_id(session_id)
        artifacts = self._session_repository.list_session_artifacts(normalized)
        active_artifact_ids = self._session_repository.get_active_artifact_ids(normalized)
        return SessionArtifactsResponse(
            session_id=normalized,
            active_artifact_ids=active_artifact_ids,
            artifacts=[_to_artifact_view(item) for item in artifacts],
        )

    def set_active_artifacts(self, session_id: str, request: ActiveArtifactsRequest) -> SessionArtifactsResponse:
        normalized = _normalize_session_id(session_id)
        if not isinstance(request, ActiveArtifactsRequest):
            raise ValidationError("request must be ActiveArtifactsRequest.")
        active = self._session_repository.set_active_artifact_ids(normalized, request.artifact_ids)
        artifacts = self._session_repository.list_session_artifacts(normalized)
        return SessionArtifactsResponse(
            session_id=normalized,
            active_artifact_ids=active,
            artifacts=[_to_artifact_view(item) for item in artifacts],
        )

    def preview_workspace_file(
        self,
        session_id: str,
        *,
        path: str,
        max_chars: int = 12000,
    ) -> WorkspaceFilePreviewResponse:
        normalized_session_id = _normalize_session_id(session_id)
        if not isinstance(path, str) or not path.strip():
            raise ValidationError("path must be a non-empty string.")
        if not isinstance(max_chars, int) or max_chars <= 0:
            raise ValidationError("max_chars must be a positive integer.")

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


def _to_artifact_view(item: SessionArtifact) -> SessionArtifactView:
    return SessionArtifactView(
        artifact_id=item.artifact_id,
        title=item.title,
        kind=item.kind,
        media_type=item.media_type,
        size_bytes=item.size_bytes,
        status=item.status,
        visibility=item.visibility,
        created_at=item.created_at,
        updated_at=item.updated_at,
        owner_agent_id=item.owner_agent_id,
        description=item.description,
        error=item.error,
        text_char_count=item.text_char_count,
        token_estimate=item.token_estimate,
        parsed_at=item.parsed_at,
    )


def _normalize_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValidationError("session_id must be a non-empty string.")
    return session_id.strip()


def _sanitize_title(raw: str) -> str:
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
