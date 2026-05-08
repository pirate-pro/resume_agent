"""Tests for the career product record store."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from app.career.models import (
    CareerProfile,
    CareerRecordStatus,
    JDAnalysis,
    JobFitReport,
    ResumeProfile,
    ResumeVersion,
)
from app.career.store import CareerProductStore
from app.core.errors import StorageError, ValidationError


def _now() -> datetime:
    return datetime(2026, 5, 7, 0, 0, tzinfo=UTC)


def _store(tmp_path: Path) -> CareerProductStore:
    return CareerProductStore(root_dir=tmp_path / "career")


def _resume_profile(record_id: str = "resume_profile_alpha") -> ResumeProfile:
    return ResumeProfile(
        resume_profile_id=record_id,
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resume",
        evidence_refs=["artifact_resume"],
        created_at=_now(),
        updated_at=_now(),
        basic_info={"name": "候选人"},
        education=[{"school": "Example University"}],
        skills=["Python", "FastAPI"],
        raw_text_artifact_id="artifact_resume",
        diagnosis_artifact_id="artifact_resume_diagnosis",
        diagnosis={"strengths": ["后端经验"], "weaknesses": ["面试准备不足"]},
    )


def _career_profile(record_id: str = "career_profile_default") -> CareerProfile:
    return CareerProfile(
        career_profile_id=record_id,
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=None,
        evidence_refs=["resume_profile_alpha"],
        created_at=_now(),
        updated_at=_now(),
        career_goal="AI 应用开发",
        target_roles=["后端开发"],
        strengths=["系统设计"],
    )


def _jd_analysis(record_id: str = "jd_alpha") -> JDAnalysis:
    return JDAnalysis(
        jd_analysis_id=record_id,
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_jd",
        evidence_refs=["artifact_jd"],
        created_at=_now(),
        updated_at=_now(),
        company="Example Co",
        position="AI 应用开发工程师",
        required_skills=["Python", "RAG"],
    )


def _job_fit_report(record_id: str = "fit_alpha") -> JobFitReport:
    return JobFitReport(
        job_fit_report_id=record_id,
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_jd",
        evidence_refs=["resume_profile_alpha", "career_profile_default", "jd_alpha", "artifact_jd"],
        created_at=_now(),
        updated_at=_now(),
        jd_analysis_id="jd_alpha",
        resume_profile_id="resume_profile_alpha",
        career_profile_id="career_profile_default",
        overall_score=82,
        score_breakdown={"skills": 80, "projects": 85},
        matched_evidence=["Python 后端经历"],
        gaps=["RAG 面试题准备不足"],
        recommendation="recommended",
        report_artifact_id="artifact_fit_report",
    )


def _resume_version(record_id: str = "resume_version_alpha") -> ResumeVersion:
    return ResumeVersion(
        resume_version_id=record_id,
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resume_version",
        evidence_refs=["resume_profile_alpha", "jd_alpha", "fit_alpha", "artifact_resume_version"],
        created_at=_now(),
        updated_at=_now(),
        base_resume_profile_id="resume_profile_alpha",
        target_jd_analysis_id="jd_alpha",
        title="AI 应用开发简历版本",
        format="markdown",
        artifact_id="artifact_resume_version",
        change_summary=["强化 RAG 项目"],
    )


def test_career_store_persists_all_record_types_across_instances(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_resume_profile(_resume_profile())
    store.save_career_profile(_career_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_job_fit_report())
    store.save_resume_version(_resume_version())

    reloaded = _store(tmp_path)

    resume = reloaded.get_resume_profile("resume_profile_alpha")
    career = reloaded.get_career_profile()
    jd = reloaded.get_jd_analysis("jd_alpha")
    fit = reloaded.get_job_fit_report("fit_alpha")
    version = reloaded.get_resume_version("resume_version_alpha")

    assert resume is not None
    assert resume.basic_info["name"] == "候选人"
    assert resume.diagnosis_artifact_id == "artifact_resume_diagnosis"
    assert career is not None
    assert career.career_goal == "AI 应用开发"
    assert jd is not None
    assert jd.source_artifact_id == "artifact_jd"
    assert fit is not None
    assert fit.source_artifact_id == "artifact_jd"
    assert fit.report_artifact_id == "artifact_fit_report"
    assert version is not None
    assert version.artifact_id == "artifact_resume_version"
    assert not list((tmp_path / "career").rglob("*.md"))


def test_career_store_lists_active_records_and_archives(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_resume_profile(_resume_profile("resume_profile_alpha"))
    store.save_resume_profile(_resume_profile("resume_profile_beta"))

    archived = store.archive_resume_profile("resume_profile_alpha")
    active_records = store.list_resume_profiles()
    all_records = store.list_resume_profiles(include_archived=True)

    assert archived is not None
    assert archived.status == CareerRecordStatus.ARCHIVED
    assert [record.resume_profile_id for record in active_records] == ["resume_profile_beta"]
    assert {record.resume_profile_id for record in all_records} == {"resume_profile_alpha", "resume_profile_beta"}
    assert store.archive_resume_profile("resume_profile_missing") is None


def test_career_store_owns_record_timestamps(tmp_path: Path) -> None:
    ticks = iter(
        [
            datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
            datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
            datetime(2026, 5, 7, 3, 0, tzinfo=UTC),
        ]
    )
    store = CareerProductStore(root_dir=tmp_path / "career", clock=lambda: next(ticks))

    created = store.save_resume_profile(_resume_profile())
    updated_input = _resume_profile()
    updated_input.basic_info = {"name": "更新后候选人"}
    updated = store.save_resume_profile(updated_input)
    archived = store.archive_resume_profile("resume_profile_alpha")

    assert created.created_at == datetime(2026, 5, 7, 1, 0, tzinfo=UTC)
    assert created.updated_at == datetime(2026, 5, 7, 1, 0, tzinfo=UTC)
    assert updated.created_at == created.created_at
    assert updated.updated_at == datetime(2026, 5, 7, 2, 0, tzinfo=UTC)
    assert archived is not None
    assert archived.created_at == created.created_at
    assert archived.updated_at == datetime(2026, 5, 7, 3, 0, tzinfo=UTC)


def test_career_store_serializes_timestamps_in_shanghai_timezone(tmp_path: Path) -> None:
    store = CareerProductStore(
        root_dir=tmp_path / "career",
        clock=lambda: datetime(2026, 5, 8, 0, 30, tzinfo=UTC),
    )

    store.save_resume_profile(_resume_profile())
    payload = json.loads((tmp_path / "career" / "resumes" / "resume_profile_alpha" / "profile.json").read_text())
    reloaded = _store(tmp_path).get_resume_profile("resume_profile_alpha")

    assert payload["created_at"] == "2026-05-08T08:30:00+08:00"
    assert payload["updated_at"] == "2026-05-08T08:30:00+08:00"
    assert reloaded is not None
    assert reloaded.created_at.isoformat() == "2026-05-08T08:30:00+08:00"


def test_career_profile_merge_preserves_existing_values_and_appends_lists(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_career_profile(_career_profile())

    updated = store.merge_career_profile(
        "career_profile_default",
        updates={
            "career_goal": "",
            "target_roles": ["AI 应用开发", "后端开发"],
            "strengths": ["Agent 系统设计"],
            "education_summary": "硕士学历",
        },
        evidence_refs=["resume_profile_alpha", "artifact_resume"],
    )

    assert updated.career_goal == "AI 应用开发"
    assert updated.target_roles == ["后端开发", "AI 应用开发"]
    assert updated.strengths == ["系统设计", "Agent 系统设计"]
    assert updated.education_summary == "硕士学历"
    assert updated.evidence_refs == ["resume_profile_alpha", "artifact_resume"]
    assert updated.updated_at >= updated.created_at


def test_career_profile_merge_rejects_unknown_fields_and_missing_evidence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_career_profile(_career_profile())

    with pytest.raises(ValidationError):
        store.merge_career_profile(
            "career_profile_default",
            updates={"unknown": "value"},
            evidence_refs=["resume_profile_alpha"],
        )
    with pytest.raises(ValidationError):
        store.merge_career_profile(
            "career_profile_default",
            updates={"career_goal": "新目标"},
            evidence_refs=[],
        )
    with pytest.raises(ValidationError):
        store.merge_career_profile(
            "career_profile_missing",
            updates={"career_goal": "新目标"},
            evidence_refs=["resume_profile_alpha"],
        )


def test_career_models_validate_ids_status_and_evidence_format(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValidationError):
        store.save_resume_profile(_resume_profile("resume-alpha"))
    with pytest.raises(ValidationError):
        ResumeProfile(
            resume_profile_id="resume_profile_alpha",
            status=cast(CareerRecordStatus, "deleted"),
            source_session_id="sess_alpha",
            source_artifact_id="artifact_resume",
            evidence_refs=["artifact_resume"],
            created_at=_now(),
            updated_at=_now(),
        )
    with pytest.raises(ValidationError):
        ResumeProfile(
            resume_profile_id="resume_profile_alpha",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="session_alpha",
            source_artifact_id="artifact_resume",
            evidence_refs=["artifact_resume"],
            created_at=_now(),
            updated_at=_now(),
        )
    with pytest.raises(ValidationError):
        ResumeProfile(
            resume_profile_id="resume_profile_alpha",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id="artifact_resume",
            evidence_refs=["not_a_ref"],
            created_at=_now(),
            updated_at=_now(),
        )


def test_job_fit_report_id_is_globally_unique(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_job_fit_report(_job_fit_report("fit_alpha"))

    duplicate = _job_fit_report("fit_alpha")
    duplicate.jd_analysis_id = "jd_beta"
    duplicate.evidence_refs = ["resume_profile_alpha", "career_profile_default", "jd_beta", "artifact_jd"]

    with pytest.raises(ValidationError):
        store.save_job_fit_report(duplicate)


def test_evidence_refs_validate_format_but_not_cross_record_existence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    report = JobFitReport(
        job_fit_report_id="fit_orphan",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_missing_jd",
        evidence_refs=["resume_profile_missing", "career_profile_missing", "jd_missing", "artifact_missing_jd"],
        created_at=_now(),
        updated_at=_now(),
        jd_analysis_id="jd_missing",
        resume_profile_id="resume_profile_missing",
        career_profile_id="career_profile_missing",
        report_artifact_id="artifact_missing_report",
    )

    store.save_job_fit_report(report)

    loaded = store.get_job_fit_report("fit_orphan")
    assert loaded is not None
    assert loaded.jd_analysis_id == "jd_missing"
    assert loaded.report_artifact_id == "artifact_missing_report"


def test_career_store_raises_stable_error_for_corrupt_json(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_resume_profile(_resume_profile("resume_profile_bad"))
    path = tmp_path / "career" / "resumes" / "resume_profile_bad" / "profile.json"
    path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_resume_profile("resume_profile_bad")
    with pytest.raises(StorageError):
        store.list_resume_profiles()


def test_career_store_rejects_schema_type_mismatch_on_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_career_profile(_career_profile())
    path = tmp_path / "career" / "profiles" / "career_profile_default.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["target_roles"] = "后端开发"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_career_profile()
    with pytest.raises(StorageError):
        store.list_career_profiles()


def test_career_store_rejects_base_schema_type_mismatch_on_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_resume_profile(_resume_profile("resume_profile_bad_schema"))
    path = tmp_path / "career" / "resumes" / "resume_profile_bad_schema" / "profile.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_session_id"] = 123
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_resume_profile("resume_profile_bad_schema")
