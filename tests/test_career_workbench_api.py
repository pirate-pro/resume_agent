"""Tests for career workbench HTTP endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import get_career_product_store, get_learning_store, get_note_store
from app.career.store import CareerProductStore
from app.learning.store import LearningStore
from app.main import app
from app.notes.store import NoteStore
from tests.test_career_workbench_service import _TickingClock, _seed_records

__all__ = []


def test_career_workbench_api_lists_and_reads_workbench(tmp_path: Path) -> None:
    career_store = CareerProductStore(root_dir=tmp_path / "career", clock=_TickingClock())
    note_store = NoteStore(root_dir=tmp_path / "notes", clock=_TickingClock())
    learning_store = LearningStore(root_dir=tmp_path / "learning", clock=_TickingClock())
    _seed_records(career_store, note_store, learning_store)
    _override_stores(career_store, note_store, learning_store)

    try:
        with TestClient(app) as client:
            list_resp = client.get("/api/career/workbench")
            assert list_resp.status_code == 200
            listing = _data(list_resp)
            assert listing["active_application_id"] == "application_alpha"
            assert listing["counts"]["applications"] == 1
            assert listing["counts"]["notes"] == 1
            assert listing["applications"][0]["readiness"]["score"] == 82

            detail_resp = client.get("/api/career/workbench/applications/application_alpha")
            assert detail_resp.status_code == 200
            detail = _data(detail_resp)
            assert detail["application"]["application_id"] == "application_alpha"
            assert detail["resume_profile"]["resume_profile_id"] == "resume_profile_alpha"
            assert detail["career_profile"]["career_profile_id"] == "career_profile_default"
            assert detail["jd_analysis"]["jd_analysis_id"] == "jd_alpha"
            assert detail["job_fit_report"]["job_fit_report_id"] == "fit_alpha"
            assert [item["resume_version_id"] for item in detail["resume_versions"]] == ["resume_version_alpha"]
            assert [item["note_id"] for item in detail["notes"]] == ["note_alpha"]
            assert [item["learning_plan_id"] for item in detail["learning"]["plans"]] == ["learning_plan_alpha"]
            assert [item["learning_task_id"] for item in detail["learning"]["tasks"]] == ["learning_task_alpha"]
            assert detail["learning"]["open_task_count"] == 1
            assert detail["learning"]["high_weakness_count"] == 1
            assert {asset["type"] for asset in detail["linked_assets"]} >= {
                "resume_profile",
                "career_profile",
                "jd_analysis",
                "job_fit_report",
                "resume_version",
                "note",
            }
            assert any(action["action_type"] == "pre_apply_check" for action in detail["suggested_actions"])

            _assert_no_internal_path_leak(list_resp.json(), tmp_path)
            _assert_no_internal_path_leak(detail_resp.json(), tmp_path)
    finally:
        app.dependency_overrides.clear()


def test_career_workbench_api_returns_404_for_missing_or_archived_application(tmp_path: Path) -> None:
    career_store = CareerProductStore(root_dir=tmp_path / "career", clock=_TickingClock())
    note_store = NoteStore(root_dir=tmp_path / "notes", clock=_TickingClock())
    learning_store = LearningStore(root_dir=tmp_path / "learning", clock=_TickingClock())
    _seed_records(career_store, note_store, learning_store)
    career_store.archive_career_application("application_alpha")
    _override_stores(career_store, note_store, learning_store)

    try:
        with TestClient(app) as client:
            missing_resp = client.get("/api/career/workbench/applications/application_missing")
            assert missing_resp.status_code == 404
            archived_resp = client.get("/api/career/workbench/applications/application_alpha")
            assert archived_resp.status_code == 404
            visible_resp = client.get(
                "/api/career/workbench/applications/application_alpha",
                params={"include_archived": True},
            )
            assert visible_resp.status_code == 200
            assert _data(visible_resp)["application"]["status"] == "archived"
    finally:
        app.dependency_overrides.clear()


def _override_stores(
    career_store: CareerProductStore,
    note_store: NoteStore,
    learning_store: LearningStore,
) -> None:
    app.dependency_overrides[get_career_product_store] = lambda: career_store
    app.dependency_overrides[get_note_store] = lambda: note_store
    app.dependency_overrides[get_learning_store] = lambda: learning_store


def _data(response: Any) -> Any:
    payload = response.json()
    assert payload["code"] == 0
    assert payload["msg"] == "ok"
    return payload["data"]


def _assert_no_internal_path_leak(payload: Any, tmp_path: Path) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "data/career" not in serialized
    assert "data/notes" not in serialized
    assert "data/learning" not in serialized
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
