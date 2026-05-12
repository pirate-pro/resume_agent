"""File-backed store for external career knowledge assets."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, TypeVar
from uuid import uuid4

from app.core.errors import StorageError, ValidationError
from app.core.time import app_now, from_app_iso, normalize_app_datetime, to_app_iso
from app.knowledge.models import (
    CompanyProfile,
    ExperiencePost,
    ExternalResource,
    InterviewQuestion,
    KnowledgeRecordStatus,
    SkillRequirement,
    validate_company_id,
    validate_experience_id,
    validate_question_id,
    validate_resource_id,
    validate_skill_requirement_id,
)

__all__ = ["KnowledgeStore"]

_RecordT = TypeVar(
    "_RecordT",
    ExternalResource,
    ExperiencePost,
    InterviewQuestion,
    CompanyProfile,
    SkillRequirement,
)
_RESOURCE_UPDATE_FIELDS = {
    "company",
    "evidence_refs",
    "key_points",
    "position",
    "provider",
    "raw_artifact_id",
    "related_application_ids",
    "related_note_ids",
    "resource_type",
    "skill_tags",
    "source_artifact_id",
    "summary",
    "target_roles",
    "title",
    "url",
}
_EXPERIENCE_UPDATE_FIELDS = {
    "company",
    "difficulty",
    "evidence_refs",
    "interview_process",
    "interview_rounds",
    "outcome",
    "position",
    "questions",
    "related_application_ids",
    "related_note_ids",
    "seniority",
    "source_artifact_id",
    "source_resource_id",
    "summary",
    "tags",
}
_QUESTION_UPDATE_FIELDS = {
    "answer_outline",
    "common_pitfalls",
    "company",
    "difficulty",
    "evaluation_points",
    "evidence_refs",
    "position",
    "question_text",
    "question_type",
    "related_application_ids",
    "related_note_ids",
    "skill_tags",
    "source_artifact_id",
    "source_experience_id",
    "source_resource_id",
}
_COMPANY_UPDATE_FIELDS = {
    "aliases",
    "common_questions",
    "company_name",
    "evidence_refs",
    "hiring_signals",
    "industries",
    "interview_style",
    "question_ids",
    "resource_ids",
    "source_artifact_id",
    "summary",
    "target_roles",
}
_SKILL_REQUIREMENT_UPDATE_FIELDS = {
    "assessment_points",
    "category",
    "company_ids",
    "description",
    "evidence_refs",
    "level",
    "question_ids",
    "resource_ids",
    "role_tags",
    "skill_name",
    "source_artifact_id",
}


class KnowledgeStore:
    """Persist external career knowledge records as atomic JSON files."""

    def __init__(self, root_dir: Path, clock: Callable[[], datetime] | None = None) -> None:
        if not isinstance(root_dir, Path):
            raise ValidationError("root_dir must be pathlib.Path.")
        self._root_dir = root_dir
        self._clock = clock or _app_now
        self._resources_dir = self._root_dir / "external_resources"
        self._experiences_dir = self._root_dir / "experience_posts"
        self._questions_dir = self._root_dir / "interview_questions"
        self._companies_dir = self._root_dir / "company_profiles"
        self._skill_requirements_dir = self._root_dir / "skill_requirements"
        for path in (
            self._resources_dir,
            self._experiences_dir,
            self._questions_dir,
            self._companies_dir,
            self._skill_requirements_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise ValidationError("clock must return datetime.")
        return normalize_app_datetime(value)

    def save_external_resource(self, record: ExternalResource) -> ExternalResource:
        if not isinstance(record, ExternalResource):
            raise ValidationError("record must be ExternalResource.")
        validated = record.copy()
        path = self._resource_path(validated.resource_id)
        stamped = _stamp_record(validated, _read_record(path, _external_resource_from_payload), self._now())
        _write_json_payload(path, _external_resource_to_payload(stamped))
        return stamped.copy()

    def get_external_resource(self, resource_id: str) -> ExternalResource | None:
        return _read_record(
            self._resource_path(validate_resource_id(resource_id)),
            _external_resource_from_payload,
        )

    def list_external_resources(
        self,
        *,
        include_archived: bool = False,
        related_application_id: str | None = None,
    ) -> list[ExternalResource]:
        records = [
            _read_record_required(path, _external_resource_from_payload)
            for path in sorted(self._resources_dir.glob("*.json"))
        ]
        filtered = _filter_and_sort(records, include_archived=include_archived)
        if related_application_id is not None:
            normalized = _normalize_application_filter(related_application_id)
            filtered = [record for record in filtered if normalized in record.related_application_ids]
        return [record.copy() for record in filtered]

    def update_external_resource(self, resource_id: str, *, updates: dict[str, Any]) -> ExternalResource:
        record = self.get_external_resource(resource_id)
        if record is None:
            raise ValidationError(f"ExternalResource not found: {resource_id}")
        normalized_updates = _normalize_update_payload(updates, allowed_fields=_RESOURCE_UPDATE_FIELDS)
        return self.save_external_resource(replace(record, **normalized_updates))

    def archive_external_resource(self, resource_id: str) -> ExternalResource | None:
        record = self.get_external_resource(resource_id)
        if record is None:
            return None
        return self.save_external_resource(replace(record, status=KnowledgeRecordStatus.ARCHIVED))

    def save_experience_post(self, record: ExperiencePost) -> ExperiencePost:
        if not isinstance(record, ExperiencePost):
            raise ValidationError("record must be ExperiencePost.")
        validated = record.copy()
        path = self._experience_path(validated.experience_id)
        stamped = _stamp_record(validated, _read_record(path, _experience_post_from_payload), self._now())
        _write_json_payload(path, _experience_post_to_payload(stamped))
        return stamped.copy()

    def get_experience_post(self, experience_id: str) -> ExperiencePost | None:
        return _read_record(
            self._experience_path(validate_experience_id(experience_id)),
            _experience_post_from_payload,
        )

    def list_experience_posts(
        self,
        *,
        include_archived: bool = False,
        source_resource_id: str | None = None,
    ) -> list[ExperiencePost]:
        records = [
            _read_record_required(path, _experience_post_from_payload)
            for path in sorted(self._experiences_dir.glob("*.json"))
        ]
        filtered = _filter_and_sort(records, include_archived=include_archived)
        if source_resource_id is not None:
            normalized = validate_resource_id(source_resource_id)
            filtered = [record for record in filtered if record.source_resource_id == normalized]
        return [record.copy() for record in filtered]

    def update_experience_post(self, experience_id: str, *, updates: dict[str, Any]) -> ExperiencePost:
        record = self.get_experience_post(experience_id)
        if record is None:
            raise ValidationError(f"ExperiencePost not found: {experience_id}")
        normalized_updates = _normalize_update_payload(updates, allowed_fields=_EXPERIENCE_UPDATE_FIELDS)
        return self.save_experience_post(replace(record, **normalized_updates))

    def archive_experience_post(self, experience_id: str) -> ExperiencePost | None:
        record = self.get_experience_post(experience_id)
        if record is None:
            return None
        return self.save_experience_post(replace(record, status=KnowledgeRecordStatus.ARCHIVED))

    def save_interview_question(self, record: InterviewQuestion) -> InterviewQuestion:
        if not isinstance(record, InterviewQuestion):
            raise ValidationError("record must be InterviewQuestion.")
        validated = record.copy()
        path = self._question_path(validated.question_id)
        stamped = _stamp_record(validated, _read_record(path, _interview_question_from_payload), self._now())
        _write_json_payload(path, _interview_question_to_payload(stamped))
        return stamped.copy()

    def get_interview_question(self, question_id: str) -> InterviewQuestion | None:
        return _read_record(
            self._question_path(validate_question_id(question_id)),
            _interview_question_from_payload,
        )

    def list_interview_questions(
        self,
        *,
        include_archived: bool = False,
        source_resource_id: str | None = None,
    ) -> list[InterviewQuestion]:
        records = [
            _read_record_required(path, _interview_question_from_payload)
            for path in sorted(self._questions_dir.glob("*.json"))
        ]
        filtered = _filter_and_sort(records, include_archived=include_archived)
        if source_resource_id is not None:
            normalized = validate_resource_id(source_resource_id)
            filtered = [record for record in filtered if record.source_resource_id == normalized]
        return [record.copy() for record in filtered]

    def update_interview_question(self, question_id: str, *, updates: dict[str, Any]) -> InterviewQuestion:
        record = self.get_interview_question(question_id)
        if record is None:
            raise ValidationError(f"InterviewQuestion not found: {question_id}")
        normalized_updates = _normalize_update_payload(updates, allowed_fields=_QUESTION_UPDATE_FIELDS)
        return self.save_interview_question(replace(record, **normalized_updates))

    def archive_interview_question(self, question_id: str) -> InterviewQuestion | None:
        record = self.get_interview_question(question_id)
        if record is None:
            return None
        return self.save_interview_question(replace(record, status=KnowledgeRecordStatus.ARCHIVED))

    def save_company_profile(self, record: CompanyProfile) -> CompanyProfile:
        if not isinstance(record, CompanyProfile):
            raise ValidationError("record must be CompanyProfile.")
        validated = record.copy()
        path = self._company_path(validated.company_id)
        stamped = _stamp_record(validated, _read_record(path, _company_profile_from_payload), self._now())
        _write_json_payload(path, _company_profile_to_payload(stamped))
        return stamped.copy()

    def get_company_profile(self, company_id: str) -> CompanyProfile | None:
        return _read_record(
            self._company_path(validate_company_id(company_id)),
            _company_profile_from_payload,
        )

    def list_company_profiles(self, *, include_archived: bool = False) -> list[CompanyProfile]:
        records = [
            _read_record_required(path, _company_profile_from_payload)
            for path in sorted(self._companies_dir.glob("*.json"))
        ]
        return _filter_and_sort(records, include_archived=include_archived)

    def update_company_profile(self, company_id: str, *, updates: dict[str, Any]) -> CompanyProfile:
        record = self.get_company_profile(company_id)
        if record is None:
            raise ValidationError(f"CompanyProfile not found: {company_id}")
        normalized_updates = _normalize_update_payload(updates, allowed_fields=_COMPANY_UPDATE_FIELDS)
        return self.save_company_profile(replace(record, **normalized_updates))

    def archive_company_profile(self, company_id: str) -> CompanyProfile | None:
        record = self.get_company_profile(company_id)
        if record is None:
            return None
        return self.save_company_profile(replace(record, status=KnowledgeRecordStatus.ARCHIVED))

    def save_skill_requirement(self, record: SkillRequirement) -> SkillRequirement:
        if not isinstance(record, SkillRequirement):
            raise ValidationError("record must be SkillRequirement.")
        validated = record.copy()
        path = self._skill_requirement_path(validated.skill_requirement_id)
        stamped = _stamp_record(validated, _read_record(path, _skill_requirement_from_payload), self._now())
        _write_json_payload(path, _skill_requirement_to_payload(stamped))
        return stamped.copy()

    def get_skill_requirement(self, skill_requirement_id: str) -> SkillRequirement | None:
        return _read_record(
            self._skill_requirement_path(validate_skill_requirement_id(skill_requirement_id)),
            _skill_requirement_from_payload,
        )

    def list_skill_requirements(self, *, include_archived: bool = False) -> list[SkillRequirement]:
        records = [
            _read_record_required(path, _skill_requirement_from_payload)
            for path in sorted(self._skill_requirements_dir.glob("*.json"))
        ]
        return _filter_and_sort(records, include_archived=include_archived)

    def update_skill_requirement(
        self,
        skill_requirement_id: str,
        *,
        updates: dict[str, Any],
    ) -> SkillRequirement:
        record = self.get_skill_requirement(skill_requirement_id)
        if record is None:
            raise ValidationError(f"SkillRequirement not found: {skill_requirement_id}")
        normalized_updates = _normalize_update_payload(updates, allowed_fields=_SKILL_REQUIREMENT_UPDATE_FIELDS)
        return self.save_skill_requirement(replace(record, **normalized_updates))

    def archive_skill_requirement(self, skill_requirement_id: str) -> SkillRequirement | None:
        record = self.get_skill_requirement(skill_requirement_id)
        if record is None:
            return None
        return self.save_skill_requirement(replace(record, status=KnowledgeRecordStatus.ARCHIVED))

    def _resource_path(self, resource_id: str) -> Path:
        return self._resources_dir / f"{resource_id}.json"

    def _experience_path(self, experience_id: str) -> Path:
        return self._experiences_dir / f"{experience_id}.json"

    def _question_path(self, question_id: str) -> Path:
        return self._questions_dir / f"{question_id}.json"

    def _company_path(self, company_id: str) -> Path:
        return self._companies_dir / f"{company_id}.json"

    def _skill_requirement_path(self, skill_requirement_id: str) -> Path:
        return self._skill_requirements_dir / f"{skill_requirement_id}.json"


def _external_resource_to_payload(record: ExternalResource) -> dict[str, Any]:
    return {
        "company": record.company,
        "created_at": _to_iso(record.created_at),
        "evidence_refs": record.evidence_refs,
        "key_points": record.key_points,
        "position": record.position,
        "provider": record.provider,
        "raw_artifact_id": record.raw_artifact_id,
        "related_application_ids": record.related_application_ids,
        "related_note_ids": record.related_note_ids,
        "resource_id": record.resource_id,
        "resource_type": _enum_value(record.resource_type),
        "skill_tags": record.skill_tags,
        "source_artifact_id": record.source_artifact_id,
        "source_session_id": record.source_session_id,
        "status": _enum_value(record.status),
        "summary": record.summary,
        "target_roles": record.target_roles,
        "title": record.title,
        "updated_at": _to_iso(record.updated_at),
        "url": record.url,
    }


def _external_resource_from_payload(payload: dict[str, Any]) -> ExternalResource:
    return ExternalResource(
        resource_id=payload["resource_id"],
        status=payload["status"],
        source_session_id=payload["source_session_id"],
        source_artifact_id=payload["source_artifact_id"],
        evidence_refs=payload["evidence_refs"],
        created_at=_from_iso(payload["created_at"]),
        updated_at=_from_iso(payload["updated_at"]),
        title=payload["title"],
        resource_type=payload["resource_type"],
        url=payload["url"],
        provider=payload["provider"],
        company=payload["company"],
        position=payload["position"],
        target_roles=payload["target_roles"],
        skill_tags=payload["skill_tags"],
        summary=payload["summary"],
        key_points=payload["key_points"],
        raw_artifact_id=payload["raw_artifact_id"],
        related_application_ids=payload["related_application_ids"],
        related_note_ids=payload["related_note_ids"],
    )


def _experience_post_to_payload(record: ExperiencePost) -> dict[str, Any]:
    return {
        "company": record.company,
        "created_at": _to_iso(record.created_at),
        "difficulty": _enum_value(record.difficulty),
        "evidence_refs": record.evidence_refs,
        "experience_id": record.experience_id,
        "interview_process": record.interview_process,
        "interview_rounds": record.interview_rounds,
        "outcome": record.outcome,
        "position": record.position,
        "questions": record.questions,
        "related_application_ids": record.related_application_ids,
        "related_note_ids": record.related_note_ids,
        "seniority": record.seniority,
        "source_artifact_id": record.source_artifact_id,
        "source_resource_id": record.source_resource_id,
        "source_session_id": record.source_session_id,
        "status": _enum_value(record.status),
        "summary": record.summary,
        "tags": record.tags,
        "updated_at": _to_iso(record.updated_at),
    }


def _experience_post_from_payload(payload: dict[str, Any]) -> ExperiencePost:
    return ExperiencePost(
        experience_id=payload["experience_id"],
        status=payload["status"],
        source_session_id=payload["source_session_id"],
        source_artifact_id=payload["source_artifact_id"],
        evidence_refs=payload["evidence_refs"],
        created_at=_from_iso(payload["created_at"]),
        updated_at=_from_iso(payload["updated_at"]),
        source_resource_id=payload["source_resource_id"],
        company=payload["company"],
        position=payload["position"],
        seniority=payload["seniority"],
        interview_rounds=payload["interview_rounds"],
        interview_process=payload["interview_process"],
        questions=payload["questions"],
        outcome=payload["outcome"],
        difficulty=payload["difficulty"],
        summary=payload["summary"],
        tags=payload["tags"],
        related_application_ids=payload["related_application_ids"],
        related_note_ids=payload["related_note_ids"],
    )


def _interview_question_to_payload(record: InterviewQuestion) -> dict[str, Any]:
    return {
        "answer_outline": record.answer_outline,
        "common_pitfalls": record.common_pitfalls,
        "company": record.company,
        "created_at": _to_iso(record.created_at),
        "difficulty": _enum_value(record.difficulty),
        "evaluation_points": record.evaluation_points,
        "evidence_refs": record.evidence_refs,
        "position": record.position,
        "question_id": record.question_id,
        "question_text": record.question_text,
        "question_type": _enum_value(record.question_type),
        "related_application_ids": record.related_application_ids,
        "related_note_ids": record.related_note_ids,
        "skill_tags": record.skill_tags,
        "source_artifact_id": record.source_artifact_id,
        "source_experience_id": record.source_experience_id,
        "source_resource_id": record.source_resource_id,
        "source_session_id": record.source_session_id,
        "status": _enum_value(record.status),
        "updated_at": _to_iso(record.updated_at),
    }


def _interview_question_from_payload(payload: dict[str, Any]) -> InterviewQuestion:
    return InterviewQuestion(
        question_id=payload["question_id"],
        status=payload["status"],
        source_session_id=payload["source_session_id"],
        source_artifact_id=payload["source_artifact_id"],
        evidence_refs=payload["evidence_refs"],
        created_at=_from_iso(payload["created_at"]),
        updated_at=_from_iso(payload["updated_at"]),
        question_text=payload["question_text"],
        question_type=payload["question_type"],
        difficulty=payload["difficulty"],
        skill_tags=payload["skill_tags"],
        company=payload["company"],
        position=payload["position"],
        source_resource_id=payload["source_resource_id"],
        source_experience_id=payload["source_experience_id"],
        answer_outline=payload["answer_outline"],
        evaluation_points=payload["evaluation_points"],
        common_pitfalls=payload["common_pitfalls"],
        related_application_ids=payload["related_application_ids"],
        related_note_ids=payload["related_note_ids"],
    )


def _company_profile_to_payload(record: CompanyProfile) -> dict[str, Any]:
    return {
        "aliases": record.aliases,
        "common_questions": record.common_questions,
        "company_id": record.company_id,
        "company_name": record.company_name,
        "created_at": _to_iso(record.created_at),
        "evidence_refs": record.evidence_refs,
        "hiring_signals": record.hiring_signals,
        "industries": record.industries,
        "interview_style": record.interview_style,
        "question_ids": record.question_ids,
        "resource_ids": record.resource_ids,
        "source_artifact_id": record.source_artifact_id,
        "source_session_id": record.source_session_id,
        "status": _enum_value(record.status),
        "summary": record.summary,
        "target_roles": record.target_roles,
        "updated_at": _to_iso(record.updated_at),
    }


def _company_profile_from_payload(payload: dict[str, Any]) -> CompanyProfile:
    return CompanyProfile(
        company_id=payload["company_id"],
        status=payload["status"],
        source_session_id=payload["source_session_id"],
        source_artifact_id=payload["source_artifact_id"],
        evidence_refs=payload["evidence_refs"],
        created_at=_from_iso(payload["created_at"]),
        updated_at=_from_iso(payload["updated_at"]),
        company_name=payload["company_name"],
        aliases=payload["aliases"],
        industries=payload["industries"],
        target_roles=payload["target_roles"],
        hiring_signals=payload["hiring_signals"],
        interview_style=payload["interview_style"],
        common_questions=payload["common_questions"],
        resource_ids=payload["resource_ids"],
        question_ids=payload["question_ids"],
        summary=payload["summary"],
    )


def _skill_requirement_to_payload(record: SkillRequirement) -> dict[str, Any]:
    return {
        "assessment_points": record.assessment_points,
        "category": _enum_value(record.category),
        "company_ids": record.company_ids,
        "created_at": _to_iso(record.created_at),
        "description": record.description,
        "evidence_refs": record.evidence_refs,
        "level": _enum_value(record.level),
        "question_ids": record.question_ids,
        "resource_ids": record.resource_ids,
        "role_tags": record.role_tags,
        "skill_name": record.skill_name,
        "skill_requirement_id": record.skill_requirement_id,
        "source_artifact_id": record.source_artifact_id,
        "source_session_id": record.source_session_id,
        "status": _enum_value(record.status),
        "updated_at": _to_iso(record.updated_at),
    }


def _skill_requirement_from_payload(payload: dict[str, Any]) -> SkillRequirement:
    return SkillRequirement(
        skill_requirement_id=payload["skill_requirement_id"],
        status=payload["status"],
        source_session_id=payload["source_session_id"],
        source_artifact_id=payload["source_artifact_id"],
        evidence_refs=payload["evidence_refs"],
        created_at=_from_iso(payload["created_at"]),
        updated_at=_from_iso(payload["updated_at"]),
        skill_name=payload["skill_name"],
        category=payload["category"],
        level=payload["level"],
        description=payload["description"],
        assessment_points=payload["assessment_points"],
        role_tags=payload["role_tags"],
        company_ids=payload["company_ids"],
        resource_ids=payload["resource_ids"],
        question_ids=payload["question_ids"],
    )


def _read_record(path: Path, parser: Callable[[dict[str, Any]], _RecordT]) -> _RecordT | None:
    if not path.exists():
        return None
    return _read_record_required(path, parser)


def _read_record_required(path: Path, parser: Callable[[dict[str, Any]], _RecordT]) -> _RecordT:
    payload = _read_json_payload(path)
    try:
        return parser(payload)
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise StorageError(f"Invalid knowledge record '{path}': {exc}") from exc


def _read_json_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StorageError(f"Invalid knowledge JSON '{path}': {exc}") from exc
    except OSError as exc:
        raise StorageError(f"Failed to read knowledge record '{path}': {exc}") from exc
    if not isinstance(payload, dict):
        raise StorageError(f"Invalid knowledge JSON '{path}': root must be object.")
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
        raise StorageError(f"Failed to write knowledge record '{path}': {exc}") from exc


def _filter_and_sort(records: list[_RecordT], *, include_archived: bool) -> list[_RecordT]:
    output = [
        record
        for record in records
        if include_archived or record.status == KnowledgeRecordStatus.ACTIVE
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
            raise ValidationError(f"Unsupported knowledge update field: {normalized_key}")
        if normalized_key in normalized:
            raise ValidationError(f"Duplicate update field: {normalized_key}")
        normalized[normalized_key] = value
    return normalized


def _normalize_application_filter(application_id: str) -> str:
    if not isinstance(application_id, str) or not application_id.strip():
        raise ValidationError("related_application_id must be a non-empty string.")
    normalized = application_id.strip()
    if not normalized.startswith("application_"):
        raise ValidationError(f"related_application_id has invalid format: {normalized}")
    return normalized


def _enum_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Enum):
        return str(value.value)
    raise ValidationError("enum value must be a string or Enum.")


def _app_now() -> datetime:
    return app_now()


def _to_iso(value: datetime) -> str:
    return to_app_iso(value)


def _from_iso(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValidationError("timestamp must be an ISO datetime string.")
    return from_app_iso(value)
