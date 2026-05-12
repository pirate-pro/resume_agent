"""Tests for note asset HTTP endpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import get_note_store
from app.main import app
from app.notes.models import Note, NoteCollection, NoteCollectionKind, NoteRecordStatus, NoteSourceRef
from app.notes.store import NoteStore

__all__ = []


class _TickingClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self._current += timedelta(minutes=1)
        return self._current


def test_note_api_creates_lists_and_reads_records(tmp_path: Path) -> None:
    store = NoteStore(root_dir=tmp_path / "notes", clock=_TickingClock())
    _override_note_store(store)

    try:
        with TestClient(app) as client:
            collection_resp = client.post(
                "/api/notes/collections",
                json={
                    "collection_id": "collection_interview",
                    "source_session_id": "sess_alpha",
                    "name": "面试复盘",
                    "description": "目标岗位面试复盘",
                    "kind": "interview",
                    "tags": ["面试", "RAG"],
                },
            )
            assert collection_resp.status_code == 200
            collection = _data(collection_resp)
            assert collection["collection_id"] == "collection_interview"
            assert collection["kind"] == "interview"

            note_resp = client.post(
                "/api/notes",
                json={
                    "note_id": "note_alpha",
                    "source_session_id": "sess_alpha",
                    "source_artifact_id": "artifact_report",
                    "evidence_refs": ["application_alpha", "artifact_report", "fit_alpha"],
                    "title": "星河智能投递前检查复盘",
                    "body_markdown": "## 结论\n先补 RAG 项目证据，再投递。",
                    "collection_id": "collection_interview",
                    "tags": ["投递前检查", "RAG"],
                    "source_refs": [
                        {
                            "source_type": "artifact",
                            "source_id": "artifact_report",
                            "source_session_id": "sess_alpha",
                            "title": "投递前检查报告",
                        }
                    ],
                    "related_application_id": "application_alpha",
                    "summary": "投递前需要补齐 RAG 项目证据。",
                },
            )
            assert note_resp.status_code == 200
            note = _data(note_resp)
            assert note["note_id"] == "note_alpha"
            assert note["status"] == "active"
            assert note["source_refs"][0]["source_id"] == "artifact_report"
            assert note["created_at"] == "2026-05-12T08:02:00+08:00"

            notes_resp = client.get("/api/notes")
            assert notes_resp.status_code == 200
            assert [item["note_id"] for item in _data(notes_resp)] == ["note_alpha"]

            by_collection_resp = client.get(
                "/api/notes",
                params={"collection_id": "collection_interview"},
            )
            assert by_collection_resp.status_code == 200
            assert [item["note_id"] for item in _data(by_collection_resp)] == ["note_alpha"]

            by_application_resp = client.get(
                "/api/notes",
                params={"related_application_id": "application_alpha"},
            )
            assert by_application_resp.status_code == 200
            assert [item["note_id"] for item in _data(by_application_resp)] == ["note_alpha"]

            read_note_resp = client.get("/api/notes/note_alpha")
            assert read_note_resp.status_code == 200
            assert _data(read_note_resp)["body_markdown"].startswith("## 结论")

            collections_resp = client.get("/api/notes/collections")
            assert collections_resp.status_code == 200
            assert [item["collection_id"] for item in _data(collections_resp)] == ["collection_interview"]

            read_collection_resp = client.get("/api/notes/collections/collection_interview")
            assert read_collection_resp.status_code == 200
            assert _data(read_collection_resp)["name"] == "面试复盘"

            for response in (
                collection_resp,
                note_resp,
                notes_resp,
                read_note_resp,
                collections_resp,
                read_collection_resp,
            ):
                _assert_no_internal_path_leak(response.json(), tmp_path)
    finally:
        app.dependency_overrides.clear()


def test_note_api_updates_appends_and_archives_note(tmp_path: Path) -> None:
    store = NoteStore(root_dir=tmp_path / "notes", clock=_TickingClock())
    store.save_note(_note())
    _override_note_store(store)

    try:
        with TestClient(app) as client:
            update_resp = client.patch(
                "/api/notes/note_alpha",
                json={
                    "title": "更新后的投递复盘",
                    "summary": "需要准备 RAG 深挖问题。",
                    "tags": ["投递前检查", "面试准备"],
                },
            )
            assert update_resp.status_code == 200
            updated = _data(update_resp)
            assert updated["title"] == "更新后的投递复盘"
            assert updated["tags"] == ["投递前检查", "面试准备"]

            append_resp = client.post(
                "/api/notes/note_alpha/append",
                json={
                    "body_markdown": "## 面试后补充\n面试官追问了向量检索评估。",
                    "source_refs": [
                        {
                            "source_type": "manual",
                            "source_session_id": "sess_alpha",
                            "title": "面试后手动补充",
                        }
                    ],
                    "evidence_refs": ["sess_alpha"],
                },
            )
            assert append_resp.status_code == 200
            appended = _data(append_resp)
            assert "面试后补充" in appended["body_markdown"]
            assert appended["source_refs"][-1]["source_type"] == "manual"
            assert appended["evidence_refs"][-1] == "sess_alpha"

            archive_resp = client.post("/api/notes/note_alpha/archive")
            assert archive_resp.status_code == 200
            assert _data(archive_resp)["status"] == "archived"

            hidden_resp = client.get("/api/notes/note_alpha")
            assert hidden_resp.status_code == 404

            visible_resp = client.get("/api/notes/note_alpha", params={"include_archived": True})
            assert visible_resp.status_code == 200
            assert _data(visible_resp)["status"] == "archived"
    finally:
        app.dependency_overrides.clear()


def test_note_api_updates_and_archives_collection(tmp_path: Path) -> None:
    store = NoteStore(root_dir=tmp_path / "notes", clock=_TickingClock())
    store.save_collection(_collection())
    _override_note_store(store)

    try:
        with TestClient(app) as client:
            update_resp = client.patch(
                "/api/notes/collections/collection_interview",
                json={
                    "name": "面试与投递复盘",
                    "description": "围绕目标岗位沉淀复盘",
                    "kind": "career_project",
                    "tags": ["投递", "复盘"],
                },
            )
            assert update_resp.status_code == 200
            updated = _data(update_resp)
            assert updated["name"] == "面试与投递复盘"
            assert updated["kind"] == "career_project"

            archive_resp = client.post("/api/notes/collections/collection_interview/archive")
            assert archive_resp.status_code == 200
            assert _data(archive_resp)["status"] == "archived"

            hidden_resp = client.get("/api/notes/collections/collection_interview")
            assert hidden_resp.status_code == 404

            visible_resp = client.get(
                "/api/notes/collections/collection_interview",
                params={"include_archived": True},
            )
            assert visible_resp.status_code == 200
            assert _data(visible_resp)["status"] == "archived"
    finally:
        app.dependency_overrides.clear()


def test_note_api_returns_404_for_missing_records(tmp_path: Path) -> None:
    store = NoteStore(root_dir=tmp_path / "notes")
    _override_note_store(store)

    try:
        with TestClient(app) as client:
            for path in (
                "/api/notes/note_missing",
                "/api/notes/collections/collection_missing",
            ):
                response = client.get(path)
                assert response.status_code == 404
                payload = response.json()
                assert payload["code"] == 404
                assert payload["data"] is None
    finally:
        app.dependency_overrides.clear()


def test_note_api_rejects_empty_and_invalid_updates(tmp_path: Path) -> None:
    store = NoteStore(root_dir=tmp_path / "notes")
    store.save_note(_note())
    store.save_collection(_collection())
    _override_note_store(store)

    try:
        with TestClient(app) as client:
            empty_note_resp = client.patch("/api/notes/note_alpha", json={})
            assert empty_note_resp.status_code == 400
            assert "at least one editable field" in empty_note_resp.json()["msg"]

            invalid_note_resp = client.patch("/api/notes/note_alpha", json={"related_application_id": "bad"})
            assert invalid_note_resp.status_code == 400

            empty_collection_resp = client.patch("/api/notes/collections/collection_interview", json={})
            assert empty_collection_resp.status_code == 400
            assert "at least one editable field" in empty_collection_resp.json()["msg"]

            invalid_query_resp = client.get("/api/notes", params={"related_application_id": "bad"})
            assert invalid_query_resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


def _note() -> Note:
    return Note(
        note_id="note_alpha",
        status=NoteRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_report",
        evidence_refs=["application_alpha", "artifact_report", "fit_alpha"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        title="星河智能投递前检查复盘",
        body_markdown="## 结论\n先补 RAG 项目证据，再投递。",
        collection_id="collection_interview",
        tags=["投递前检查", "RAG"],
        source_refs=[
            NoteSourceRef(
                source_type="artifact",
                source_id="artifact_report",
                source_session_id="sess_alpha",
                title="投递前检查报告",
            )
        ],
        related_application_id="application_alpha",
        summary="投递前需要补齐 RAG 项目证据。",
    )


def _collection() -> NoteCollection:
    return NoteCollection(
        collection_id="collection_interview",
        status=NoteRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        created_at=_seed_time(),
        updated_at=_seed_time(),
        name="面试复盘",
        description="目标岗位面试复盘",
        kind=NoteCollectionKind.INTERVIEW,
        tags=["面试", "RAG"],
    )


def _seed_time() -> datetime:
    return datetime(2026, 5, 12, 0, 0, tzinfo=UTC)


def _override_note_store(store: NoteStore) -> None:
    app.dependency_overrides[get_note_store] = lambda: store


def _data(response: Any) -> Any:
    payload = response.json()
    assert payload["code"] == 0
    assert payload["msg"] == "ok"
    return payload["data"]


def _assert_no_internal_path_leak(payload: Any, tmp_path: Path) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "data/notes" not in serialized
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
