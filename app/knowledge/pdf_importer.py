"""Import local PDF files into knowledge resources and retrieval index."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.core.errors import ValidationError
from app.core.time import app_now, normalize_app_datetime
from app.domain.models import SessionArtifact
from app.domain.protocols import SessionRepository
from app.knowledge.models import ExternalResource, KnowledgeRecordStatus, ResourceType
from app.knowledge.store import KnowledgeStore
from app.retrieval.index_store import RetrievalIndexStore
from app.retrieval.indexer import RetrievalIndexer, RetrievalIndexingResult
from app.tools.builtin_tools.session_artifact_helpers import ensure_session_artifact_text_ready

__all__ = [
    "KnowledgePdfImportResult",
    "KnowledgePdfImporter",
]

_DEFAULT_SESSION_ID = "sess_knowledge_import"
_PDF_MEDIA_TYPE = "application/pdf"
_MAX_SUMMARY_CHARS = 160
_MAX_KEY_POINTS = 12


@dataclass(slots=True)
class KnowledgePdfImportResult:
    """Result returned after importing one PDF into knowledge."""

    resource_id: str
    artifact_id: str
    session_id: str
    title: str
    text_char_count: int
    token_estimate: int
    index_result: RetrievalIndexingResult
    key_points: list[str] = field(default_factory=list)


class KnowledgePdfImporter:
    """Import local PDF files as artifact-first external knowledge resources."""

    def __init__(
        self,
        *,
        session_repository: SessionRepository,
        knowledge_store: KnowledgeStore,
        retrieval_index_store: RetrievalIndexStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_repository = session_repository
        self._knowledge_store = knowledge_store
        self._retrieval_index_store = retrieval_index_store
        self._clock = clock or app_now

    def import_pdf(
        self,
        path: Path,
        *,
        session_id: str = _DEFAULT_SESSION_ID,
        title: str | None = None,
        provider: str = "本地 PDF 导入",
        skill_tags: list[str] | None = None,
        target_roles: list[str] | None = None,
        auto_index: bool = True,
    ) -> KnowledgePdfImportResult:
        pdf_path = _validate_pdf_path(path)
        normalized_session_id = _normalize_session_id(session_id)
        resolved_title = _normalize_title(title or pdf_path.stem)
        digest = _file_digest(pdf_path)
        artifact_id = f"artifact_pdf_{digest[:16]}"
        resource_id = f"resource_pdf_{digest[:16]}"
        tags = _merge_strings(_infer_skill_tags(resolved_title), skill_tags or [])
        roles = _merge_strings(target_roles or [])

        self._ensure_session(normalized_session_id)
        artifact = self._upsert_pdf_artifact(
            pdf_path,
            session_id=normalized_session_id,
            artifact_id=artifact_id,
            title=resolved_title,
        )
        ready_artifact, text = ensure_session_artifact_text_ready(
            self._session_repository,
            normalized_session_id,
            artifact,
        )
        key_points = _extract_key_points(text)
        resource = ExternalResource(
            resource_id=resource_id,
            status=KnowledgeRecordStatus.ACTIVE,
            source_session_id=normalized_session_id,
            source_artifact_id=ready_artifact.artifact_id,
            evidence_refs=[ready_artifact.artifact_id, normalized_session_id],
            created_at=self._now(),
            updated_at=self._now(),
            title=resolved_title,
            resource_type=ResourceType.UPLOADED_FILE,
            provider=provider,
            target_roles=roles,
            skill_tags=tags,
            summary=_summary_for_pdf(text),
            key_points=key_points,
            raw_artifact_id=ready_artifact.artifact_id,
        )
        saved = self._knowledge_store.save_external_resource(resource)
        index_result = RetrievalIndexingResult()
        if auto_index:
            indexer = RetrievalIndexer(
                index_store=self._retrieval_index_store,
                session_repository=self._session_repository,
                clock=self._clock,
            )
            index_result = indexer.sync_knowledge(self._knowledge_store)
        return KnowledgePdfImportResult(
            resource_id=saved.resource_id,
            artifact_id=ready_artifact.artifact_id,
            session_id=normalized_session_id,
            title=saved.title,
            text_char_count=ready_artifact.text_char_count or len(text),
            token_estimate=ready_artifact.token_estimate or _estimate_tokens(text),
            index_result=index_result,
            key_points=key_points,
        )

    def _upsert_pdf_artifact(
        self,
        source_path: Path,
        *,
        session_id: str,
        artifact_id: str,
        title: str,
    ) -> SessionArtifact:
        root = self._session_repository.get_session_root_path(session_id).resolve()
        artifact_dir = root / "artifacts" / artifact_id
        original_path = artifact_dir / "original.pdf"
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, original_path)
        except OSError as exc:
            raise ValidationError(f"Failed to copy PDF into artifact storage: {exc}") from exc
        now = self._now()
        artifact = SessionArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            kind="uploaded_file",
            title=f"{title}.pdf" if not title.lower().endswith(".pdf") else title,
            description=f"Knowledge PDF import: {title}",
            media_type=_PDF_MEDIA_TYPE,
            size_bytes=original_path.stat().st_size,
            status="uploaded",
            visibility="session_shared",
            owner_agent_id="knowledge_importer",
            source_type="knowledge_pdf_import",
            source_event_id=None,
            created_at=now,
            updated_at=now,
            storage_relpath=str(original_path.relative_to(root)),
            text_relpath=None,
            error=None,
            text_char_count=None,
            token_estimate=None,
            parsed_at=None,
        )
        self._session_repository.add_or_update_session_artifact(artifact)
        return artifact

    def _ensure_session(self, session_id: str) -> None:
        if self._session_repository.get_session(session_id) is None:
            self._session_repository.create_session(session_id)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise ValidationError("clock must return datetime.")
        return normalize_app_datetime(value)


def _validate_pdf_path(path: Path) -> Path:
    if not isinstance(path, Path):
        raise ValidationError("path must be pathlib.Path.")
    resolved = path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise ValidationError(f"PDF file not found: {path}")
    if resolved.suffix.lower() != ".pdf":
        raise ValidationError(f"Knowledge import only supports PDF files: {path}")
    return resolved


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValidationError(f"Failed to read PDF file: {exc}") from exc
    return digest.hexdigest()


def _extract_key_points(text: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line or len(line) > 80:
            continue
        if line.startswith(("http://", "https://")):
            continue
        if line in seen:
            continue
        output.append(line)
        seen.add(line)
        if len(output) >= _MAX_KEY_POINTS:
            break
    return output


def _summary_for_pdf(text: str) -> str:
    compact = " ".join(text.split())
    if not compact:
        return "本地导入 PDF，已建立外部资料记录。"
    snippet = compact[:_MAX_SUMMARY_CHARS].rstrip()
    suffix = "..." if len(compact) > _MAX_SUMMARY_CHARS else ""
    return f"本地导入 PDF，已提取 {len(text)} 字符用于检索。开头内容：{snippet}{suffix}"


def _infer_skill_tags(title: str) -> list[str]:
    tags: list[str] = []
    lowered = title.lower()
    if "c++" in lowered or "cpp" in lowered:
        tags.append("C++")
    if "java" in lowered:
        tags.append("Java")
    if "八股" in title:
        tags.append("八股文")
    if "面试" in title or "八股" in title:
        tags.append("面试题")
    if "代码随想录" in title:
        tags.append("代码随想录")
    return tags


def _merge_strings(*groups: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, list):
            raise ValidationError("string groups must be list[str].")
        for raw in group:
            item = _normalize_optional_text(raw)
            if item is None or item in seen:
                continue
            output.append(item)
            seen.add(item)
    return output


def _normalize_session_id(value: str) -> str:
    normalized = _normalize_title(value)
    if not normalized.startswith("sess_"):
        raise ValidationError("session_id must start with sess_.")
    return normalized


def _normalize_title(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("title must be a non-empty string.")
    normalized = value.strip()
    if "/" in normalized or "\\" in normalized:
        raise ValidationError("title must not contain path segments.")
    return normalized


def _normalize_optional_text(value: str) -> str | None:
    if not isinstance(value, str):
        raise ValidationError("value must be a string.")
    normalized = value.strip()
    return normalized or None


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)
