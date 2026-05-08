"""File-backed store for career product records."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypeVar
from uuid import uuid4

from app.core.time import app_now, from_app_iso, normalize_app_datetime, to_app_iso
from app.career.models import (
    CareerProfile,
    CareerRecordStatus,
    JDAnalysis,
    JobFitReport,
    ResumeProfile,
    ResumeVersion,
    validate_artifact_id,
    validate_career_profile_id,
    validate_evidence_refs,
    validate_fit_id,
    validate_jd_id,
    validate_resume_profile_id,
    validate_resume_version_id,
)
from app.core.errors import StorageError, ValidationError

__all__ = ["CareerProductStore"]

_RecordT = TypeVar("_RecordT", ResumeProfile, CareerProfile, JDAnalysis, JobFitReport, ResumeVersion)

_CAREER_PROFILE_STRING_FIELDS = {
    "career_goal",
    "education_summary",
    "experience_summary",
}
_CAREER_PROFILE_LIST_FIELDS = {
    "target_roles",
    "preferred_industries",
    "preferred_cities",
    "strengths",
    "weaknesses",
    "skills",
    "interests",
    "resume_issues",
    "interview_weaknesses",
}


class CareerProductStore:
    """Persist career product records as atomic JSON files."""

    def __init__(self, root_dir: Path, clock: Callable[[], datetime] | None = None) -> None:
        if not isinstance(root_dir, Path):
            raise ValidationError("root_dir must be pathlib.Path.")
        self._root_dir = root_dir
        self._clock = clock or _app_now
        self._profiles_dir = self._root_dir / "profiles"
        self._resumes_dir = self._root_dir / "resumes"
        self._jobs_dir = self._root_dir / "jobs"
        self._versions_dir = self._root_dir / "versions"
        for path in (self._profiles_dir, self._resumes_dir, self._jobs_dir, self._versions_dir):
            path.mkdir(parents=True, exist_ok=True)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise ValidationError("clock must return datetime.")
        return normalize_app_datetime(value)

    def save_resume_profile(self, record: ResumeProfile) -> ResumeProfile:
        if not isinstance(record, ResumeProfile):
            raise ValidationError("record must be ResumeProfile.")
        validated = record.copy()
        path = self._resume_profile_path(validated.resume_profile_id)
        stamped = _stamp_record(validated, _read_record(path, _resume_profile_from_payload), self._now())
        _write_json_payload(path, _resume_profile_to_payload(stamped))
        return stamped.copy()

    def get_resume_profile(self, resume_profile_id: str) -> ResumeProfile | None:
        return _read_record(
            self._resume_profile_path(validate_resume_profile_id(resume_profile_id)),
            _resume_profile_from_payload,
        )

    def list_resume_profiles(self, *, include_archived: bool = False) -> list[ResumeProfile]:
        records = [
            _read_record_required(path, _resume_profile_from_payload)
            for path in sorted(self._resumes_dir.glob("*/profile.json"))
        ]
        return _filter_and_sort(records, include_archived=include_archived)

    def archive_resume_profile(self, resume_profile_id: str) -> ResumeProfile | None:
        record = self.get_resume_profile(resume_profile_id)
        if record is None:
            return None
        return self.save_resume_profile(replace(record, status=CareerRecordStatus.ARCHIVED))

    def save_career_profile(self, record: CareerProfile) -> CareerProfile:
        if not isinstance(record, CareerProfile):
            raise ValidationError("record must be CareerProfile.")
        validated = record.copy()
        path = self._career_profile_path(validated.career_profile_id)
        stamped = _stamp_record(validated, _read_record(path, _career_profile_from_payload), self._now())
        _write_json_payload(path, _career_profile_to_payload(stamped))
        return stamped.copy()

    def get_career_profile(self, career_profile_id: str = "career_profile_default") -> CareerProfile | None:
        return _read_record(
            self._career_profile_path(validate_career_profile_id(career_profile_id)),
            _career_profile_from_payload,
        )

    def list_career_profiles(self, *, include_archived: bool = False) -> list[CareerProfile]:
        records = [
            _read_record_required(path, _career_profile_from_payload)
            for path in sorted(self._profiles_dir.glob("*.json"))
        ]
        return _filter_and_sort(records, include_archived=include_archived)

    def archive_career_profile(self, career_profile_id: str) -> CareerProfile | None:
        record = self.get_career_profile(career_profile_id)
        if record is None:
            return None
        return self.save_career_profile(replace(record, status=CareerRecordStatus.ARCHIVED))

    def merge_career_profile(
        self,
        career_profile_id: str,
        *,
        updates: dict[str, Any],
        evidence_refs: list[str],
        source_artifact_id: str | None = None,
    ) -> CareerProfile:
        record = self.get_career_profile(career_profile_id)
        if record is None:
            raise ValidationError(f"CareerProfile not found: {career_profile_id}")
        normalized_updates = _normalize_update_payload(updates)
        normalized_evidence_refs = _validate_evidence_refs(evidence_refs)
        if not normalized_evidence_refs:
            raise ValidationError("evidence_refs are required for CareerProfile merge.")
        normalized_source_artifact_id = _normalize_optional_artifact_id(source_artifact_id)

        values: dict[str, Any] = {}
        for field_name, raw_value in normalized_updates.items():
            if field_name in _CAREER_PROFILE_STRING_FIELDS:
                if raw_value is None:
                    continue
                if not isinstance(raw_value, str):
                    raise ValidationError(f"{field_name} must be a string.")
                normalized = raw_value.strip()
                if normalized:
                    values[field_name] = normalized
                continue
            if field_name in _CAREER_PROFILE_LIST_FIELDS:
                if raw_value is None:
                    continue
                if not isinstance(raw_value, list):
                    raise ValidationError(f"{field_name} must be a list.")
                additions = _normalize_string_list(field_name, raw_value)
                if additions:
                    values[field_name] = _merge_string_lists(getattr(record, field_name), additions)
                continue
            raise ValidationError(f"Unsupported CareerProfile merge field: {field_name}")

        merged_evidence_refs = _merge_string_lists(record.evidence_refs, normalized_evidence_refs)
        values["evidence_refs"] = merged_evidence_refs
        if normalized_source_artifact_id is not None and record.source_artifact_id is None:
            values["source_artifact_id"] = normalized_source_artifact_id
        updated = replace(record, **values)
        return self.save_career_profile(updated)

    def save_jd_analysis(self, record: JDAnalysis) -> JDAnalysis:
        if not isinstance(record, JDAnalysis):
            raise ValidationError("record must be JDAnalysis.")
        validated = record.copy()
        path = self._jd_analysis_path(validated.jd_analysis_id)
        stamped = _stamp_record(validated, _read_record(path, _jd_analysis_from_payload), self._now())
        _write_json_payload(path, _jd_analysis_to_payload(stamped))
        return stamped.copy()

    def get_jd_analysis(self, jd_analysis_id: str) -> JDAnalysis | None:
        return _read_record(
            self._jd_analysis_path(validate_jd_id(jd_analysis_id)),
            _jd_analysis_from_payload,
        )

    def list_jd_analyses(self, *, include_archived: bool = False) -> list[JDAnalysis]:
        records = [
            _read_record_required(path, _jd_analysis_from_payload)
            for path in sorted(self._jobs_dir.glob("*/jd_analysis.json"))
        ]
        return _filter_and_sort(records, include_archived=include_archived)

    def archive_jd_analysis(self, jd_analysis_id: str) -> JDAnalysis | None:
        record = self.get_jd_analysis(jd_analysis_id)
        if record is None:
            return None
        return self.save_jd_analysis(replace(record, status=CareerRecordStatus.ARCHIVED))

    def save_job_fit_report(self, record: JobFitReport) -> JobFitReport:
        if not isinstance(record, JobFitReport):
            raise ValidationError("record must be JobFitReport.")
        validated = record.copy()
        target_path = self._job_fit_report_path(validated.jd_analysis_id, validated.job_fit_report_id)
        existing_paths = self._job_fit_report_paths(validated.job_fit_report_id)
        duplicate_paths = [path for path in existing_paths if path != target_path]
        if duplicate_paths:
            raise ValidationError(f"Duplicate job_fit_report_id across JD analyses: {validated.job_fit_report_id}")
        stamped = _stamp_record(validated, _read_record(target_path, _job_fit_report_from_payload), self._now())
        _write_json_payload(target_path, _job_fit_report_to_payload(stamped))
        return stamped.copy()

    def get_job_fit_report(self, job_fit_report_id: str) -> JobFitReport | None:
        normalized = validate_fit_id(job_fit_report_id)
        paths = self._job_fit_report_paths(normalized)
        if not paths:
            return None
        if len(paths) > 1:
            raise StorageError(f"Ambiguous job_fit_report_id across JD analyses: {normalized}")
        return _read_record(paths[0], _job_fit_report_from_payload)

    def list_job_fit_reports(self, *, include_archived: bool = False) -> list[JobFitReport]:
        records = [
            _read_record_required(path, _job_fit_report_from_payload)
            for path in sorted(self._jobs_dir.glob("*/job_fit_reports/*.json"))
        ]
        return _filter_and_sort(records, include_archived=include_archived)

    def archive_job_fit_report(self, job_fit_report_id: str) -> JobFitReport | None:
        record = self.get_job_fit_report(job_fit_report_id)
        if record is None:
            return None
        return self.save_job_fit_report(replace(record, status=CareerRecordStatus.ARCHIVED))

    def save_resume_version(self, record: ResumeVersion) -> ResumeVersion:
        if not isinstance(record, ResumeVersion):
            raise ValidationError("record must be ResumeVersion.")
        validated = record.copy()
        path = self._resume_version_path(validated.resume_version_id)
        stamped = _stamp_record(validated, _read_record(path, _resume_version_from_payload), self._now())
        _write_json_payload(path, _resume_version_to_payload(stamped))
        return stamped.copy()

    def get_resume_version(self, resume_version_id: str) -> ResumeVersion | None:
        return _read_record(
            self._resume_version_path(validate_resume_version_id(resume_version_id)),
            _resume_version_from_payload,
        )

    def list_resume_versions(self, *, include_archived: bool = False) -> list[ResumeVersion]:
        records = [
            _read_record_required(path, _resume_version_from_payload)
            for path in sorted(self._versions_dir.glob("*.json"))
        ]
        return _filter_and_sort(records, include_archived=include_archived)

    def archive_resume_version(self, resume_version_id: str) -> ResumeVersion | None:
        record = self.get_resume_version(resume_version_id)
        if record is None:
            return None
        return self.save_resume_version(replace(record, status=CareerRecordStatus.ARCHIVED))

    def _career_profile_path(self, career_profile_id: str) -> Path:
        return self._profiles_dir / f"{career_profile_id}.json"

    def _resume_profile_path(self, resume_profile_id: str) -> Path:
        return self._resumes_dir / resume_profile_id / "profile.json"

    def _jd_analysis_path(self, jd_analysis_id: str) -> Path:
        return self._jobs_dir / jd_analysis_id / "jd_analysis.json"

    def _job_fit_report_path(self, jd_analysis_id: str, job_fit_report_id: str) -> Path:
        return self._jobs_dir / jd_analysis_id / "job_fit_reports" / f"{job_fit_report_id}.json"

    def _job_fit_report_paths(self, job_fit_report_id: str) -> list[Path]:
        normalized = validate_fit_id(job_fit_report_id)
        return sorted(self._jobs_dir.glob(f"*/job_fit_reports/{normalized}.json"))

    def _resume_version_path(self, resume_version_id: str) -> Path:
        return self._versions_dir / f"{resume_version_id}.json"


def _resume_profile_to_payload(record: ResumeProfile) -> dict[str, Any]:
    payload = _base_payload(record)
    payload.update(
        {
            "resume_profile_id": record.resume_profile_id,
            "basic_info": record.basic_info,
            "education": record.education,
            "work_experience": record.work_experience,
            "project_experience": record.project_experience,
            "skills": record.skills,
            "certificates": record.certificates,
            "awards": record.awards,
            "self_evaluation": record.self_evaluation,
            "raw_text_artifact_id": record.raw_text_artifact_id,
            "diagnosis_artifact_id": record.diagnosis_artifact_id,
            "diagnosis": record.diagnosis,
        }
    )
    return payload


def _resume_profile_from_payload(payload: dict[str, Any]) -> ResumeProfile:
    return ResumeProfile(
        resume_profile_id=payload["resume_profile_id"],
        **_base_kwargs(payload),
        basic_info=payload.get("basic_info", {}),
        education=payload.get("education", []),
        work_experience=payload.get("work_experience", []),
        project_experience=payload.get("project_experience", []),
        skills=payload.get("skills", []),
        certificates=payload.get("certificates", []),
        awards=payload.get("awards", []),
        self_evaluation=payload.get("self_evaluation", ""),
        raw_text_artifact_id=payload.get("raw_text_artifact_id"),
        diagnosis_artifact_id=payload.get("diagnosis_artifact_id"),
        diagnosis=payload.get("diagnosis", {}),
    )


def _career_profile_to_payload(record: CareerProfile) -> dict[str, Any]:
    payload = _base_payload(record)
    payload.update(
        {
            "career_profile_id": record.career_profile_id,
            "career_goal": record.career_goal,
            "target_roles": record.target_roles,
            "preferred_industries": record.preferred_industries,
            "preferred_cities": record.preferred_cities,
            "strengths": record.strengths,
            "weaknesses": record.weaknesses,
            "skills": record.skills,
            "interests": record.interests,
            "education_summary": record.education_summary,
            "experience_summary": record.experience_summary,
            "resume_issues": record.resume_issues,
            "interview_weaknesses": record.interview_weaknesses,
        }
    )
    return payload


def _career_profile_from_payload(payload: dict[str, Any]) -> CareerProfile:
    return CareerProfile(
        career_profile_id=payload["career_profile_id"],
        **_base_kwargs(payload),
        career_goal=payload.get("career_goal", ""),
        target_roles=payload.get("target_roles", []),
        preferred_industries=payload.get("preferred_industries", []),
        preferred_cities=payload.get("preferred_cities", []),
        strengths=payload.get("strengths", []),
        weaknesses=payload.get("weaknesses", []),
        skills=payload.get("skills", []),
        interests=payload.get("interests", []),
        education_summary=payload.get("education_summary", ""),
        experience_summary=payload.get("experience_summary", ""),
        resume_issues=payload.get("resume_issues", []),
        interview_weaknesses=payload.get("interview_weaknesses", []),
    )


def _jd_analysis_to_payload(record: JDAnalysis) -> dict[str, Any]:
    payload = _base_payload(record)
    payload.update(
        {
            "jd_analysis_id": record.jd_analysis_id,
            "company": record.company,
            "position": record.position,
            "seniority": record.seniority,
            "required_skills": record.required_skills,
            "preferred_skills": record.preferred_skills,
            "responsibilities": record.responsibilities,
            "keywords": record.keywords,
            "risk_signals": record.risk_signals,
            "interview_focus": record.interview_focus,
        }
    )
    return payload


def _jd_analysis_from_payload(payload: dict[str, Any]) -> JDAnalysis:
    return JDAnalysis(
        jd_analysis_id=payload["jd_analysis_id"],
        **_base_kwargs(payload),
        company=payload.get("company", ""),
        position=payload.get("position", ""),
        seniority=payload.get("seniority", ""),
        required_skills=payload.get("required_skills", []),
        preferred_skills=payload.get("preferred_skills", []),
        responsibilities=payload.get("responsibilities", []),
        keywords=payload.get("keywords", []),
        risk_signals=payload.get("risk_signals", []),
        interview_focus=payload.get("interview_focus", []),
    )


def _job_fit_report_to_payload(record: JobFitReport) -> dict[str, Any]:
    payload = _base_payload(record)
    payload.update(
        {
            "job_fit_report_id": record.job_fit_report_id,
            "jd_analysis_id": record.jd_analysis_id,
            "resume_profile_id": record.resume_profile_id,
            "career_profile_id": record.career_profile_id,
            "overall_score": record.overall_score,
            "score_breakdown": record.score_breakdown,
            "matched_evidence": record.matched_evidence,
            "gaps": record.gaps,
            "resume_optimization_direction": record.resume_optimization_direction,
            "interview_preparation_focus": record.interview_preparation_focus,
            "recommendation": record.recommendation,
            "report_artifact_id": record.report_artifact_id,
        }
    )
    return payload


def _job_fit_report_from_payload(payload: dict[str, Any]) -> JobFitReport:
    return JobFitReport(
        job_fit_report_id=payload["job_fit_report_id"],
        **_base_kwargs(payload),
        jd_analysis_id=payload["jd_analysis_id"],
        resume_profile_id=payload["resume_profile_id"],
        career_profile_id=payload["career_profile_id"],
        overall_score=payload.get("overall_score", 0),
        score_breakdown=payload.get("score_breakdown", {}),
        matched_evidence=payload.get("matched_evidence", []),
        gaps=payload.get("gaps", []),
        resume_optimization_direction=payload.get("resume_optimization_direction", []),
        interview_preparation_focus=payload.get("interview_preparation_focus", []),
        recommendation=payload.get("recommendation", "cautious"),
        report_artifact_id=payload.get("report_artifact_id"),
    )


def _resume_version_to_payload(record: ResumeVersion) -> dict[str, Any]:
    payload = _base_payload(record)
    payload.update(
        {
            "resume_version_id": record.resume_version_id,
            "base_resume_profile_id": record.base_resume_profile_id,
            "target_jd_analysis_id": record.target_jd_analysis_id,
            "title": record.title,
            "format": record.format,
            "artifact_id": record.artifact_id,
            "change_summary": record.change_summary,
            "keyword_strategy": record.keyword_strategy,
            "risk_notes": record.risk_notes,
        }
    )
    return payload


def _resume_version_from_payload(payload: dict[str, Any]) -> ResumeVersion:
    return ResumeVersion(
        resume_version_id=payload["resume_version_id"],
        **_base_kwargs(payload),
        base_resume_profile_id=payload["base_resume_profile_id"],
        target_jd_analysis_id=payload.get("target_jd_analysis_id"),
        title=payload["title"],
        format=payload["format"],
        artifact_id=payload["artifact_id"],
        change_summary=payload.get("change_summary", []),
        keyword_strategy=payload.get("keyword_strategy", []),
        risk_notes=payload.get("risk_notes", []),
    )


def _base_payload(record: ResumeProfile | CareerProfile | JDAnalysis | JobFitReport | ResumeVersion) -> dict[str, Any]:
    return {
        "status": record.status.value,
        "source_session_id": record.source_session_id,
        "source_artifact_id": record.source_artifact_id,
        "evidence_refs": record.evidence_refs,
        "created_at": _to_iso(record.created_at),
        "updated_at": _to_iso(record.updated_at),
    }


def _base_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload["status"],
        "source_session_id": payload["source_session_id"],
        "source_artifact_id": payload["source_artifact_id"],
        "evidence_refs": payload["evidence_refs"],
        "created_at": _from_iso(payload["created_at"]),
        "updated_at": _from_iso(payload["updated_at"]),
    }


def _read_record(path: Path, parser: Callable[[dict[str, Any]], _RecordT]) -> _RecordT | None:
    if not path.exists():
        return None
    return _read_record_required(path, parser)


def _read_record_required(path: Path, parser: Callable[[dict[str, Any]], _RecordT]) -> _RecordT:
    payload = _read_json_payload(path)
    try:
        return parser(payload)
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise StorageError(f"Invalid career product record '{path}': {exc}") from exc


def _read_json_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StorageError(f"Invalid career product JSON '{path}': {exc}") from exc
    except OSError as exc:
        raise StorageError(f"Failed to read career product record '{path}': {exc}") from exc
    if not isinstance(payload, dict):
        raise StorageError(f"Invalid career product JSON '{path}': root must be object.")
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
        raise StorageError(f"Failed to write career product record '{path}': {exc}") from exc


def _filter_and_sort(records: list[_RecordT], *, include_archived: bool) -> list[_RecordT]:
    output = [
        record
        for record in records
        if include_archived or record.status == CareerRecordStatus.ACTIVE
    ]
    output.sort(key=lambda item: (item.updated_at, item.created_at), reverse=True)
    return [record.copy() for record in output]


def _stamp_record(record: _RecordT, existing: _RecordT | None, now: datetime) -> _RecordT:
    created_at = existing.created_at if existing is not None else now
    return replace(record, created_at=created_at, updated_at=now)


def _normalize_update_payload(updates: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(updates, dict):
        raise ValidationError("updates must be a dictionary.")
    normalized: dict[str, Any] = {}
    for key, value in updates.items():
        if not isinstance(key, str) or not key.strip():
            raise ValidationError("updates keys must be non-empty strings.")
        normalized_key = key.strip()
        if normalized_key in normalized:
            raise ValidationError(f"Duplicate update field: {normalized_key}")
        normalized[normalized_key] = value
    try:
        json.dumps(normalized, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError("updates must be JSON-serializable.") from exc
    return normalized


def _validate_evidence_refs(values: list[str]) -> list[str]:
    return validate_evidence_refs(values)


def _normalize_optional_artifact_id(value: str | None) -> str | None:
    if value is None:
        return None
    return validate_artifact_id(value)


def _normalize_string_list(field_name: str, values: list[Any]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(f"{field_name} must be a list.")
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str) or not raw.strip():
            raise ValidationError(f"{field_name} values must be non-empty strings.")
        item = raw.strip()
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _merge_string_lists(existing: list[str], additions: list[str]) -> list[str]:
    output = list(existing)
    seen = set(output)
    for item in additions:
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _app_now() -> datetime:
    return app_now()


def _to_iso(value: datetime) -> str:
    return to_app_iso(value)


def _from_iso(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValidationError("timestamp must be an ISO datetime string.")
    return from_app_iso(value)
