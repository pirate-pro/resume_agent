"""Tests for deterministic career frontend demo data seeding."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import get_career_product_store, get_session_artifact_service
from app.career.store import CareerProductStore
from app.main import app
from scripts.seed_career_frontend_demo import (
    DEFAULT_SESSION_ID,
    DIAGNOSIS_ARTIFACT_ID,
    FIT_REPORT_ARTIFACT_ID,
    JD_ANALYSIS_ID,
    JOB_FIT_REPORT_ID,
    RESUME_PROFILE_ID,
    RESUME_VERSION_ID,
    RESUME_VERSION_ARTIFACT_ID,
    seed_demo_data,
)
from tests.helpers import StaticModelClient, build_chat_service_bundle

__all__ = []


def test_seed_career_frontend_demo_data_is_idempotent_and_api_readable(tmp_path: Path) -> None:
    first_summary = seed_demo_data(tmp_path)
    second_summary = seed_demo_data(tmp_path)

    assert first_summary == second_summary
    assert first_summary.session_id == DEFAULT_SESSION_ID
    assert len(first_summary.artifact_ids) == 5

    store = CareerProductStore(root_dir=tmp_path / "career")
    assert [item.resume_profile_id for item in store.list_resume_profiles()] == [RESUME_PROFILE_ID]
    assert [item.career_profile_id for item in store.list_career_profiles()] == ["career_profile_m4_demo"]
    assert [item.jd_analysis_id for item in store.list_jd_analyses()] == [JD_ANALYSIS_ID]
    assert [item.job_fit_report_id for item in store.list_job_fit_reports()] == [JOB_FIT_REPORT_ID]
    assert [item.resume_version_id for item in store.list_resume_versions()] == [RESUME_VERSION_ID]

    bundle = build_chat_service_bundle(data_dir=tmp_path, model_client=StaticModelClient(content="demo-ok"))
    artifacts = bundle.chat_service._session_repository.list_session_artifacts(DEFAULT_SESSION_ID)  # noqa: SLF001
    assert [item.artifact_id for item in artifacts] == first_summary.artifact_ids
    assert bundle.chat_service._session_repository.get_active_artifact_ids(DEFAULT_SESSION_ID) == first_summary.artifact_ids  # noqa: SLF001

    app.dependency_overrides[get_career_product_store] = lambda: store
    app.dependency_overrides[get_session_artifact_service] = lambda: bundle.session_artifact_service
    try:
        with TestClient(app) as client:
            resumes_resp = client.get("/api/career/resumes")
            versions_resp = client.get("/api/career/resume-versions")
            diagnosis_resp = client.get(
                f"/api/sessions/{DEFAULT_SESSION_ID}/artifacts/{DIAGNOSIS_ARTIFACT_ID}/content"
            )
            fit_report_resp = client.get(
                f"/api/sessions/{DEFAULT_SESSION_ID}/artifacts/{FIT_REPORT_ARTIFACT_ID}/content"
            )
            resume_version_resp = client.get(
                f"/api/sessions/{DEFAULT_SESSION_ID}/artifacts/{RESUME_VERSION_ARTIFACT_ID}/content"
            )

        assert _data(resumes_resp)[0]["resume_profile_id"] == RESUME_PROFILE_ID
        assert _data(versions_resp)[0]["resume_version_id"] == RESUME_VERSION_ID
        assert _data(diagnosis_resp)["content"].startswith("# 简历诊断")
        assert _data(fit_report_resp)["content"].startswith("# 岗位匹配报告")
        assert _data(resume_version_resp)["content"].startswith("# 林一凡")
    finally:
        app.dependency_overrides.clear()


def _data(response: Any) -> Any:
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["msg"] == "ok"
    return payload["data"]
