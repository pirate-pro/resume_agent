"""Tests for career product HTTP endpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import get_career_product_store, get_session_repository
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
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.main import app

__all__ = []


class _TickingClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 5, 7, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self._current += timedelta(minutes=1)
        return self._current


def test_career_api_lists_and_reads_active_records(tmp_path: Path) -> None:
    store = CareerProductStore(root_dir=tmp_path / "career", clock=_TickingClock())
    _seed_active_records(store)
    _override_career_store(store)

    try:
        with TestClient(app) as client:
            resumes_resp = client.get("/api/career/resumes")
            assert resumes_resp.status_code == 200
            resumes = _data(resumes_resp)
            assert [item["resume_profile_id"] for item in resumes] == ["resume_profile_alpha"]

            resume_resp = client.get("/api/career/resumes/resume_profile_alpha")
            assert resume_resp.status_code == 200
            resume = _data(resume_resp)
            assert resume["basic_info"]["name"] == "候选人"
            assert resume["raw_text_artifact_id"] == "artifact_resume"

            profile_resp = client.get("/api/career/profile")
            assert profile_resp.status_code == 200
            assert _data(profile_resp)["career_goal"] == "AI 应用开发"

            profiles_resp = client.get("/api/career/profiles")
            assert profiles_resp.status_code == 200
            assert [item["career_profile_id"] for item in _data(profiles_resp)] == ["career_profile_default"]

            jobs_resp = client.get("/api/career/jobs")
            assert jobs_resp.status_code == 200
            assert [item["jd_analysis_id"] for item in _data(jobs_resp)] == ["jd_alpha"]

            job_resp = client.get("/api/career/jobs/jd_alpha")
            assert job_resp.status_code == 200
            assert _data(job_resp)["position"] == "AI 应用开发工程师"

            fit_reports_resp = client.get("/api/career/job-fit-reports")
            assert fit_reports_resp.status_code == 200
            assert [item["job_fit_report_id"] for item in _data(fit_reports_resp)] == ["fit_alpha"]

            fit_report_resp = client.get("/api/career/job-fit-reports/fit_alpha")
            assert fit_report_resp.status_code == 200
            fit_report = _data(fit_report_resp)
            assert fit_report["source_artifact_id"] == "artifact_jd"
            assert fit_report["report_artifact_id"] == "artifact_fit_report"
            assert fit_report["overall_score"] == 82

            versions_resp = client.get("/api/career/resume-versions")
            assert versions_resp.status_code == 200
            assert [item["resume_version_id"] for item in _data(versions_resp)] == ["resume_version_alpha"]

            version_resp = client.get("/api/career/resume-versions/resume_version_alpha")
            assert version_resp.status_code == 200
            assert _data(version_resp)["artifact_id"] == "artifact_resume_version"

            applications_resp = client.get("/api/career/applications")
            assert applications_resp.status_code == 200
            assert [item["application_id"] for item in _data(applications_resp)] == ["application_alpha"]

            application_resp = client.get("/api/career/applications/application_alpha")
            assert application_resp.status_code == 200
            application = _data(application_resp)
            assert application["company"] == "Example Co"
            assert application["position"] == "AI 应用开发工程师"
            assert application["job_fit_report_id"] == "fit_alpha"
            assert application["resume_version_ids"] == ["resume_version_alpha"]

            for response in (
                resumes_resp,
                resume_resp,
                profile_resp,
                profiles_resp,
                jobs_resp,
                job_resp,
                fit_reports_resp,
                fit_report_resp,
                versions_resp,
                version_resp,
                applications_resp,
                application_resp,
            ):
                _assert_no_internal_path_leak(response.json(), tmp_path)
    finally:
        app.dependency_overrides.clear()


def test_career_api_returns_404_for_missing_records(tmp_path: Path) -> None:
    store = CareerProductStore(root_dir=tmp_path / "career")
    _override_career_store(store)

    try:
        with TestClient(app) as client:
            for path in (
                "/api/career/profile",
                "/api/career/resumes/resume_profile_missing",
                "/api/career/profiles/career_profile_missing",
                "/api/career/jobs/jd_missing",
                "/api/career/job-fit-reports/fit_missing",
                "/api/career/resume-versions/resume_version_missing",
                "/api/career/applications/application_missing",
            ):
                response = client.get(path)
                assert response.status_code == 404
                payload = response.json()
                assert payload["code"] == 404
                assert payload["data"] is None
    finally:
        app.dependency_overrides.clear()


def test_career_api_filters_archived_records_by_default(tmp_path: Path) -> None:
    store = CareerProductStore(root_dir=tmp_path / "career", clock=_TickingClock())
    _seed_resume_profile(store, "resume_profile_active")
    _seed_resume_profile(store, "resume_profile_archived")
    store.archive_resume_profile("resume_profile_archived")
    _override_career_store(store)

    try:
        with TestClient(app) as client:
            active_resp = client.get("/api/career/resumes")
            assert active_resp.status_code == 200
            assert [item["resume_profile_id"] for item in _data(active_resp)] == ["resume_profile_active"]

            archived_detail_resp = client.get("/api/career/resumes/resume_profile_archived")
            assert archived_detail_resp.status_code == 404

            all_resp = client.get("/api/career/resumes", params={"include_archived": True})
            assert all_resp.status_code == 200
            assert {
                item["resume_profile_id"]
                for item in _data(all_resp)
            } == {"resume_profile_active", "resume_profile_archived"}

            archived_visible_resp = client.get(
                "/api/career/resumes/resume_profile_archived",
                params={"include_archived": True},
            )
            assert archived_visible_resp.status_code == 200
            assert _data(archived_visible_resp)["status"] == "archived"
    finally:
        app.dependency_overrides.clear()


def test_career_api_updates_application_status_with_self_evidence(tmp_path: Path) -> None:
    store = CareerProductStore(root_dir=tmp_path / "career", clock=_TickingClock())
    _seed_active_records(store)
    _override_career_store(store)

    try:
        with TestClient(app) as client:
            response = client.patch(
                "/api/career/applications/application_alpha",
                json={
                    "stage": "applied",
                    "priority": "medium",
                    "next_actions": ["准备一面自我介绍"],
                    "risks": ["RAG 项目指标需要准备口径"],
                    "notes": "用户手动更新投递状态。",
                },
            )

        assert response.status_code == 200
        payload = _data(response)
        assert payload["stage"] == "applied"
        assert payload["priority"] == "medium"
        assert payload["next_actions"] == ["完善 RAG 面试题", "准备一面自我介绍"]
        assert payload["risks"] == ["RAG 经验表达需要补证据", "RAG 项目指标需要准备口径"]
        assert payload["notes"] == "用户手动更新投递状态。"
        assert payload["evidence_refs"] == [
            "resume_profile_alpha",
            "career_profile_default",
            "jd_alpha",
            "fit_alpha",
            "application_alpha",
        ]
    finally:
        app.dependency_overrides.clear()


def test_career_api_rejects_empty_application_update(tmp_path: Path) -> None:
    store = CareerProductStore(root_dir=tmp_path / "career")
    _seed_active_records(store)
    _override_career_store(store)

    try:
        with TestClient(app) as client:
            response = client.patch("/api/career/applications/application_alpha", json={})

        assert response.status_code == 400
        payload = response.json()
        assert payload["code"] == 400
        assert "at least one editable field" in payload["msg"]
    finally:
        app.dependency_overrides.clear()


def test_career_api_generates_and_accepts_resume_version_draft(tmp_path: Path) -> None:
    store = CareerProductStore(root_dir=tmp_path / "career", clock=_TickingClock())
    session_repository = JsonlSessionRepository(tmp_path / "sessions")
    _seed_active_records(store)
    _override_career_store(store)
    app.dependency_overrides[get_session_repository] = lambda: session_repository

    try:
        with TestClient(app) as client:
            generate_resp = client.post(
                "/api/career/resume-version-drafts/generate",
                json={
                    "application_id": "application_alpha",
                    "resume_profile_id": "resume_profile_alpha",
                    "target_jd_analysis_id": "jd_alpha",
                    "job_fit_report_id": "fit_alpha",
                    "title": "Example Co 定制版草案",
                    "strategy": ["突出 Agent 项目", "补强量化成果"],
                },
            )
            assert generate_resp.status_code == 201
            draft = _data(generate_resp)["draft"]
            draft_id = draft["resume_version_draft_id"]
            assert draft_id.startswith("resume_version_draft_")
            assert draft["application_id"] == "application_alpha"
            assert draft["markdown"].startswith("# 候选人")
            assert "AI 应用开发工程师" in draft["markdown"]
            assert "补强量化成果" in draft["change_summary"]

            accept_resp = client.post(
                f"/api/career/resume-version-drafts/{draft_id}/accept",
                json={"link_application": True},
            )
            assert accept_resp.status_code == 200
            accepted = _data(accept_resp)
            version = accepted["resume_version"]
            assert version["resume_version_id"].startswith("resume_version_")
            assert version["artifact_id"].startswith("artifact_resume_version_")
            assert accepted["draft"]["accepted_resume_version_id"] == version["resume_version_id"]

            application = store.get_career_application("application_alpha")
            assert application is not None
            assert version["resume_version_id"] in application.resume_version_ids
            artifact_text = session_repository.read_session_artifact_text(
                version["source_session_id"],
                version["artifact_id"],
            )
            assert "Example Co 定制版草案" in version["title"]
            assert "AI 应用开发工程师" in artifact_text

            repeat_resp = client.post(
                f"/api/career/resume-version-drafts/{draft_id}/accept",
                json={"link_application": True},
            )
            assert repeat_resp.status_code == 200
            repeat = _data(repeat_resp)
            assert repeat["resume_version"]["resume_version_id"] == version["resume_version_id"]
    finally:
        app.dependency_overrides.clear()


def _seed_active_records(store: CareerProductStore) -> None:
    _seed_resume_profile(store, "resume_profile_alpha")
    store.save_career_profile(_career_profile())
    store.save_jd_analysis(_jd_analysis())
    store.save_job_fit_report(_job_fit_report())
    store.save_resume_version(_resume_version())
    store.save_career_application(_career_application())


def _seed_resume_profile(store: CareerProductStore, record_id: str) -> None:
    store.save_resume_profile(
        ResumeProfile(
            resume_profile_id=record_id,
            status=CareerRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id="artifact_resume",
            evidence_refs=["artifact_resume"],
            created_at=_seed_time(),
            updated_at=_seed_time(),
            basic_info={"name": "候选人"},
            education=[{"school": "Example University"}],
            skills=["Python", "FastAPI"],
            raw_text_artifact_id="artifact_resume",
            diagnosis_artifact_id="artifact_resume_diagnosis",
            diagnosis={"strengths": ["后端经验"]},
        )
    )


def _career_profile() -> CareerProfile:
    return CareerProfile(
        career_profile_id="career_profile_default",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=None,
        evidence_refs=["resume_profile_alpha"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        career_goal="AI 应用开发",
        target_roles=["后端开发"],
        strengths=["系统设计"],
    )


def _jd_analysis() -> JDAnalysis:
    return JDAnalysis(
        jd_analysis_id="jd_alpha",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_jd",
        evidence_refs=["artifact_jd"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        company="Example Co",
        position="AI 应用开发工程师",
        required_skills=["Python", "RAG"],
    )


def _job_fit_report() -> JobFitReport:
    return JobFitReport(
        job_fit_report_id="fit_alpha",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_jd",
        evidence_refs=["resume_profile_alpha", "career_profile_default", "jd_alpha", "artifact_jd"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
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


def _resume_version() -> ResumeVersion:
    return ResumeVersion(
        resume_version_id="resume_version_alpha",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resume_version",
        evidence_refs=["resume_profile_alpha", "jd_alpha", "fit_alpha", "artifact_resume_version"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        base_resume_profile_id="resume_profile_alpha",
        target_jd_analysis_id="jd_alpha",
        title="AI 应用开发简历版本",
        format="markdown",
        artifact_id="artifact_resume_version",
        change_summary=["强化 RAG 项目"],
    )


def _career_application() -> CareerApplication:
    return CareerApplication(
        application_id="application_alpha",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_jd",
        evidence_refs=["resume_profile_alpha", "career_profile_default", "jd_alpha", "fit_alpha"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        company="Example Co",
        position="AI 应用开发工程师",
        location="上海",
        stage="ready_to_apply",
        priority="high",
        resume_profile_id="resume_profile_alpha",
        career_profile_id="career_profile_default",
        jd_analysis_id="jd_alpha",
        job_fit_report_id="fit_alpha",
        resume_version_ids=["resume_version_alpha"],
        summary="匹配度较高，适合优先投递。",
        next_actions=["完善 RAG 面试题"],
        risks=["RAG 经验表达需要补证据"],
    )


def _seed_time() -> datetime:
    return datetime(2026, 5, 7, 0, 0, tzinfo=UTC)


def _override_career_store(store: CareerProductStore) -> None:
    app.dependency_overrides[get_career_product_store] = lambda: store


def _data(response: Any) -> Any:
    payload = response.json()
    assert payload["code"] == 0
    assert payload["msg"] == "ok"
    return payload["data"]


def _assert_no_internal_path_leak(payload: Any, tmp_path: Path) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "data/career" not in serialized
    _assert_no_path_key(payload)


def _assert_no_path_key(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in {"path", "root_dir", "workspace_path"}
            _assert_no_path_key(item)
        return
    if isinstance(value, list):
        for item in value:
            _assert_no_path_key(item)
