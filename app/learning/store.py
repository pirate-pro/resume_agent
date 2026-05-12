"""File-backed store for learning plans and progress tracking."""

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
from app.learning.models import (
    LearningPlan,
    LearningRecordStatus,
    LearningTask,
    LearningTaskState,
    ProgressCheckin,
    ProgressState,
    ReviewSchedule,
    ReviewState,
    WeaknessState,
    WeaknessTracker,
    validate_checkin_id,
    validate_learning_plan_id,
    validate_learning_task_id,
    validate_optional_application_id,
    validate_optional_learning_plan_id,
    validate_optional_learning_task_id,
    validate_optional_weakness_id,
    validate_review_schedule_id,
    validate_weakness_id,
)

__all__ = ["LearningStore"]

_RecordT = TypeVar(
    "_RecordT",
    LearningPlan,
    LearningTask,
    ProgressCheckin,
    WeaknessTracker,
    ReviewSchedule,
)
_EnumT = TypeVar("_EnumT", bound=Enum)
_PLAN_UPDATE_FIELDS = {
    "description",
    "end_date",
    "evidence_refs",
    "focus_skill_tags",
    "goals",
    "plan_type",
    "priority",
    "progress_summary",
    "review_schedule_ids",
    "source_artifact_id",
    "start_date",
    "target_application_id",
    "target_company",
    "target_role",
    "task_ids",
    "title",
    "weakness_ids",
}
_TASK_UPDATE_FIELDS = {
    "completed_at",
    "description",
    "due_date",
    "estimated_minutes",
    "evidence_refs",
    "learning_plan_id",
    "note_refs",
    "output_artifact_id",
    "planned_start_date",
    "priority",
    "progress_notes",
    "question_refs",
    "resource_refs",
    "skill_tags",
    "source_artifact_id",
    "state",
    "success_criteria",
    "task_type",
    "title",
}
_CHECKIN_UPDATE_FIELDS = {
    "blockers",
    "checkin_date",
    "confidence",
    "evidence_refs",
    "learning_plan_id",
    "learning_task_id",
    "minutes_spent",
    "next_action",
    "note_refs",
    "progress_state",
    "source_artifact_id",
    "summary",
}
_WEAKNESS_UPDATE_FIELDS = {
    "description",
    "evidence_refs",
    "last_observed_at",
    "related_note_ids",
    "related_task_ids",
    "resolved_at",
    "resolution_summary",
    "severity",
    "skill_tags",
    "source_artifact_id",
    "source_report_ids",
    "state",
    "target_application_ids",
    "title",
    "weakness_type",
}
_REVIEW_UPDATE_FIELDS = {
    "evidence_refs",
    "interval_days",
    "last_reviewed_at",
    "learning_plan_id",
    "learning_task_id",
    "next_review_at",
    "note_refs",
    "question_refs",
    "resource_refs",
    "review_at",
    "review_type",
    "source_artifact_id",
    "state",
    "summary",
    "title",
    "weakness_id",
}


