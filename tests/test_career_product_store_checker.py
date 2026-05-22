"""Tests for CareerProductStore consistency checks."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.career.models import (
    CareerApplication,
    CareerProfile,
    CareerRecordStatus,
    JDAnalysis,
    JobFitReport,
    ResumeProfile,
    ResumeVersion,
)
from app.career.store import CareerProductStore
from app.domain.models import SessionArtifact
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from tools.check_career_product_store import check_career_product_store, main as checker_main


def _now() -> datetime:
    return datetime(2026, 5, 8, 8, 0, tzinfo=UTC)


def _create_session_with_artifacts(tmp_path: Path, artifact_ids: list[str]) -> JsonlSessionRepository:
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session("sess_alpha")
    for artifact_id in artifact_ids:
        _add_text_artifact(repository, artifact_id=artifact_id)
    return repository


def _add_text_artifact(
    repository: JsonlSessionRepository,
    *,
    artifact_id: str,
    content: str | None = None,
) -> None:
    session_id = "sess_alpha"
    root = repository.get_session_root_path(session_id)
    artifact_dir = root / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    content_path = artifact_dir / "content.txt"
    artifact_content = content or f"{artifact_id} content"
    content_path.write_text(artifact_content, encoding="utf-8")
    repository.add_or_update_session_artifact(
        SessionArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            kind="generated_file",
            title=f"{artifact_id}.txt",
            media_type="text/plain",
            size_bytes=content_path.stat().st_size,
            status="ready",
            visibility="session_shared",
            created_at=_now(),
            updated_at=_now(),
            storage_relpath=str(content_path.relative_to(root)),
            text_relpath=str(content_path.relative_to(root)),
            text_char_count=len(artifact_content),
            token_estimate=4,
            parsed_at=_now(),
        )
    )


def _store(tmp_path: Path) -> CareerProductStore:
    return CareerProductStore(root_dir=tmp_path / "career", clock=_now)


def _save_clean_product_records(store: CareerProductStore) -> None:
    store.save_resume_profile(
        ResumeProfile(
            resume_profile_id="resume_profile_alpha",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id="artifact_resume",
            evidence_refs=["artifact_resume", "artifact_diagnosis"],
            created_at=_now(),
            updated_at=_now(),
            basic_info={"name": "候选人"},
            skills=["Python"],
            raw_text_artifact_id="artifact_resume",
            diagnosis_artifact_id="artifact_diagnosis",
        )
    )
    store.save_career_profile(
        CareerProfile(
            career_profile_id="career_profile_default",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id=None,
            evidence_refs=["resume_profile_alpha", "artifact_resume"],
            created_at=_now(),
            updated_at=_now(),
            career_goal="AI 应用开发",
            target_roles=["后端开发"],
        )
    )
    store.save_jd_analysis(
        JDAnalysis(
            jd_analysis_id="jd_alpha",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id="artifact_jd",
            evidence_refs=["artifact_jd"],
            created_at=_now(),
            updated_at=_now(),
            company="Example",
            position="AI 工程师",
        )
    )
    store.save_job_fit_report(
        JobFitReport(
            job_fit_report_id="fit_alpha",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id="artifact_jd",
            evidence_refs=["resume_profile_alpha", "career_profile_default", "jd_alpha", "artifact_report"],
            created_at=_now(),
            updated_at=_now(),
            jd_analysis_id="jd_alpha",
            resume_profile_id="resume_profile_alpha",
            career_profile_id="career_profile_default",
            report_artifact_id="artifact_report",
        )
    )
    store.save_resume_version(
        ResumeVersion(
            resume_version_id="resume_version_alpha",
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
        )
    )
    store.save_career_application(
        CareerApplication(
            application_id="application_alpha",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id="artifact_jd",
            evidence_refs=[
                "artifact_jd",
                "resume_profile_alpha",
                "career_profile_default",
                "jd_alpha",
                "fit_alpha",
                "resume_version_alpha",
            ],
            created_at=_now(),
            updated_at=_now(),
            company="Example",
            position="AI 工程师",
            stage="ready_to_apply",
            priority="high",
            resume_profile_id="resume_profile_alpha",
            career_profile_id="career_profile_default",
            jd_analysis_id="jd_alpha",
            job_fit_report_id="fit_alpha",
            resume_version_ids=["resume_version_alpha"],
            summary="Example · AI 工程师，已准备投递。",
            next_actions=["确认投递渠道"],
            risks=["RAG 项目细节需补充"],
        )
    )


def test_career_product_store_checker_passes_clean_records(tmp_path: Path) -> None:
    _create_session_with_artifacts(
        tmp_path,
        [
            "artifact_resume",
            "artifact_diagnosis",
            "artifact_jd",
            "artifact_report",
            "artifact_resume_version",
        ],
    )
    _save_clean_product_records(_store(tmp_path))

    report = check_career_product_store(tmp_path, session_id="sess_alpha")

    assert report.success
    assert report.findings == []
    assert report.counts["resume_profiles"] == 1
    assert report.counts["resume_versions"] == 1
    assert report.counts["career_applications"] == 1


def test_career_product_store_checker_reports_missing_refs_and_duplicates(tmp_path: Path) -> None:
    _create_session_with_artifacts(tmp_path, ["artifact_jd"])
    store = _store(tmp_path)
    store.save_jd_analysis(
        JDAnalysis(
            jd_analysis_id="jd_alpha",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id="artifact_jd",
            evidence_refs=["artifact_jd"],
            created_at=_now(),
            updated_at=_now(),
        )
    )
    store.save_jd_analysis(
        JDAnalysis(
            jd_analysis_id="jd_beta",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id="artifact_jd",
            evidence_refs=["artifact_jd"],
            created_at=_now(),
            updated_at=_now(),
        )
    )
    store.save_job_fit_report(
        JobFitReport(
            job_fit_report_id="fit_orphan",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id="artifact_jd",
            evidence_refs=[
                "artifact_jd",
                "artifact_missing_evidence",
                "resume_profile_missing",
                "career_profile_missing",
                "jd_alpha",
            ],
            created_at=_now(),
            updated_at=_now(),
            jd_analysis_id="jd_alpha",
            resume_profile_id="resume_profile_missing",
            career_profile_id="career_profile_missing",
            report_artifact_id="artifact_missing_report",
        )
    )

    report = check_career_product_store(tmp_path, session_id="sess_alpha")
    codes = {item.code for item in report.findings}

    assert not report.success
    assert "duplicate_jd_analysis_source" in codes
    assert "missing_artifact_ref" in codes
    assert "missing_product_ref" in codes


def test_career_product_store_checker_reports_application_quality_and_duplicates(tmp_path: Path) -> None:
    _create_session_with_artifacts(
        tmp_path,
        [
            "artifact_resume",
            "artifact_diagnosis",
            "artifact_jd",
            "artifact_report",
            "artifact_resume_version",
        ],
    )
    store = _store(tmp_path)
    _save_clean_product_records(store)
    store.save_career_application(
        CareerApplication(
            application_id="application_beta",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id="artifact_jd",
            evidence_refs=["artifact_jd", "resume_profile_missing", "jd_missing"],
            created_at=_now(),
            updated_at=_now(),
            company="Example",
            position="AI 工程师",
            stage="ready_to_apply",
            priority="medium",
            resume_profile_id="resume_profile_missing",
            jd_analysis_id="jd_missing",
            job_fit_report_id="fit_missing",
            resume_version_ids=["resume_version_missing"],
            summary="这里是占位摘要，待替换为真实数据。",
        )
    )

    report = check_career_product_store(tmp_path, session_id="sess_alpha")
    codes = {item.code for item in report.findings}

    assert not report.success
    assert "career_application_placeholder_text" in codes
    assert "duplicate_career_application_source" in codes
    assert "missing_product_ref" not in codes


def test_career_product_store_checker_reports_application_jd_field_mismatch(tmp_path: Path) -> None:
    _create_session_with_artifacts(
        tmp_path,
        [
            "artifact_resume",
            "artifact_diagnosis",
            "artifact_jd",
            "artifact_report",
            "artifact_resume_version",
        ],
    )
    store = _store(tmp_path)
    _save_clean_product_records(store)
    store.save_career_application(
        CareerApplication(
            application_id="application_wrong_jd",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id="artifact_jd",
            evidence_refs=[
                "artifact_jd",
                "resume_profile_alpha",
                "career_profile_default",
                "jd_alpha",
                "fit_alpha",
            ],
            created_at=_now(),
            updated_at=_now(),
            company="XX科技有限公司",
            position="新媒体运营专员",
            stage="ready_to_apply",
            resume_profile_id="resume_profile_alpha",
            career_profile_id="career_profile_default",
            jd_analysis_id="jd_alpha",
            job_fit_report_id="fit_alpha",
        )
    )

    report = check_career_product_store(tmp_path, session_id="sess_alpha")
    codes = {item.code for item in report.findings}

    assert not report.success
    assert "career_application_jd_field_mismatch" in codes


def test_career_product_store_checker_reports_corrupt_json(tmp_path: Path) -> None:
    _create_session_with_artifacts(tmp_path, ["artifact_resume"])
    store = _store(tmp_path)
    store.save_resume_profile(
        ResumeProfile(
            resume_profile_id="resume_profile_bad",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id="artifact_resume",
            evidence_refs=["artifact_resume"],
            created_at=_now(),
            updated_at=_now(),
        )
    )
    path = tmp_path / "career" / "resumes" / "resume_profile_bad" / "profile.json"
    path.write_text("{bad json", encoding="utf-8")

    report = check_career_product_store(tmp_path, session_id="sess_alpha")

    assert not report.success
    assert [item.code for item in report.findings] == ["record_load_failed"]


def test_career_product_store_checker_cli_outputs_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _create_session_with_artifacts(tmp_path, ["artifact_resume"])

    exit_code = checker_main(["--data-dir", str(tmp_path), "--session-id", "sess_alpha", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["success"] is True
    assert payload["counts"]["artifacts"] == 1


def test_career_product_store_checker_rejects_resume_version_placeholder_and_unverified_metrics(
    tmp_path: Path,
) -> None:
    repository = _create_session_with_artifacts(
        tmp_path,
        [
            "artifact_resume",
            "artifact_diagnosis",
            "artifact_jd",
            "artifact_report",
            "artifact_resume_version",
            "artifact_resume_version_bad",
        ],
    )
    _add_text_artifact(
        repository,
        artifact_id="artifact_resume_version_bad",
        content="项目成果：检索命中率 85%+，端到端时延 <2s。",
    )
    store = _store(tmp_path)
    _save_clean_product_records(store)
    store.save_resume_version(
        ResumeVersion(
            resume_version_id="resume_version_bad",
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id="artifact_resume_version_bad",
            evidence_refs=[
                "resume_profile_alpha",
                "jd_alpha",
                "fit_alpha",
                "artifact_resume",
                "artifact_resume_version_bad",
            ],
            created_at=_now(),
            updated_at=_now(),
            base_resume_profile_id="resume_profile_alpha",
            target_jd_analysis_id="jd_alpha",
            title="含占位的简历版本",
            format="markdown",
            artifact_id="artifact_resume_version_bad",
            change_summary=["补充项目量化指标占位"],
            risk_notes=["量化指标需替换为真实数据"],
        )
    )

    report = check_career_product_store(tmp_path, session_id="sess_alpha")
    codes = {item.code for item in report.findings}

    assert not report.success
    assert "resume_version_placeholder_text" in codes
    assert "resume_version_unverified_metric" in codes
