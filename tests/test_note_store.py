"""Tests for the user note asset store."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from app.core.errors import StorageError, ValidationError
from app.notes.models import (
    Note,
    NoteCollection,
    NoteCollectionKind,
    NoteRecordStatus,
    NoteSourceRef,
    NoteSourceType,
)
from app.notes.store import NoteStore


def _now() -> datetime:
    return datetime(2026, 5, 12, 0, 0, tzinfo=UTC)


def _store(tmp_path: Path) -> NoteStore:
    return NoteStore(root_dir=tmp_path / "notes")


def _collection(record_id: str = "collection_interview") -> NoteCollection:
    return NoteCollection(
        collection_id=record_id,
        status=NoteRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        created_at=_now(),
        updated_at=_now(),
        name="面试复盘",
        description="目标岗位面试复盘",
        kind=NoteCollectionKind.INTERVIEW,
        tags=["面试", "RAG"],
    )


def _note(record_id: str = "note_alpha") -> Note:
    return Note(
        note_id=record_id,
        status=NoteRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_report",
        evidence_refs=[
            "application_alpha",
            "artifact_report",
            "fit_alpha",
            "resume_profile_alpha",
            "career_profile_default",
        ],
        created_at=_now(),
        updated_at=_now(),
        title="星河智能投递前检查复盘",
        body_markdown="## 结论\n先补 RAG 项目证据，再投递。",
        collection_id="collection_interview",
        tags=["投递前检查", "RAG"],
        source_refs=[
            NoteSourceRef(
                source_type=NoteSourceType.ARTIFACT,
                source_id="artifact_report",
                source_session_id="sess_alpha",
                title="投递前检查报告",
                quote="RAG 项目证据不足",
            ),
            NoteSourceRef(
                source_type=NoteSourceType.CAREER_APPLICATION,
                source_id="application_alpha",
                source_session_id="sess_alpha",
                title="星河智能 AI Agent 后端工程师",
            ),
        ],
        related_application_id="application_alpha",
        summary="投递前需要补齐 RAG 项目证据。",
    )


def test_note_store_persists_notes_and_collections_across_instances(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_collection(_collection())
    store.save_note(_note())

    reloaded = _store(tmp_path)
    collection = reloaded.get_collection("collection_interview")
    note = reloaded.get_note("note_alpha")

    assert collection is not None
    assert collection.name == "面试复盘"
    assert collection.kind == NoteCollectionKind.INTERVIEW
    assert note is not None
    assert note.title == "星河智能投递前检查复盘"
    assert note.note_type.value == "note"
    assert note.body_markdown.startswith("## 结论")
    assert note.source_artifact_id == "artifact_report"
    assert note.source_refs[0].source_id == "artifact_report"
    assert note.related_application_id == "application_alpha"
    assert not list((tmp_path / "notes").rglob("*.md"))


def test_note_store_lists_active_records_and_archives(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_collection(_collection("collection_interview"))
    store.save_collection(_collection("collection_learning"))
    store.save_note(_note("note_alpha"))
    store.save_note(_note("note_beta"))

    archived_note = store.archive_note("note_alpha")
    archived_collection = store.archive_collection("collection_learning")

    assert archived_note is not None
    assert archived_note.status == NoteRecordStatus.ARCHIVED
    assert archived_collection is not None
    assert archived_collection.status == NoteRecordStatus.ARCHIVED
    assert [record.note_id for record in store.list_notes()] == ["note_beta"]
    assert {record.note_id for record in store.list_notes(include_archived=True)} == {"note_alpha", "note_beta"}
    assert [record.collection_id for record in store.list_collections()] == ["collection_interview"]
    assert store.archive_note("note_missing") is None
    assert store.archive_collection("collection_missing") is None


def test_note_store_filters_notes_by_collection_and_application(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_note(_note("note_alpha"))
    second = _note("note_beta")
    second.collection_id = None
    second.related_application_id = "application_beta"
    second.evidence_refs = ["application_beta", "artifact_report"]
    store.save_note(second)

    assert [record.note_id for record in store.list_notes(collection_id="collection_interview")] == ["note_alpha"]
    assert [record.note_id for record in store.list_notes(related_application_id="application_beta")] == ["note_beta"]


def test_note_store_owns_record_timestamps(tmp_path: Path) -> None:
    ticks = iter(
        [
            datetime(2026, 5, 12, 1, 0, tzinfo=UTC),
            datetime(2026, 5, 12, 2, 0, tzinfo=UTC),
            datetime(2026, 5, 12, 3, 0, tzinfo=UTC),
        ]
    )
    store = NoteStore(root_dir=tmp_path / "notes", clock=lambda: next(ticks))

    created = store.save_note(_note())
    updated = store.update_note("note_alpha", updates={"summary": "已更新摘要"})
    archived = store.archive_note("note_alpha")

    assert created.created_at == datetime(2026, 5, 12, 9, 0, tzinfo=created.created_at.tzinfo)
    assert created.updated_at == created.created_at
    assert updated.created_at == created.created_at
    assert updated.updated_at.isoformat() == "2026-05-12T10:00:00+08:00"
    assert archived is not None
    assert archived.created_at == created.created_at
    assert archived.updated_at.isoformat() == "2026-05-12T11:00:00+08:00"


def test_note_store_serializes_timestamps_in_shanghai_timezone(tmp_path: Path) -> None:
    store = NoteStore(
        root_dir=tmp_path / "notes",
        clock=lambda: datetime(2026, 5, 12, 0, 30, tzinfo=UTC),
    )

    store.save_note(_note())
    payload = json.loads((tmp_path / "notes" / "notes" / "note_alpha.json").read_text(encoding="utf-8"))
    reloaded = _store(tmp_path).get_note("note_alpha")

    assert payload["created_at"] == "2026-05-12T08:30:00+08:00"
    assert payload["updated_at"] == "2026-05-12T08:30:00+08:00"
    assert reloaded is not None
    assert reloaded.created_at.isoformat() == "2026-05-12T08:30:00+08:00"


def test_note_update_and_append_validate_allowed_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_note(_note())

    updated = store.update_note(
        "note_alpha",
        updates={
            "title": "更新后的投递复盘",
            "body_markdown": "## 新结论\n可以投递，但要准备 RAG 深挖。",
            "tags": ["投递前检查", "面试准备"],
            "note_type": "learning",
            "summary": "投递前准备 RAG 深挖问题。",
        },
    )
    appended = store.append_note(
        "note_alpha",
        body_markdown="## 面试后补充\n面试官追问了向量检索评估。",
        source_refs=[
            NoteSourceRef(
                source_type="manual",
                source_session_id="sess_alpha",
                title="面试后手动补充",
            )
        ],
        evidence_refs=["sess_alpha"],
    )

    assert updated.title == "更新后的投递复盘"
    assert updated.note_type.value == "learning"
    assert updated.tags == ["投递前检查", "面试准备"]
    assert "面试后补充" in appended.body_markdown
    assert appended.evidence_refs[-1] == "sess_alpha"
    assert appended.source_refs[-1].source_type == NoteSourceType.MANUAL
    with pytest.raises(ValidationError):
        store.update_note("note_alpha", updates={"unknown": "value"})
    with pytest.raises(ValidationError):
        store.append_note("note_missing", body_markdown="内容")


def test_collection_update_validate_allowed_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_collection(_collection())

    updated = store.update_collection(
        "collection_interview",
        updates={
            "name": "面试与投递复盘",
            "description": "围绕目标岗位沉淀复盘",
            "kind": "career_project",
            "tags": ["投递", "复盘"],
        },
    )

    assert updated.name == "面试与投递复盘"
    assert updated.kind == NoteCollectionKind.CAREER_PROJECT
    assert updated.tags == ["投递", "复盘"]
    with pytest.raises(ValidationError):
        store.update_collection("collection_interview", updates={"source_session_id": "sess_other"})


def test_note_models_validate_ids_status_and_refs_format(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValidationError):
        store.save_note(_note("bad-note"))
    with pytest.raises(ValidationError):
        Note(
            note_id="note_alpha",
            status=cast(NoteRecordStatus, "deleted"),
            source_session_id="sess_alpha",
            source_artifact_id=None,
            evidence_refs=[],
            created_at=_now(),
            updated_at=_now(),
            title="坏状态",
            body_markdown="正文",
        )
    with pytest.raises(ValidationError):
        Note(
            note_id="note_alpha",
            status=NoteRecordStatus.ACTIVE,
            source_session_id="session_alpha",
            source_artifact_id=None,
            evidence_refs=[],
            created_at=_now(),
            updated_at=_now(),
            title="坏会话",
            body_markdown="正文",
        )
    with pytest.raises(ValidationError):
        bad_ref = _note("note_bad_ref")
        bad_ref.evidence_refs = ["not_a_ref"]
        store.save_note(bad_ref)
    with pytest.raises(ValidationError):
        NoteSourceRef(source_type=NoteSourceType.ARTIFACT, source_id="fit_alpha")
    with pytest.raises(ValidationError):
        NoteSourceRef(source_type=NoteSourceType.ARTIFACT)
    with pytest.raises(ValidationError):
        invalid_type = _note("note_bad_type")
        invalid_type.note_type = cast(Any, "project")
        store.save_note(invalid_type)


def test_note_refs_validate_format_but_not_cross_record_existence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    note = Note(
        note_id="note_orphan",
        status=NoteRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_missing",
        evidence_refs=["application_missing", "artifact_missing", "fit_missing"],
        created_at=_now(),
        updated_at=_now(),
        title="孤立来源笔记",
        body_markdown="格式正确即可，M8 不做跨 store 存在性校验。",
        source_refs=[
            NoteSourceRef(source_type="artifact", source_id="artifact_missing"),
            NoteSourceRef(source_type="career_application", source_id="application_missing"),
        ],
        related_application_id="application_missing",
    )

    store.save_note(note)

    loaded = store.get_note("note_orphan")
    assert loaded is not None
    assert loaded.source_artifact_id == "artifact_missing"
    assert loaded.related_application_id == "application_missing"


def test_note_store_raises_stable_error_for_corrupt_json(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_note(_note("note_bad"))
    path = tmp_path / "notes" / "notes" / "note_bad.json"
    path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_note("note_bad")
    with pytest.raises(StorageError):
        store.list_notes()


def test_note_store_rejects_schema_type_mismatch_on_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_note(_note("note_bad_schema"))
    path = tmp_path / "notes" / "notes" / "note_bad_schema.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tags"] = "RAG"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_note("note_bad_schema")
    with pytest.raises(StorageError):
        store.list_notes()


def test_note_store_rejects_source_refs_schema_type_mismatch_on_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_note(_note("note_bad_source_refs"))
    path = tmp_path / "notes" / "notes" / "note_bad_source_refs.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_refs"] = [{"source_type": "artifact", "source_id": 123}]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_note("note_bad_source_refs")


def test_note_store_rejects_collection_schema_type_mismatch_on_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_collection(_collection("collection_bad_schema"))
    path = tmp_path / "notes" / "collections" / "collection_bad_schema.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_session_id"] = 123
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_collection("collection_bad_schema")
    with pytest.raises(StorageError):
        store.list_collections()