class LearningStore:
    """Persist learning product records as atomic JSON files."""

    def __init__(self, root_dir: Path, clock: Callable[[], datetime] | None = None) -> None:
        if not isinstance(root_dir, Path):
            raise ValidationError("root_dir must be pathlib.Path.")
        self._root_dir = root_dir
        self._clock = clock or _app_now
        self._plans_dir = self._root_dir / "plans"
        self._tasks_dir = self._root_dir / "tasks"
        self._checkins_dir = self._root_dir / "checkins"
        self._weaknesses_dir = self._root_dir / "weaknesses"
        self._reviews_dir = self._root_dir / "reviews"
        for path in (
            self._plans_dir,
            self._tasks_dir,
            self._checkins_dir,
            self._weaknesses_dir,
            self._reviews_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise ValidationError("clock must return datetime.")
        return normalize_app_datetime(value)

    def save_learning_plan(self, record: LearningPlan) -> LearningPlan:
        if not isinstance(record, LearningPlan):
            raise ValidationError("record must be LearningPlan.")
        validated = record.copy()
        path = self._plan_path(validated.learning_plan_id)
        stamped = _stamp_record(validated, _read_record(path, _learning_plan_from_payload), self._now())
        _write_json_payload(path, _learning_plan_to_payload(stamped))
        return stamped.copy()

    def get_learning_plan(self, learning_plan_id: str) -> LearningPlan | None:
        return _read_record(
            self._plan_path(validate_learning_plan_id(learning_plan_id)),
            _learning_plan_from_payload,
        )

    def list_learning_plans(
        self,
        *,
        include_archived: bool = False,
        target_application_id: str | None = None,
    ) -> list[LearningPlan]:
        records = [_read_record_required(path, _learning_plan_from_payload) for path in sorted(self._plans_dir.glob("*.json"))]
        filtered = _filter_and_sort(records, include_archived=include_archived)
        if target_application_id is not None:
            normalized = validate_optional_application_id("target_application_id", target_application_id)
            filtered = [record for record in filtered if record.target_application_id == normalized]
        return [record.copy() for record in filtered]

    def update_learning_plan(self, learning_plan_id: str, *, updates: dict[str, Any]) -> LearningPlan:
        record = self.get_learning_plan(learning_plan_id)
        if record is None:
            raise ValidationError(f"LearningPlan not found: {learning_plan_id}")
        normalized_updates = _normalize_update_payload(updates, allowed_fields=_PLAN_UPDATE_FIELDS)
        return self.save_learning_plan(replace(record, **normalized_updates))

    def archive_learning_plan(self, learning_plan_id: str) -> LearningPlan | None:
        record = self.get_learning_plan(learning_plan_id)
        if record is None:
            return None
        return self.save_learning_plan(replace(record, status=LearningRecordStatus.ARCHIVED))

    def save_learning_task(self, record: LearningTask) -> LearningTask:
        return self._save_learning_task(record, now=self._now())

    def get_learning_task(self, learning_task_id: str) -> LearningTask | None:
        return _read_record(
            self._task_path(validate_learning_task_id(learning_task_id)),
            _learning_task_from_payload,
        )

    def list_learning_tasks(
        self,
        *,
        include_archived: bool = False,
        learning_plan_id: str | None = None,
        state: LearningTaskState | str | None = None,
    ) -> list[LearningTask]:
        records = [_read_record_required(path, _learning_task_from_payload) for path in sorted(self._tasks_dir.glob("*.json"))]
        filtered = _filter_and_sort(records, include_archived=include_archived)
        if learning_plan_id is not None:
            normalized_plan_id = validate_optional_learning_plan_id("learning_plan_id", learning_plan_id)
            filtered = [record for record in filtered if record.learning_plan_id == normalized_plan_id]
        if state is not None:
            normalized_state = _normalize_enum_filter("state", state, LearningTaskState)
            filtered = [record for record in filtered if record.state == normalized_state]
        return [record.copy() for record in filtered]

    def update_learning_task(self, learning_task_id: str, *, updates: dict[str, Any]) -> LearningTask:
        record = self.get_learning_task(learning_task_id)
        if record is None:
            raise ValidationError(f"LearningTask not found: {learning_task_id}")
        normalized_updates = _normalize_update_payload(updates, allowed_fields=_TASK_UPDATE_FIELDS)
        return self.save_learning_task(replace(record, **normalized_updates))

    def update_task_state(
        self,
        learning_task_id: str,
        *,
        state: LearningTaskState | str,
        completed_at: datetime | None = None,
    ) -> LearningTask:
        record = self.get_learning_task(learning_task_id)
        if record is None:
            raise ValidationError(f"LearningTask not found: {learning_task_id}")
        now = self._now()
        normalized_state = _normalize_enum_filter("state", state, LearningTaskState)
        effective_completed_at = completed_at
        if normalized_state == LearningTaskState.DONE and effective_completed_at is None:
            effective_completed_at = now
        updated = replace(record, state=normalized_state, completed_at=effective_completed_at)
        return self._save_learning_task(updated, now=now)

    def archive_learning_task(self, learning_task_id: str) -> LearningTask | None:
        record = self.get_learning_task(learning_task_id)
        if record is None:
            return None
        return self.save_learning_task(replace(record, status=LearningRecordStatus.ARCHIVED))

    def append_progress_checkin(self, record: ProgressCheckin) -> ProgressCheckin:
        return self.save_progress_checkin(record)

    def save_progress_checkin(self, record: ProgressCheckin) -> ProgressCheckin:
        if not isinstance(record, ProgressCheckin):
            raise ValidationError("record must be ProgressCheckin.")
        validated = record.copy()
        path = self._checkin_path(validated.checkin_id)
        stamped = _stamp_record(validated, _read_record(path, _progress_checkin_from_payload), self._now())
        _write_json_payload(path, _progress_checkin_to_payload(stamped))
        return stamped.copy()

    def get_progress_checkin(self, checkin_id: str) -> ProgressCheckin | None:
        return _read_record(
            self._checkin_path(validate_checkin_id(checkin_id)),
            _progress_checkin_from_payload,
        )

    def list_progress_checkins(
        self,
        *,
        include_archived: bool = False,
        learning_plan_id: str | None = None,
        learning_task_id: str | None = None,
        progress_state: ProgressState | str | None = None,
    ) -> list[ProgressCheckin]:
        records = [
            _read_record_required(path, _progress_checkin_from_payload)
            for path in sorted(self._checkins_dir.glob("*.json"))
        ]
        filtered = _filter_and_sort(records, include_archived=include_archived)
        if learning_plan_id is not None:
            normalized_plan_id = validate_optional_learning_plan_id("learning_plan_id", learning_plan_id)
            filtered = [record for record in filtered if record.learning_plan_id == normalized_plan_id]
        if learning_task_id is not None:
            normalized_task_id = validate_optional_learning_task_id("learning_task_id", learning_task_id)
            filtered = [record for record in filtered if record.learning_task_id == normalized_task_id]
        if progress_state is not None:
            normalized_state = _normalize_enum_filter("progress_state", progress_state, ProgressState)
            filtered = [record for record in filtered if record.progress_state == normalized_state]
        return [record.copy() for record in filtered]

    def update_progress_checkin(self, checkin_id: str, *, updates: dict[str, Any]) -> ProgressCheckin:
        record = self.get_progress_checkin(checkin_id)
        if record is None:
            raise ValidationError(f"ProgressCheckin not found: {checkin_id}")
        normalized_updates = _normalize_update_payload(updates, allowed_fields=_CHECKIN_UPDATE_FIELDS)
        return self.save_progress_checkin(replace(record, **normalized_updates))

    def archive_progress_checkin(self, checkin_id: str) -> ProgressCheckin | None:
        record = self.get_progress_checkin(checkin_id)
        if record is None:
            return None
        return self.save_progress_checkin(replace(record, status=LearningRecordStatus.ARCHIVED))

    def save_weakness_tracker(self, record: WeaknessTracker) -> WeaknessTracker:
        if not isinstance(record, WeaknessTracker):
            raise ValidationError("record must be WeaknessTracker.")
        validated = record.copy()
        path = self._weakness_path(validated.weakness_id)
        stamped = _stamp_record(validated, _read_record(path, _weakness_tracker_from_payload), self._now())
        _write_json_payload(path, _weakness_tracker_to_payload(stamped))
        return stamped.copy()

    def get_weakness_tracker(self, weakness_id: str) -> WeaknessTracker | None:
        return _read_record(
            self._weakness_path(validate_weakness_id(weakness_id)),
            _weakness_tracker_from_payload,
        )

    def list_weakness_trackers(
        self,
        *,
        include_archived: bool = False,
        state: WeaknessState | str | None = None,
        target_application_id: str | None = None,
    ) -> list[WeaknessTracker]:
        records = [
            _read_record_required(path, _weakness_tracker_from_payload)
            for path in sorted(self._weaknesses_dir.glob("*.json"))
        ]
        filtered = _filter_and_sort(records, include_archived=include_archived)
        if state is not None:
            normalized_state = _normalize_enum_filter("state", state, WeaknessState)
            filtered = [record for record in filtered if record.state == normalized_state]
        if target_application_id is not None:
            normalized_application_id = validate_optional_application_id(
                "target_application_id",
                target_application_id,
            )
            filtered = [
                record
                for record in filtered
                if normalized_application_id in record.target_application_ids
            ]
        return [record.copy() for record in filtered]

    def update_weakness_tracker(self, weakness_id: str, *, updates: dict[str, Any]) -> WeaknessTracker:
        record = self.get_weakness_tracker(weakness_id)
        if record is None:
            raise ValidationError(f"WeaknessTracker not found: {weakness_id}")
        normalized_updates = _normalize_update_payload(updates, allowed_fields=_WEAKNESS_UPDATE_FIELDS)
        return self.save_weakness_tracker(replace(record, **normalized_updates))

    def archive_weakness_tracker(self, weakness_id: str) -> WeaknessTracker | None:
        record = self.get_weakness_tracker(weakness_id)
        if record is None:
            return None
        return self.save_weakness_tracker(replace(record, status=LearningRecordStatus.ARCHIVED))

    def save_review_schedule(self, record: ReviewSchedule) -> ReviewSchedule:
        if not isinstance(record, ReviewSchedule):
            raise ValidationError("record must be ReviewSchedule.")
        validated = record.copy()
        path = self._review_path(validated.review_schedule_id)
        stamped = _stamp_record(validated, _read_record(path, _review_schedule_from_payload), self._now())
        _write_json_payload(path, _review_schedule_to_payload(stamped))
        return stamped.copy()

    def get_review_schedule(self, review_schedule_id: str) -> ReviewSchedule | None:
        return _read_record(
            self._review_path(validate_review_schedule_id(review_schedule_id)),
            _review_schedule_from_payload,
        )

    def list_review_schedules(
        self,
        *,
        include_archived: bool = False,
        learning_plan_id: str | None = None,
        learning_task_id: str | None = None,
        weakness_id: str | None = None,
        state: ReviewState | str | None = None,
    ) -> list[ReviewSchedule]:
        records = [
            _read_record_required(path, _review_schedule_from_payload)
            for path in sorted(self._reviews_dir.glob("*.json"))
        ]
        filtered = _filter_and_sort(records, include_archived=include_archived)
        if learning_plan_id is not None:
            normalized_plan_id = validate_optional_learning_plan_id("learning_plan_id", learning_plan_id)
            filtered = [record for record in filtered if record.learning_plan_id == normalized_plan_id]
        if learning_task_id is not None:
            normalized_task_id = validate_optional_learning_task_id("learning_task_id", learning_task_id)
            filtered = [record for record in filtered if record.learning_task_id == normalized_task_id]
        if weakness_id is not None:
            normalized_weakness_id = validate_optional_weakness_id("weakness_id", weakness_id)
            filtered = [record for record in filtered if record.weakness_id == normalized_weakness_id]
        if state is not None:
            normalized_state = _normalize_enum_filter("state", state, ReviewState)
            filtered = [record for record in filtered if record.state == normalized_state]
        return [record.copy() for record in filtered]

    def update_review_schedule(self, review_schedule_id: str, *, updates: dict[str, Any]) -> ReviewSchedule:
        record = self.get_review_schedule(review_schedule_id)
        if record is None:
            raise ValidationError(f"ReviewSchedule not found: {review_schedule_id}")
        normalized_updates = _normalize_update_payload(updates, allowed_fields=_REVIEW_UPDATE_FIELDS)
        return self.save_review_schedule(replace(record, **normalized_updates))

    def archive_review_schedule(self, review_schedule_id: str) -> ReviewSchedule | None:
        record = self.get_review_schedule(review_schedule_id)
        if record is None:
            return None
        return self.save_review_schedule(replace(record, status=LearningRecordStatus.ARCHIVED))

    def _save_learning_task(self, record: LearningTask, *, now: datetime) -> LearningTask:
        if not isinstance(record, LearningTask):
            raise ValidationError("record must be LearningTask.")
        validated = record.copy()
        path = self._task_path(validated.learning_task_id)
        stamped = _stamp_record(validated, _read_record(path, _learning_task_from_payload), now)
        _write_json_payload(path, _learning_task_to_payload(stamped))
        return stamped.copy()

    def _plan_path(self, learning_plan_id: str) -> Path:
        return self._plans_dir / f"{learning_plan_id}.json"

    def _task_path(self, learning_task_id: str) -> Path:
        return self._tasks_dir / f"{learning_task_id}.json"

    def _checkin_path(self, checkin_id: str) -> Path:
        return self._checkins_dir / f"{checkin_id}.json"

    def _weakness_path(self, weakness_id: str) -> Path:
        return self._weaknesses_dir / f"{weakness_id}.json"

    def _review_path(self, review_schedule_id: str) -> Path:
        return self._reviews_dir / f"{review_schedule_id}.json"


def _learning_plan_to_payload(record: LearningPlan) -> dict[str, Any]:
    return {
        "created_at": _to_iso(record.created_at),
        "description": record.description,
        "end_date": _optional_to_iso(record.end_date),
        "evidence_refs": record.evidence_refs,
        "focus_skill_tags": record.focus_skill_tags,
        "goals": record.goals,
        "learning_plan_id": record.learning_plan_id,
        "plan_type": _enum_value(record.plan_type),
        "priority": _enum_value(record.priority),
        "progress_summary": record.progress_summary,
        "review_schedule_ids": record.review_schedule_ids,
        "source_artifact_id": record.source_artifact_id,
        "source_session_id": record.source_session_id,
        "start_date": _optional_to_iso(record.start_date),
        "status": _enum_value(record.status),
        "target_application_id": record.target_application_id,
        "target_company": record.target_company,
        "target_role": record.target_role,
        "task_ids": record.task_ids,
        "title": record.title,
        "updated_at": _to_iso(record.updated_at),
        "weakness_ids": record.weakness_ids,
    }


def _learning_plan_from_payload(payload: dict[str, Any]) -> LearningPlan:
    return LearningPlan(
        learning_plan_id=payload["learning_plan_id"],
        status=payload["status"],
        source_session_id=payload["source_session_id"],
        source_artifact_id=payload["source_artifact_id"],
        evidence_refs=payload["evidence_refs"],
        created_at=_from_iso(payload["created_at"]),
        updated_at=_from_iso(payload["updated_at"]),
        title=payload["title"],
        description=payload["description"],
        plan_type=payload["plan_type"],
        target_application_id=payload["target_application_id"],
        target_role=payload["target_role"],
        target_company=payload["target_company"],
        start_date=_optional_from_iso(payload["start_date"]),
        end_date=_optional_from_iso(payload["end_date"]),
        priority=payload["priority"],
        goals=payload["goals"],
        focus_skill_tags=payload["focus_skill_tags"],
        task_ids=payload["task_ids"],
        weakness_ids=payload["weakness_ids"],
        review_schedule_ids=payload["review_schedule_ids"],
        progress_summary=payload["progress_summary"],
    )


def _learning_task_to_payload(record: LearningTask) -> dict[str, Any]:
    return {
        "completed_at": _optional_to_iso(record.completed_at),
        "created_at": _to_iso(record.created_at),
        "description": record.description,
        "due_date": _optional_to_iso(record.due_date),
        "estimated_minutes": record.estimated_minutes,
        "evidence_refs": record.evidence_refs,
        "learning_plan_id": record.learning_plan_id,
        "learning_task_id": record.learning_task_id,
        "note_refs": record.note_refs,
        "output_artifact_id": record.output_artifact_id,
        "planned_start_date": _optional_to_iso(record.planned_start_date),
        "priority": _enum_value(record.priority),
        "progress_notes": record.progress_notes,
        "question_refs": record.question_refs,
        "resource_refs": record.resource_refs,
        "skill_tags": record.skill_tags,
        "source_artifact_id": record.source_artifact_id,
        "source_session_id": record.source_session_id,
        "state": _enum_value(record.state),
        "status": _enum_value(record.status),
        "success_criteria": record.success_criteria,
        "task_type": _enum_value(record.task_type),
        "title": record.title,
        "updated_at": _to_iso(record.updated_at),
    }


def _learning_task_from_payload(payload: dict[str, Any]) -> LearningTask:
    return LearningTask(
        learning_task_id=payload["learning_task_id"],
        status=payload["status"],
        source_session_id=payload["source_session_id"],
        source_artifact_id=payload["source_artifact_id"],
        evidence_refs=payload["evidence_refs"],
        created_at=_from_iso(payload["created_at"]),
        updated_at=_from_iso(payload["updated_at"]),
        title=payload["title"],
        learning_plan_id=payload["learning_plan_id"],
        description=payload["description"],
        task_type=payload["task_type"],
        priority=payload["priority"],
        state=payload["state"],
        skill_tags=payload["skill_tags"],
        estimated_minutes=payload["estimated_minutes"],
        planned_start_date=_optional_from_iso(payload["planned_start_date"]),
        due_date=_optional_from_iso(payload["due_date"]),
        completed_at=_optional_from_iso(payload["completed_at"]),
        resource_refs=payload["resource_refs"],
        question_refs=payload["question_refs"],
        note_refs=payload["note_refs"],
        output_artifact_id=payload["output_artifact_id"],
        success_criteria=payload["success_criteria"],
        progress_notes=payload["progress_notes"],
    )


def _progress_checkin_to_payload(record: ProgressCheckin) -> dict[str, Any]:
    return {
        "blockers": record.blockers,
        "checkin_date": _optional_to_iso(record.checkin_date),
        "checkin_id": record.checkin_id,
        "confidence": _enum_value(record.confidence),
        "created_at": _to_iso(record.created_at),
        "evidence_refs": record.evidence_refs,
        "learning_plan_id": record.learning_plan_id,
        "learning_task_id": record.learning_task_id,
        "minutes_spent": record.minutes_spent,
        "next_action": record.next_action,
        "note_refs": record.note_refs,
        "progress_state": _enum_value(record.progress_state),
        "source_artifact_id": record.source_artifact_id,
        "source_session_id": record.source_session_id,
        "status": _enum_value(record.status),
        "summary": record.summary,
        "updated_at": _to_iso(record.updated_at),
    }


def _progress_checkin_from_payload(payload: dict[str, Any]) -> ProgressCheckin:
    return ProgressCheckin(
        checkin_id=payload["checkin_id"],
        status=payload["status"],
        source_session_id=payload["source_session_id"],
        source_artifact_id=payload["source_artifact_id"],
        evidence_refs=payload["evidence_refs"],
        created_at=_from_iso(payload["created_at"]),
        updated_at=_from_iso(payload["updated_at"]),
        learning_plan_id=payload["learning_plan_id"],
        learning_task_id=payload["learning_task_id"],
        checkin_date=_optional_from_iso(payload["checkin_date"]),
        minutes_spent=payload["minutes_spent"],
        progress_state=payload["progress_state"],
        summary=payload["summary"],
        blockers=payload["blockers"],
        confidence=payload["confidence"],
        next_action=payload["next_action"],
        note_refs=payload["note_refs"],
    )


def _weakness_tracker_to_payload(record: WeaknessTracker) -> dict[str, Any]:
    return {
        "created_at": _to_iso(record.created_at),
        "description": record.description,
        "evidence_refs": record.evidence_refs,
        "last_observed_at": _optional_to_iso(record.last_observed_at),
        "related_note_ids": record.related_note_ids,
        "related_task_ids": record.related_task_ids,
        "resolved_at": _optional_to_iso(record.resolved_at),
        "resolution_summary": record.resolution_summary,
        "severity": _enum_value(record.severity),
        "skill_tags": record.skill_tags,
        "source_artifact_id": record.source_artifact_id,
        "source_report_ids": record.source_report_ids,
        "source_session_id": record.source_session_id,
        "state": _enum_value(record.state),
        "status": _enum_value(record.status),
        "target_application_ids": record.target_application_ids,
        "title": record.title,
        "updated_at": _to_iso(record.updated_at),
        "weakness_id": record.weakness_id,
        "weakness_type": _enum_value(record.weakness_type),
    }


def _weakness_tracker_from_payload(payload: dict[str, Any]) -> WeaknessTracker:
    return WeaknessTracker(
        weakness_id=payload["weakness_id"],
        status=payload["status"],
        source_session_id=payload["source_session_id"],
        source_artifact_id=payload["source_artifact_id"],
        evidence_refs=payload["evidence_refs"],
        created_at=_from_iso(payload["created_at"]),
        updated_at=_from_iso(payload["updated_at"]),
        title=payload["title"],
        description=payload["description"],
        weakness_type=payload["weakness_type"],
        severity=payload["severity"],
        state=payload["state"],
        skill_tags=payload["skill_tags"],
        target_application_ids=payload["target_application_ids"],
        source_report_ids=payload["source_report_ids"],
        related_task_ids=payload["related_task_ids"],
        related_note_ids=payload["related_note_ids"],
        last_observed_at=_optional_from_iso(payload["last_observed_at"]),
        resolved_at=_optional_from_iso(payload["resolved_at"]),
        resolution_summary=payload["resolution_summary"],
    )


def _review_schedule_to_payload(record: ReviewSchedule) -> dict[str, Any]:
    return {
        "created_at": _to_iso(record.created_at),
        "evidence_refs": record.evidence_refs,
        "interval_days": record.interval_days,
        "last_reviewed_at": _optional_to_iso(record.last_reviewed_at),
        "learning_plan_id": record.learning_plan_id,
        "learning_task_id": record.learning_task_id,
        "next_review_at": _optional_to_iso(record.next_review_at),
        "note_refs": record.note_refs,
        "question_refs": record.question_refs,
        "resource_refs": record.resource_refs,
        "review_at": _optional_to_iso(record.review_at),
        "review_schedule_id": record.review_schedule_id,
        "review_type": _enum_value(record.review_type),
        "source_artifact_id": record.source_artifact_id,
        "source_session_id": record.source_session_id,
        "state": _enum_value(record.state),
        "status": _enum_value(record.status),
        "summary": record.summary,
        "title": record.title,
        "updated_at": _to_iso(record.updated_at),
        "weakness_id": record.weakness_id,
    }


def _review_schedule_from_payload(payload: dict[str, Any]) -> ReviewSchedule:
    return ReviewSchedule(
        review_schedule_id=payload["review_schedule_id"],
        status=payload["status"],
        source_session_id=payload["source_session_id"],
        source_artifact_id=payload["source_artifact_id"],
        evidence_refs=payload["evidence_refs"],
        created_at=_from_iso(payload["created_at"]),
        updated_at=_from_iso(payload["updated_at"]),
        title=payload["title"],
        learning_plan_id=payload["learning_plan_id"],
        learning_task_id=payload["learning_task_id"],
        weakness_id=payload["weakness_id"],
        review_type=payload["review_type"],
        review_at=_optional_from_iso(payload["review_at"]),
        interval_days=payload["interval_days"],
        state=payload["state"],
        resource_refs=payload["resource_refs"],
        question_refs=payload["question_refs"],
        note_refs=payload["note_refs"],
        last_reviewed_at=_optional_from_iso(payload["last_reviewed_at"]),
        next_review_at=_optional_from_iso(payload["next_review_at"]),
        summary=payload["summary"],
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
        raise StorageError(f"Invalid learning record '{path}': {exc}") from exc


def _read_json_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StorageError(f"Invalid learning JSON '{path}': {exc}") from exc
    except OSError as exc:
        raise StorageError(f"Failed to read learning record '{path}': {exc}") from exc
    if not isinstance(payload, dict):
        raise StorageError(f"Invalid learning JSON '{path}': root must be object.")
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
        raise StorageError(f"Failed to write learning record '{path}': {exc}") from exc


def _filter_and_sort(records: list[_RecordT], *, include_archived: bool) -> list[_RecordT]:
    output = [
        record
        for record in records
        if include_archived or record.status == LearningRecordStatus.ACTIVE
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
            raise ValidationError(f"Unsupported learning update field: {normalized_key}")
        if normalized_key in normalized:
            raise ValidationError(f"Duplicate update field: {normalized_key}")
        normalized[normalized_key] = value
    return normalized


def _normalize_enum_filter(field_name: str, value: _EnumT | str, enum_type: type[_EnumT]) -> _EnumT:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        try:
            return enum_type(normalized)
        except ValueError as exc:
            raise ValidationError(f"{field_name} is invalid: {value}") from exc
    raise ValidationError(f"{field_name} must be a string.")


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


def _optional_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _to_iso(value)


def _optional_from_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    return _from_iso(value)
