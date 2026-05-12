"""Tests for the learning product store."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from app.core.errors import StorageError, ValidationError
from app.learning.models import (
    ConfidenceLevel,
    LearningPlan,
    LearningPlanType,
    LearningPriority,
    LearningRecordStatus,
    LearningTask,
    LearningTaskState,
    LearningTaskType,
    ProgressCheckin,
    ProgressState,
    ReviewSchedule,
    ReviewState,
    ReviewType,
    WeaknessSeverity,
    WeaknessState,
    WeaknessTracker,
    WeaknessType,
)
from app.learning.store import LearningStore


def _now() -> datetime:
    return datetime(2026, 5, 12, 0, 0, tzinfo=UTC)


def _store(tmp_path: Path) -> LearningStore:
    return LearningStore(root_dir=tmp_path / "learning")


def _plan(record_id: str = "learning_plan_stargazer_backend") -> LearningPlan:
    return LearningPlan(
        learning_plan_id=record_id,
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report",
        evidence_refs=["artifact_fit_report", "fit_stargazer_backend", "application_alpha"],
        created_at=_now(),
        updated_at=_now(),
        title="Backend agent interview plan",
        description="Close gaps from the fit report before interview.",
        plan_type=LearningPlanType.INTERVIEW_PREP,
        target_application_id="application_alpha",
        target_role="AI agent backend engineer",
        target_company="Stargazer",
        start_date=_now(),
        end_date=datetime(2026, 5, 26, 0, 0, tzinfo=UTC),
        priority=LearningPriority.HIGH,
        goals=["Explain RAG evaluation", "Prepare async task design"],
        focus_skill_tags=["RAG", "FastAPI", "Async tasks"],
        task_ids=["learning_task_rag_eval"],
        weakness_ids=["weakness_rag_depth"],
        review_schedule_ids=["review_rag_eval"],
        progress_summary="Not started.",
    )


def _task(record_id: str = "learning_task_rag_eval") -> LearningTask:
    return LearningTask(
        learning_task_id=record_id,
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report",
        evidence_refs=["learning_plan_stargazer_backend", "resource_rag_eval"],
        created_at=_now(),
        updated_at=_now(),
        title="Prepare RAG evaluation answer",
        learning_plan_id="learning_plan_stargazer_backend",
        description="Write a concise explanation for chunking, retrieval and metrics.",
        task_type=LearningTaskType.WRITE_ANSWER,
        priority=LearningPriority.HIGH,
        state=LearningTaskState.TODO,
        skill_tags=["RAG"],
        estimated_minutes=45,
        planned_start_date=_now(),
        due_date=datetime(2026, 5, 13, 0, 0, tzinfo=UTC),
        resource_refs=["resource_rag_eval", "skill_req_rag_engineering"],
        question_refs=["question_rag_chunk_strategy"],
        note_refs=["note_rag_draft"],
        output_artifact_id="artifact_answer_draft",
        success_criteria=["Covers metrics", "Includes failure recovery"],
        progress_notes="Draft required.",
    )


def _checkin(record_id: str = "checkin_rag_eval_day1") -> ProgressCheckin:
    return ProgressCheckin(
        checkin_id=record_id,
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=None,
        evidence_refs=["learning_task_rag_eval", "note_rag_draft"],
        created_at=_now(),
        updated_at=_now(),
        learning_plan_id="learning_plan_stargazer_backend",
        learning_task_id="learning_task_rag_eval",
        checkin_date=_now(),
        minutes_spent=30,
        progress_state=ProgressState.IN_PROGRESS,
        summary="Outlined retrieval metrics.",
        blockers=["Need one production example"],
        confidence=ConfidenceLevel.MEDIUM,
        next_action="Add evaluation example.",
        note_refs=["note_rag_draft"],
    )


def _weakness(record_id: str = "weakness_rag_depth") -> WeaknessTracker:
    return WeaknessTracker(
        weakness_id=record_id,
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report",
        evidence_refs=["fit_stargazer_backend", "learning_plan_stargazer_backend"],
        created_at=_now(),
        updated_at=_now(),
        title="RAG depth is thin",
        description="Fit report flags limited RAG production evidence.",
        weakness_type=WeaknessType.SKILL_GAP,
        severity=WeaknessSeverity.HIGH,
        state=WeaknessState.OPEN,
        skill_tags=["RAG"],
        target_application_ids=["application_alpha"],
        source_report_ids=["fit_stargazer_backend", "artifact_fit_report"],
        related_task_ids=["learning_task_rag_eval"],
        related_note_ids=["note_rag_draft"],
        last_observed_at=_now(),
        resolution_summary="",
    )


def _review(record_id: str = "review_rag_eval") -> ReviewSchedule:
    return ReviewSchedule(
        review_schedule_id=record_id,
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=None,
        evidence_refs=["learning_task_rag_eval", "weakness_rag_depth"],
        created_at=_now(),
        updated_at=_now(),
        title="Review RAG answer",
        learning_plan_id="learning_plan_stargazer_backend",
        learning_task_id="learning_task_rag_eval",
        weakness_id="weakness_rag_depth",
        review_type=ReviewType.INTERVIEW_REHEARSAL,
        review_at=datetime(2026, 5, 14, 0, 0, tzinfo=UTC),
        interval_days=2,
        state=ReviewState.SCHEDULED,
        resource_refs=["resource_rag_eval"],
        question_refs=["question_rag_chunk_strategy"],
        note_refs=["note_rag_draft"],
        next_review_at=datetime(2026, 5, 16, 0, 0, tzinfo=UTC),
        summary="Practice verbally.",
    )


def test_learning_store_persists_all_record_types_across_instances(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_learning_plan(_plan())
    store.save_learning_task(_task())
    store.save_progress_checkin(_checkin())
    store.save_weakness_tracker(_weakness())
    store.save_review_schedule(_review())

    reloaded = _store(tmp_path)
    plan = reloaded.get_learning_plan("learning_plan_stargazer_backend")
    task = reloaded.get_learning_task("learning_task_rag_eval")
    checkin = reloaded.get_progress_checkin("checkin_rag_eval_day1")
    weakness = reloaded.get_weakness_tracker("weakness_rag_depth")
    review = reloaded.get_review_schedule("review_rag_eval")

    assert plan is not None
    assert plan.plan_type == LearningPlanType.INTERVIEW_PREP
    assert plan.task_ids == ["learning_task_rag_eval"]
    assert task is not None
    assert task.task_type == LearningTaskType.WRITE_ANSWER
    assert task.resource_refs == ["resource_rag_eval", "skill_req_rag_engineering"]
    assert checkin is not None
    assert checkin.confidence == ConfidenceLevel.MEDIUM
    assert weakness is not None
    assert weakness.source_report_ids == ["fit_stargazer_backend", "artifact_fit_report"]
    assert review is not None
    assert review.review_type == ReviewType.INTERVIEW_REHEARSAL
    assert not list((tmp_path / "learning").rglob("*.md"))


def test_learning_store_lists_active_records_and_archives(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_learning_plan(_plan("learning_plan_active"))
    store.save_learning_plan(_plan("learning_plan_archived"))
    store.save_learning_task(_task("learning_task_active"))
    store.save_learning_task(_task("learning_task_archived"))

    archived_plan = store.archive_learning_plan("learning_plan_archived")
    archived_task = store.archive_learning_task("learning_task_archived")

    assert archived_plan is not None
    assert archived_plan.status == LearningRecordStatus.ARCHIVED
    assert archived_task is not None
    assert archived_task.status == LearningRecordStatus.ARCHIVED
    assert [record.learning_plan_id for record in store.list_learning_plans()] == ["learning_plan_active"]
    assert {record.learning_plan_id for record in store.list_learning_plans(include_archived=True)} == {
        "learning_plan_active",
        "learning_plan_archived",
    }
    assert [record.learning_task_id for record in store.list_learning_tasks()] == ["learning_task_active"]
    assert store.archive_learning_plan("learning_plan_missing") is None
    assert store.archive_learning_task("learning_task_missing") is None


def test_learning_store_filters_records(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_alpha = _task("learning_task_alpha")
    task_alpha.learning_plan_id = "learning_plan_alpha"
    task_beta = _task("learning_task_beta")
    task_beta.learning_plan_id = "learning_plan_beta"
    task_beta.state = LearningTaskState.DONE
    checkin_alpha = _checkin("checkin_alpha")
    checkin_alpha.learning_plan_id = "learning_plan_alpha"
    checkin_alpha.learning_task_id = "learning_task_alpha"
    checkin_alpha.progress_state = ProgressState.COMPLETED
    checkin_beta = _checkin("checkin_beta")
    checkin_beta.learning_plan_id = "learning_plan_beta"
    checkin_beta.learning_task_id = "learning_task_beta"
    checkin_beta.progress_state = ProgressState.BLOCKED
    weakness_alpha = _weakness("weakness_alpha")
    weakness_alpha.target_application_ids = ["application_alpha"]
    weakness_beta = _weakness("weakness_beta")
    weakness_beta.target_application_ids = ["application_beta"]
    weakness_beta.state = WeaknessState.IMPROVING
    review_alpha = _review("review_alpha")
    review_alpha.learning_plan_id = "learning_plan_alpha"
    review_alpha.learning_task_id = "learning_task_alpha"
    review_alpha.weakness_id = "weakness_alpha"
    review_beta = _review("review_beta")
    review_beta.learning_plan_id = "learning_plan_beta"
    review_beta.learning_task_id = "learning_task_beta"
    review_beta.weakness_id = "weakness_beta"
    review_beta.state = ReviewState.DONE
    store.save_learning_task(task_alpha)
    store.save_learning_task(task_beta)
    store.save_progress_checkin(checkin_alpha)
    store.save_progress_checkin(checkin_beta)
    store.save_weakness_tracker(weakness_alpha)
    store.save_weakness_tracker(weakness_beta)
    store.save_review_schedule(review_alpha)
    store.save_review_schedule(review_beta)

    assert [item.learning_task_id for item in store.list_learning_tasks(learning_plan_id="learning_plan_alpha")] == [
        "learning_task_alpha"
    ]
    assert [item.learning_task_id for item in store.list_learning_tasks(state="done")] == ["learning_task_beta"]
    assert [item.checkin_id for item in store.list_progress_checkins(learning_task_id="learning_task_alpha")] == [
        "checkin_alpha"
    ]
    assert [item.checkin_id for item in store.list_progress_checkins(progress_state=ProgressState.BLOCKED)] == [
        "checkin_beta"
    ]
    assert [item.weakness_id for item in store.list_weakness_trackers(target_application_id="application_beta")] == [
        "weakness_beta"
    ]
    assert [item.review_schedule_id for item in store.list_review_schedules(weakness_id="weakness_alpha")] == [
        "review_alpha"
    ]
    assert [item.review_schedule_id for item in store.list_review_schedules(state="done")] == ["review_beta"]


def test_learning_store_owns_timestamps_and_serializes_shanghai_time(tmp_path: Path) -> None:
    ticks = iter(
        [
            datetime(2026, 5, 12, 1, 0, tzinfo=UTC),
            datetime(2026, 5, 12, 2, 0, tzinfo=UTC),
            datetime(2026, 5, 12, 3, 0, tzinfo=UTC),
        ]
    )
    store = LearningStore(root_dir=tmp_path / "learning", clock=lambda: next(ticks))

    created = store.save_learning_plan(_plan())
    updated = store.update_learning_plan("learning_plan_stargazer_backend", updates={"progress_summary": "In progress."})
    archived = store.archive_learning_plan("learning_plan_stargazer_backend")
    payload = json.loads(
        (tmp_path / "learning" / "plans" / "learning_plan_stargazer_backend.json").read_text(encoding="utf-8")
    )

    assert created.created_at.isoformat() == "2026-05-12T09:00:00+08:00"
    assert created.updated_at == created.created_at
    assert updated.created_at == created.created_at
    assert updated.updated_at.isoformat() == "2026-05-12T10:00:00+08:00"
    assert archived is not None
    assert archived.created_at == created.created_at
    assert archived.updated_at.isoformat() == "2026-05-12T11:00:00+08:00"
    assert payload["created_at"] == "2026-05-12T09:00:00+08:00"
    assert payload["updated_at"] == "2026-05-12T11:00:00+08:00"


def test_learning_task_state_update_sets_completed_time(tmp_path: Path) -> None:
    ticks = iter(
        [
            datetime(2026, 5, 12, 1, 0, tzinfo=UTC),
            datetime(2026, 5, 12, 2, 0, tzinfo=UTC),
        ]
    )
    store = LearningStore(root_dir=tmp_path / "learning", clock=lambda: next(ticks))
    store.save_learning_task(_task())

    completed = store.update_task_state("learning_task_rag_eval", state="done")

    assert completed.state == LearningTaskState.DONE
    assert completed.completed_at is not None
    assert completed.completed_at.isoformat() == "2026-05-12T10:00:00+08:00"
    assert completed.updated_at == completed.completed_at


def test_learning_update_validates_allowed_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_learning_plan(_plan())
    store.save_learning_task(_task())
    store.save_progress_checkin(_checkin())
    store.save_weakness_tracker(_weakness())
    store.save_review_schedule(_review())

    plan = store.update_learning_plan(
        "learning_plan_stargazer_backend",
        updates={"priority": "medium", "focus_skill_tags": ["RAG", "System design"]},
    )
    task = store.update_learning_task("learning_task_rag_eval", updates={"estimated_minutes": 60, "state": "doing"})
    checkin = store.update_progress_checkin("checkin_rag_eval_day1", updates={"confidence": "high"})
    weakness = store.update_weakness_tracker("weakness_rag_depth", updates={"state": "improving"})
    review = store.update_review_schedule("review_rag_eval", updates={"state": "done"})

    assert plan.priority == LearningPriority.MEDIUM
    assert task.state == LearningTaskState.DOING
    assert task.estimated_minutes == 60
    assert checkin.confidence == ConfidenceLevel.HIGH
    assert weakness.state == WeaknessState.IMPROVING
    assert review.state == ReviewState.DONE
    with pytest.raises(ValidationError):
        store.update_learning_plan("learning_plan_stargazer_backend", updates={"created_at": _now()})
    with pytest.raises(ValidationError):
        store.update_learning_task("learning_task_missing", updates={"title": "Missing"})


def test_learning_models_validate_ids_status_and_refs_format(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValidationError):
        _plan("bad-plan")
    with pytest.raises(ValidationError):
        LearningPlan(
            learning_plan_id="learning_plan_alpha",
            status=cast(LearningRecordStatus, "deleted"),
            source_session_id="sess_alpha",
            source_artifact_id=None,
            evidence_refs=[],
            created_at=_now(),
            updated_at=_now(),
            title="Bad status",
        )
    with pytest.raises(ValidationError):
        LearningPlan(
            learning_plan_id="learning_plan_alpha",
            status=LearningRecordStatus.ACTIVE,
            source_session_id="session_alpha",
            source_artifact_id=None,
            evidence_refs=[],
            created_at=_now(),
            updated_at=_now(),
            title="Bad session",
        )
    with pytest.raises(ValidationError):
        bad_ref = _plan("learning_plan_bad_ref")
        bad_ref.evidence_refs = ["bad_ref"]
        store.save_learning_plan(bad_ref)
    with pytest.raises(ValidationError):
        bad_task = _task("learning_task_bad_resource")
        bad_task.resource_refs = ["fit_alpha"]
        store.save_learning_task(bad_task)
    with pytest.raises(ValidationError):
        bad_minutes = _task("learning_task_bad_minutes")
        bad_minutes.estimated_minutes = cast(int, True)
        store.save_learning_task(bad_minutes)


def test_learning_refs_validate_format_but_not_cross_record_existence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan = LearningPlan(
        learning_plan_id="learning_plan_orphan",
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_missing",
        evidence_refs=[
            "artifact_missing",
            "application_missing",
            "resume_profile_missing",
            "career_profile_missing",
            "jd_missing",
            "fit_missing",
            "resume_version_missing",
            "note_missing",
            "resource_missing",
            "experience_missing",
            "question_missing",
            "company_missing",
            "skill_req_missing",
            "learning_task_missing",
            "checkin_missing",
            "weakness_missing",
            "review_missing",
            "sess_alpha",
        ],
        created_at=_now(),
        updated_at=_now(),
        title="Orphan plan",
        target_application_id="application_missing",
        task_ids=["learning_task_missing"],
        weakness_ids=["weakness_missing"],
        review_schedule_ids=["review_missing"],
    )
    task = LearningTask(
        learning_task_id="learning_task_orphan",
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_missing",
        evidence_refs=["learning_plan_missing", "resource_missing"],
        created_at=_now(),
        updated_at=_now(),
        title="Orphan task",
        learning_plan_id="learning_plan_missing",
        resource_refs=["resource_missing", "skill_req_missing", "artifact_missing"],
        question_refs=["question_missing"],
        note_refs=["note_missing"],
    )

    store.save_learning_plan(plan)
    store.save_learning_task(task)

    loaded_plan = store.get_learning_plan("learning_plan_orphan")
    loaded_task = store.get_learning_task("learning_task_orphan")
    assert loaded_plan is not None
    assert loaded_plan.target_application_id == "application_missing"
    assert loaded_task is not None
    assert loaded_task.learning_plan_id == "learning_plan_missing"


def test_learning_store_raises_stable_error_for_corrupt_json(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_learning_plan(_plan("learning_plan_bad"))
    path = tmp_path / "learning" / "plans" / "learning_plan_bad.json"
    path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_learning_plan("learning_plan_bad")
    with pytest.raises(StorageError):
        store.list_learning_plans()


def test_learning_store_rejects_schema_type_mismatch_on_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_learning_plan(_plan("learning_plan_bad_schema"))
    path = tmp_path / "learning" / "plans" / "learning_plan_bad_schema.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["goals"] = "RAG"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_learning_plan("learning_plan_bad_schema")
    with pytest.raises(StorageError):
        store.list_learning_plans()


def test_learning_store_rejects_source_session_schema_type_mismatch_on_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_weakness_tracker(_weakness("weakness_bad_schema"))
    path = tmp_path / "learning" / "weaknesses" / "weakness_bad_schema.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_session_id"] = 123
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_weakness_tracker("weakness_bad_schema")
    with pytest.raises(StorageError):
        store.list_weakness_trackers()

