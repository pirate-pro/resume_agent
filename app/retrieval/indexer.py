"""Build retrieval index projections from product fact sources."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.core.errors import SessionNotFoundError, StorageError, ValidationError
from app.core.time import app_now, normalize_app_datetime
from app.domain.models import SessionArtifact
from app.domain.protocols import SessionRepository
from app.knowledge.models import (
    CompanyProfile,
    ExperiencePost,
    ExternalResource,
    InterviewQuestion,
    KnowledgeRecordStatus,
    SkillRequirement,
)
from app.knowledge.store import KnowledgeStore
from app.notes.models import Note, NoteRecordStatus
from app.notes.store import NoteStore
from app.retrieval.chunking import ChunkingOptions, build_retrieval_chunks
from app.retrieval.index_models import RetrievalChunkSensitivity, RetrievalIndexScope
from app.retrieval.index_store import RetrievalIndexStore
from app.retrieval.models import RetrievalSourceRef, RetrievalSourceType

__all__ = [
    "RetrievalIndexDocument",
    "RetrievalIndexer",
    "RetrievalIndexingResult",
]

_DEFAULT_OWNER_USER_ID = "user_local"
_DEFAULT_WORKSPACE_ID = "workspace_default"


@dataclass(slots=True)
class RetrievalIndexDocument:
    """Normalized document ready to be projected into retrieval chunks."""

    source_ref: RetrievalSourceRef
    title: str
    text: str
    updated_at: datetime
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    scope: RetrievalIndexScope | str = RetrievalIndexScope.USER_PRIVATE
    sensitivity: RetrievalChunkSensitivity | str = RetrievalChunkSensitivity.PRIVATE
    active: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.source_ref, RetrievalSourceRef):
            raise ValidationError("source_ref must be RetrievalSourceRef.")
        self.source_ref = self.source_ref.copy()
        self.title = _normalize_text("title", self.title, allow_empty=False)
        self.text = _normalize_text("text", self.text, allow_empty=True)
        self.updated_at = normalize_app_datetime(self.updated_at)
        self.tags = _clean_strings(self.tags)
        self.metadata = _normalize_metadata(self.metadata)
        self.scope = _normalize_scope(self.scope)
        self.sensitivity = _normalize_sensitivity(self.sensitivity)
        if not isinstance(self.active, bool):
            raise ValidationError("active must be bool.")

    def copy(self) -> "RetrievalIndexDocument":
        return type(self)(
            source_ref=self.source_ref.copy(),
            title=self.title,
            text=self.text,
            updated_at=self.updated_at,
            tags=list(self.tags),
            metadata=dict(self.metadata),
            scope=self.scope,
            sensitivity=self.sensitivity,
            active=self.active,
        )


@dataclass(slots=True)
class RetrievalIndexingResult:
    """Summary of one indexing run."""

    source_count: int = 0
    indexed_source_count: int = 0
    archived_source_count: int = 0
    skipped_source_count: int = 0
    chunk_count: int = 0
    indexed_source_ids: list[str] = field(default_factory=list)
    archived_source_ids: list[str] = field(default_factory=list)
    skipped_source_ids: list[str] = field(default_factory=list)

    def merge(self, other: "RetrievalIndexingResult") -> None:
        if not isinstance(other, RetrievalIndexingResult):
            raise ValidationError("other must be RetrievalIndexingResult.")
        self.source_count += other.source_count
        self.indexed_source_count += other.indexed_source_count
        self.archived_source_count += other.archived_source_count
        self.skipped_source_count += other.skipped_source_count
        self.chunk_count += other.chunk_count
        self.indexed_source_ids.extend(other.indexed_source_ids)
        self.archived_source_ids.extend(other.archived_source_ids)
        self.skipped_source_ids.extend(other.skipped_source_ids)


class RetrievalIndexer:
    """Project Note, Knowledge, and SessionArtifact records into chunk index."""

    def __init__(
        self,
        *,
        index_store: RetrievalIndexStore,
        chunking_options: ChunkingOptions | None = None,
        owner_user_id: str = _DEFAULT_OWNER_USER_ID,
        workspace_id: str = _DEFAULT_WORKSPACE_ID,
        index_version: int = 1,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(index_store, RetrievalIndexStore):
            raise ValidationError("index_store must be RetrievalIndexStore.")
        self._index_store = index_store
        self._chunking_options = chunking_options or ChunkingOptions()
        self._owner_user_id = _normalize_text("owner_user_id", owner_user_id, allow_empty=False)
        self._workspace_id = _normalize_text("workspace_id", workspace_id, allow_empty=False)
        self._index_version = _normalize_int("index_version", index_version, min_value=1)
        self._clock = clock or app_now

    def index_documents(self, documents: Iterable[RetrievalIndexDocument]) -> RetrievalIndexingResult:
        """Replace or archive chunks for normalized documents."""

        result = RetrievalIndexingResult()
        for raw in documents:
            if not isinstance(raw, RetrievalIndexDocument):
                raise ValidationError("documents entries must be RetrievalIndexDocument.")
            document = raw.copy()
            result.source_count += 1
            source_id = document.source_ref.source_id
            source_type = document.source_ref.source_type
            if not document.active:
                self._index_store.archive_source_chunks(source_type=source_type, source_id=source_id)
                result.archived_source_count += 1
                result.archived_source_ids.append(source_id)
                continue
            if not document.text.strip():
                self._index_store.replace_source_chunks(source_type=source_type, source_id=source_id, chunks=[])
                result.skipped_source_count += 1
                result.skipped_source_ids.append(source_id)
                continue
            chunks = build_retrieval_chunks(
                text=document.text,
                source_ref=document.source_ref,
                source_title=document.title,
                source_updated_at=document.updated_at,
                owner_user_id=self._owner_user_id,
                workspace_id=self._workspace_id,
                scope=document.scope,
                sensitivity=document.sensitivity,
                index_version=self._index_version,
                tags=document.tags,
                metadata=document.metadata,
                options=self._chunking_options,
                now=self._now(),
            )
            saved = self._index_store.replace_source_chunks(source_type=source_type, source_id=source_id, chunks=chunks)
            result.indexed_source_count += 1
            result.indexed_source_ids.append(source_id)
            result.chunk_count += len(saved)
        return result

    def sync_notes(self, note_store: NoteStore, *, include_archived: bool = True) -> RetrievalIndexingResult:
        """Index Note records into user-private retrieval chunks."""

        if not isinstance(note_store, NoteStore):
            raise ValidationError("note_store must be NoteStore.")
        documents = [_note_document(note) for note in note_store.list_notes(include_archived=include_archived)]
        return self.index_documents(documents)

    def sync_knowledge(
        self,
        knowledge_store: KnowledgeStore,
        *,
        include_archived: bool = True,
    ) -> RetrievalIndexingResult:
        """Index Knowledge records into user-library retrieval chunks."""

        if not isinstance(knowledge_store, KnowledgeStore):
            raise ValidationError("knowledge_store must be KnowledgeStore.")
        documents: list[RetrievalIndexDocument] = []
        documents.extend(
            _external_resource_document(item)
            for item in knowledge_store.list_external_resources(include_archived=include_archived)
        )
        documents.extend(
            _experience_post_document(item)
            for item in knowledge_store.list_experience_posts(include_archived=include_archived)
        )
        documents.extend(
            _interview_question_document(item)
            for item in knowledge_store.list_interview_questions(include_archived=include_archived)
        )
        documents.extend(
            _company_profile_document(item)
            for item in knowledge_store.list_company_profiles(include_archived=include_archived)
        )
        documents.extend(
            _skill_requirement_document(item)
            for item in knowledge_store.list_skill_requirements(include_archived=include_archived)
        )
        return self.index_documents(documents)

    def sync_session_artifacts(
        self,
        repository: SessionRepository,
        *,
        session_id: str,
    ) -> RetrievalIndexingResult:
        """Index ready artifacts from one session into session-only chunks."""

        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        try:
            artifacts = repository.list_session_artifacts(session_id.strip())
        except SessionNotFoundError:
            return RetrievalIndexingResult()
        documents = [_session_artifact_document(repository, artifact) for artifact in artifacts]
        return self.index_documents(documents)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise ValidationError("clock must return datetime.")
        return normalize_app_datetime(value)


def _note_document(note: Note) -> RetrievalIndexDocument:
    note_type = _enum_value(note.note_type)
    text = _document_text(
        ("标题", note.title),
        ("摘要", note.summary),
        ("类型", note_type),
        ("标签", note.tags),
        ("正文", note.body_markdown),
    )
    return RetrievalIndexDocument(
        source_ref=RetrievalSourceRef(
            source_type=RetrievalSourceType.NOTE,
            source_id=note.note_id,
            source_session_id=note.source_session_id,
            artifact_id=note.source_artifact_id,
        ),
        title=note.title,
        text=text,
        updated_at=note.updated_at,
        tags=[note_type, *note.tags],
        metadata={
            "note_type": note_type,
            "collection_id": note.collection_id,
            "related_application_id": note.related_application_id,
        },
        scope=RetrievalIndexScope.USER_PRIVATE,
        sensitivity=RetrievalChunkSensitivity.PRIVATE,
        active=note.status == NoteRecordStatus.ACTIVE,
    )


def _external_resource_document(resource: ExternalResource) -> RetrievalIndexDocument:
    resource_type = _enum_value(resource.resource_type)
    text = _document_text(
        ("标题", resource.title),
        ("摘要", resource.summary),
        ("资料类型", resource_type),
        ("来源", resource.provider),
        ("链接", resource.url),
        ("公司", resource.company),
        ("岗位", resource.position),
        ("目标方向", resource.target_roles),
        ("技能标签", resource.skill_tags),
        ("要点", resource.key_points),
    )
    return RetrievalIndexDocument(
        source_ref=RetrievalSourceRef(
            source_type=RetrievalSourceType.EXTERNAL_RESOURCE,
            source_id=resource.resource_id,
            source_session_id=resource.source_session_id,
            artifact_id=resource.raw_artifact_id or resource.source_artifact_id,
        ),
        title=resource.title,
        text=text,
        updated_at=resource.updated_at,
        tags=[resource_type, resource.company, resource.position, *resource.skill_tags, *resource.target_roles],
        metadata={
            "resource_type": resource_type,
            "company": resource.company,
            "position": resource.position,
            "related_application_ids": list(resource.related_application_ids),
            "related_note_ids": list(resource.related_note_ids),
        },
        scope=RetrievalIndexScope.USER_LIBRARY,
        sensitivity=RetrievalChunkSensitivity.INTERNAL,
        active=resource.status == KnowledgeRecordStatus.ACTIVE,
    )


def _experience_post_document(experience: ExperiencePost) -> RetrievalIndexDocument:
    title = _join_non_empty(experience.company, experience.position, "面经") or experience.experience_id
    text = _document_text(
        ("标题", title),
        ("摘要", experience.summary),
        ("公司", experience.company),
        ("岗位", experience.position),
        ("级别", experience.seniority),
        ("难度", _enum_value(experience.difficulty)),
        ("流程", experience.interview_process),
        ("轮次", experience.interview_rounds),
        ("问题", experience.questions),
        ("结果", experience.outcome),
        ("标签", experience.tags),
    )
    return RetrievalIndexDocument(
        source_ref=RetrievalSourceRef(
            source_type=RetrievalSourceType.EXPERIENCE_POST,
            source_id=experience.experience_id,
            source_session_id=experience.source_session_id,
            artifact_id=experience.source_artifact_id,
        ),
        title=title,
        text=text,
        updated_at=experience.updated_at,
        tags=[
            experience.company,
            experience.position,
            experience.seniority,
            _enum_value(experience.difficulty),
            *experience.tags,
        ],
        metadata={
            "source_resource_id": experience.source_resource_id,
            "related_application_ids": list(experience.related_application_ids),
            "related_note_ids": list(experience.related_note_ids),
        },
        scope=RetrievalIndexScope.USER_LIBRARY,
        sensitivity=RetrievalChunkSensitivity.INTERNAL,
        active=experience.status == KnowledgeRecordStatus.ACTIVE,
    )


def _interview_question_document(question: InterviewQuestion) -> RetrievalIndexDocument:
    text = _document_text(
        ("题目", question.question_text),
        ("答案思路", question.answer_outline),
        ("考察点", question.evaluation_points),
        ("常见问题", question.common_pitfalls),
        ("公司", question.company),
        ("岗位", question.position),
        ("题型", _enum_value(question.question_type)),
        ("难度", _enum_value(question.difficulty)),
        ("技能标签", question.skill_tags),
    )
    return RetrievalIndexDocument(
        source_ref=RetrievalSourceRef(
            source_type=RetrievalSourceType.INTERVIEW_QUESTION,
            source_id=question.question_id,
            source_session_id=question.source_session_id,
            artifact_id=question.source_artifact_id,
        ),
        title=question.question_text,
        text=text,
        updated_at=question.updated_at,
        tags=[question.company, question.position, _enum_value(question.question_type), *question.skill_tags],
        metadata={
            "source_resource_id": question.source_resource_id,
            "source_experience_id": question.source_experience_id,
            "related_application_ids": list(question.related_application_ids),
            "related_note_ids": list(question.related_note_ids),
        },
        scope=RetrievalIndexScope.USER_LIBRARY,
        sensitivity=RetrievalChunkSensitivity.INTERNAL,
        active=question.status == KnowledgeRecordStatus.ACTIVE,
    )


def _company_profile_document(company: CompanyProfile) -> RetrievalIndexDocument:
    text = _document_text(
        ("公司", company.company_name),
        ("摘要", company.summary),
        ("别名", company.aliases),
        ("行业", company.industries),
        ("目标岗位", company.target_roles),
        ("招聘信号", company.hiring_signals),
        ("面试风格", company.interview_style),
        ("常见问题", company.common_questions),
    )
    return RetrievalIndexDocument(
        source_ref=RetrievalSourceRef(
            source_type=RetrievalSourceType.COMPANY_PROFILE,
            source_id=company.company_id,
            source_session_id=company.source_session_id,
            artifact_id=company.source_artifact_id,
        ),
        title=company.company_name,
        text=text,
        updated_at=company.updated_at,
        tags=[company.company_name, *company.aliases, *company.target_roles, *company.industries],
        metadata={
            "resource_ids": list(company.resource_ids),
            "question_ids": list(company.question_ids),
        },
        scope=RetrievalIndexScope.USER_LIBRARY,
        sensitivity=RetrievalChunkSensitivity.INTERNAL,
        active=company.status == KnowledgeRecordStatus.ACTIVE,
    )


def _skill_requirement_document(skill: SkillRequirement) -> RetrievalIndexDocument:
    text = _document_text(
        ("技能", skill.skill_name),
        ("描述", skill.description),
        ("分类", _enum_value(skill.category)),
        ("等级", _enum_value(skill.level)),
        ("评估点", skill.assessment_points),
        ("岗位标签", skill.role_tags),
    )
    return RetrievalIndexDocument(
        source_ref=RetrievalSourceRef(
            source_type=RetrievalSourceType.SKILL_REQUIREMENT,
            source_id=skill.skill_requirement_id,
            source_session_id=skill.source_session_id,
            artifact_id=skill.source_artifact_id,
        ),
        title=skill.skill_name,
        text=text,
        updated_at=skill.updated_at,
        tags=[skill.skill_name, _enum_value(skill.category), _enum_value(skill.level), *skill.role_tags],
        metadata={
            "company_ids": list(skill.company_ids),
            "resource_ids": list(skill.resource_ids),
            "question_ids": list(skill.question_ids),
        },
        scope=RetrievalIndexScope.USER_LIBRARY,
        sensitivity=RetrievalChunkSensitivity.INTERNAL,
        active=skill.status == KnowledgeRecordStatus.ACTIVE,
    )


def _session_artifact_document(repository: SessionRepository, artifact: SessionArtifact) -> RetrievalIndexDocument:
    text = ""
    active = artifact.status == "ready" and artifact.text_relpath is not None and artifact.visibility != "agent_private"
    if active:
        try:
            text = repository.read_session_artifact_text(artifact.session_id, artifact.artifact_id)
        except (SessionNotFoundError, StorageError):
            active = False
    document_text = _document_text(
        ("文件名", artifact.title),
        ("说明", artifact.description),
        ("类型", artifact.kind),
        ("媒体类型", artifact.media_type),
        ("来源", artifact.source_type),
        ("正文", text),
    )
    return RetrievalIndexDocument(
        source_ref=RetrievalSourceRef(
            source_type=RetrievalSourceType.SESSION_ARTIFACT,
            source_id=artifact.artifact_id,
            source_session_id=artifact.session_id,
            artifact_id=artifact.artifact_id,
        ),
        title=artifact.title,
        text=document_text,
        updated_at=artifact.updated_at,
        tags=[artifact.kind, artifact.media_type, artifact.source_type or ""],
        metadata={
            "kind": artifact.kind,
            "media_type": artifact.media_type,
            "visibility": artifact.visibility,
            "text_char_count": artifact.text_char_count,
        },
        scope=RetrievalIndexScope.SESSION_ONLY,
        sensitivity=RetrievalChunkSensitivity.PRIVATE,
        active=active,
    )


def _document_text(*sections: tuple[str, Any]) -> str:
    parts: list[str] = []
    for title, raw in sections:
        value = _format_section_value(raw)
        if not value:
            continue
        parts.append(f"## {title}\n{value}")
    return "\n\n".join(parts).strip()


def _format_section_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            formatted = _format_section_value(item)
            if formatted:
                lines.append(f"- {key}: {formatted}")
        return "\n".join(lines)
    if isinstance(value, list | tuple | set):
        lines = []
        for item in value:
            formatted = _format_section_value(item)
            if formatted:
                lines.append(f"- {formatted}")
        return "\n".join(lines)
    return str(value).strip()


def _normalize_metadata(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("metadata must be dict.")
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError("metadata must be JSON serializable.") from exc
    return dict(value)


def _normalize_scope(value: RetrievalIndexScope | str) -> RetrievalIndexScope:
    if isinstance(value, RetrievalIndexScope):
        return value
    if isinstance(value, str):
        return RetrievalIndexScope(value.strip().lower())
    raise ValidationError("scope must be a string.")


def _normalize_sensitivity(value: RetrievalChunkSensitivity | str) -> RetrievalChunkSensitivity:
    if isinstance(value, RetrievalChunkSensitivity):
        return value
    if isinstance(value, str):
        return RetrievalChunkSensitivity(value.strip().lower())
    raise ValidationError("sensitivity must be a string.")


def _normalize_int(field_name: str, value: int, *, min_value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{field_name} must be int.")
    if value < min_value:
        raise ValidationError(f"{field_name} must be >= {min_value}.")
    return value


def _normalize_text(field_name: str, value: str, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string.")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return normalized


def _clean_strings(values: Sequence[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = _format_section_value(raw).strip()
        if not text or text in seen:
            continue
        output.append(text)
        seen.add(text)
    return output


def _join_non_empty(*values: str) -> str:
    return " · ".join(_clean_strings(values))


def _enum_value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, str):
        return value
    raise ValidationError("enum value must be a string or Enum.")
