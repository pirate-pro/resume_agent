"""Learning plan HTTP endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_learning_store
from app.api.presenters import (
    learning_plan_view,
    learning_task_view,
    progress_checkin_view,
    review_schedule_view,
    weakness_tracker_view,
)
from app.api.responses import ok
from app.core.errors import ValidationError
from app.core.time import app_now
from app.learning.models import (
    LearningPlan,
    LearningRecordStatus,
    LearningTask,
    ProgressCheckin,
    ReviewSchedule,
    WeaknessTracker,
)
from app.learning.store import LearningStore
from app.schemas.common import StandardResponse
from app.schemas.learning import (
    LearningPlanCreateRequest,
    LearningPlanUpdateRequest,
    LearningPlanView,
    LearningTaskCreateRequest,
    LearningTaskStateUpdateRequest,
    LearningTaskUpdateRequest,
    LearningTaskView,
    ProgressCheckinCreateRequest,
    ProgressCheckinUpdateRequest,
    ProgressCheckinView,
    ReviewScheduleCreateRequest,
    ReviewScheduleUpdateRequest,
    ReviewScheduleView,
    WeaknessTrackerCreateRequest,
    WeaknessTrackerUpdateRequest,
    WeaknessTrackerView,
)

__all__ = ["admin_router", "router"]

router = APIRouter(prefix="/api/learning", tags=["learning"])
admin_router = APIRouter(prefix="/api/learning-admin", tags=["learning-admin"])
_RecordT = TypeVar(
    "_RecordT",
    LearningPlan,
    LearningTask,
    ProgressCheckin,
    WeaknessTracker,
    ReviewSchedule,
)


@router.get("/plans", response_model=StandardResponse[list[LearningPlanView]])
def list_learning_plans(
    include_archived: bool = Query(default=False),
    target_application_id: str | None = Query(default=None),
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[list[LearningPlanView]]:
    return ok([
        learning_plan_view(item)
        for item in store.list_learning_plans(
            include_archived=include_archived,
            target_application_id=target_application_id,
        )
    ])


@admin_router.post("/plans", response_model=StandardResponse[LearningPlanView])
def create_learning_plan(
    request: LearningPlanCreateRequest,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[LearningPlanView]:
    record = LearningPlan(
        learning_plan_id=request.learning_plan_id or _new_learning_plan_id(),
        status=LearningRecordStatus.ACTIVE,
        source_session_id=request.source_session_id,
        source_artifact_id=request.source_artifact_id,
        evidence_refs=request.evidence_refs,
        created_at=_placeholder_time(),
        updated_at=_placeholder_time(),
        title=request.title,
        description=request.description,
        plan_type=request.plan_type,
        target_application_id=request.target_application_id,
        target_role=request.target_role,
        target_company=request.target_company,
        start_date=request.start_date,
        end_date=request.end_date,
        priority=request.priority,
        goals=request.goals,
        focus_skill_tags=request.focus_skill_tags,
        task_ids=request.task_ids,
        weakness_ids=request.weakness_ids,
        review_schedule_ids=request.review_schedule_ids,
        progress_summary=request.progress_summary,
    )
    return ok(learning_plan_view(store.save_learning_plan(record)))


@router.get("/plans/{learning_plan_id}", response_model=StandardResponse[LearningPlanView])
def get_learning_plan(
    learning_plan_id: str,
    include_archived: bool = Query(default=False),
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[LearningPlanView]:
    record = _require_visible(
        store.get_learning_plan(learning_plan_id),
        include_archived=include_archived,
        record_type="LearningPlan",
        record_id=learning_plan_id,
    )
    return ok(learning_plan_view(record))


@admin_router.patch("/plans/{learning_plan_id}", response_model=StandardResponse[LearningPlanView])
def update_learning_plan(
    learning_plan_id: str,
    request: LearningPlanUpdateRequest,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[LearningPlanView]:
    _require_visible(
        store.get_learning_plan(learning_plan_id),
        include_archived=False,
        record_type="LearningPlan",
        record_id=learning_plan_id,
    )
    return ok(learning_plan_view(store.update_learning_plan(learning_plan_id, updates=_updates(request))))


@admin_router.post("/plans/{learning_plan_id}/archive", response_model=StandardResponse[LearningPlanView])
def archive_learning_plan(
    learning_plan_id: str,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[LearningPlanView]:
    record = store.archive_learning_plan(learning_plan_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"LearningPlan not found: {learning_plan_id}")
    return ok(learning_plan_view(record))


@router.get("/tasks", response_model=StandardResponse[list[LearningTaskView]])
def list_learning_tasks(
    include_archived: bool = Query(default=False),
    learning_plan_id: str | None = Query(default=None),
    state: str | None = Query(default=None),
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[list[LearningTaskView]]:
    return ok([
        learning_task_view(item)
        for item in store.list_learning_tasks(
            include_archived=include_archived,
            learning_plan_id=learning_plan_id,
            state=state,
        )
    ])


@admin_router.post("/tasks", response_model=StandardResponse[LearningTaskView])
def create_learning_task(
    request: LearningTaskCreateRequest,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[LearningTaskView]:
    record = LearningTask(
        learning_task_id=request.learning_task_id or _new_learning_task_id(),
        status=LearningRecordStatus.ACTIVE,
        source_session_id=request.source_session_id,
        source_artifact_id=request.source_artifact_id,
        evidence_refs=request.evidence_refs,
        created_at=_placeholder_time(),
        updated_at=_placeholder_time(),
        title=request.title,
        learning_plan_id=request.learning_plan_id,
        description=request.description,
        task_type=request.task_type,
        priority=request.priority,
        state=request.state,
        skill_tags=request.skill_tags,
        estimated_minutes=request.estimated_minutes,
        planned_start_date=request.planned_start_date,
        due_date=request.due_date,
        completed_at=request.completed_at,
        resource_refs=request.resource_refs,
        question_refs=request.question_refs,
        note_refs=request.note_refs,
        output_artifact_id=request.output_artifact_id,
        success_criteria=request.success_criteria,
        progress_notes=request.progress_notes,
    )
    return ok(learning_task_view(store.save_learning_task(record)))


@router.get("/tasks/{learning_task_id}", response_model=StandardResponse[LearningTaskView])
def get_learning_task(
    learning_task_id: str,
    include_archived: bool = Query(default=False),
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[LearningTaskView]:
    record = _require_visible(
        store.get_learning_task(learning_task_id),
        include_archived=include_archived,
        record_type="LearningTask",
        record_id=learning_task_id,
    )
    return ok(learning_task_view(record))


@admin_router.patch("/tasks/{learning_task_id}", response_model=StandardResponse[LearningTaskView])
def update_learning_task(
    learning_task_id: str,
    request: LearningTaskUpdateRequest,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[LearningTaskView]:
    _require_visible(
        store.get_learning_task(learning_task_id),
        include_archived=False,
        record_type="LearningTask",
        record_id=learning_task_id,
    )
    return ok(learning_task_view(store.update_learning_task(learning_task_id, updates=_updates(request))))


@admin_router.post("/tasks/{learning_task_id}/state", response_model=StandardResponse[LearningTaskView])
def update_learning_task_state(
    learning_task_id: str,
    request: LearningTaskStateUpdateRequest,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[LearningTaskView]:
    _require_visible(
        store.get_learning_task(learning_task_id),
        include_archived=False,
        record_type="LearningTask",
        record_id=learning_task_id,
    )
    record = store.update_task_state(learning_task_id, state=request.state, completed_at=request.completed_at)
    return ok(learning_task_view(record))


@admin_router.post("/tasks/{learning_task_id}/complete", response_model=StandardResponse[LearningTaskView])
def complete_learning_task(
    learning_task_id: str,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[LearningTaskView]:
    _require_visible(
        store.get_learning_task(learning_task_id),
        include_archived=False,
        record_type="LearningTask",
        record_id=learning_task_id,
    )
    return ok(learning_task_view(store.update_task_state(learning_task_id, state="done")))


@admin_router.post("/tasks/{learning_task_id}/archive", response_model=StandardResponse[LearningTaskView])
def archive_learning_task(
    learning_task_id: str,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[LearningTaskView]:
    record = store.archive_learning_task(learning_task_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"LearningTask not found: {learning_task_id}")
    return ok(learning_task_view(record))


@router.get("/checkins", response_model=StandardResponse[list[ProgressCheckinView]])
def list_progress_checkins(
    include_archived: bool = Query(default=False),
    learning_plan_id: str | None = Query(default=None),
    learning_task_id: str | None = Query(default=None),
    progress_state: str | None = Query(default=None),
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[list[ProgressCheckinView]]:
    return ok([
        progress_checkin_view(item)
        for item in store.list_progress_checkins(
            include_archived=include_archived,
            learning_plan_id=learning_plan_id,
            learning_task_id=learning_task_id,
            progress_state=progress_state,
        )
    ])


@admin_router.post("/checkins", response_model=StandardResponse[ProgressCheckinView])
def create_progress_checkin(
    request: ProgressCheckinCreateRequest,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[ProgressCheckinView]:
    record = ProgressCheckin(
        checkin_id=request.checkin_id or _new_checkin_id(),
        status=LearningRecordStatus.ACTIVE,
        source_session_id=request.source_session_id,
        source_artifact_id=request.source_artifact_id,
        evidence_refs=request.evidence_refs,
        created_at=_placeholder_time(),
        updated_at=_placeholder_time(),
        learning_plan_id=request.learning_plan_id,
        learning_task_id=request.learning_task_id,
        checkin_date=request.checkin_date,
        minutes_spent=request.minutes_spent,
        progress_state=request.progress_state,
        summary=request.summary,
        blockers=request.blockers,
        confidence=request.confidence,
        next_action=request.next_action,
        note_refs=request.note_refs,
    )
    return ok(progress_checkin_view(store.append_progress_checkin(record)))


@router.get("/checkins/{checkin_id}", response_model=StandardResponse[ProgressCheckinView])
def get_progress_checkin(
    checkin_id: str,
    include_archived: bool = Query(default=False),
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[ProgressCheckinView]:
    record = _require_visible(
        store.get_progress_checkin(checkin_id),
        include_archived=include_archived,
        record_type="ProgressCheckin",
        record_id=checkin_id,
    )
    return ok(progress_checkin_view(record))


@admin_router.patch("/checkins/{checkin_id}", response_model=StandardResponse[ProgressCheckinView])
def update_progress_checkin(
    checkin_id: str,
    request: ProgressCheckinUpdateRequest,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[ProgressCheckinView]:
    _require_visible(
        store.get_progress_checkin(checkin_id),
        include_archived=False,
        record_type="ProgressCheckin",
        record_id=checkin_id,
    )
    return ok(progress_checkin_view(store.update_progress_checkin(checkin_id, updates=_updates(request))))


@admin_router.post("/checkins/{checkin_id}/archive", response_model=StandardResponse[ProgressCheckinView])
def archive_progress_checkin(
    checkin_id: str,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[ProgressCheckinView]:
    record = store.archive_progress_checkin(checkin_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"ProgressCheckin not found: {checkin_id}")
    return ok(progress_checkin_view(record))


@router.get("/weaknesses", response_model=StandardResponse[list[WeaknessTrackerView]])
def list_weakness_trackers(
    include_archived: bool = Query(default=False),
    state: str | None = Query(default=None),
    target_application_id: str | None = Query(default=None),
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[list[WeaknessTrackerView]]:
    return ok([
        weakness_tracker_view(item)
        for item in store.list_weakness_trackers(
            include_archived=include_archived,
            state=state,
            target_application_id=target_application_id,
        )
    ])


@admin_router.post("/weaknesses", response_model=StandardResponse[WeaknessTrackerView])
def create_weakness_tracker(
    request: WeaknessTrackerCreateRequest,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[WeaknessTrackerView]:
    record = WeaknessTracker(
        weakness_id=request.weakness_id or _new_weakness_id(),
        status=LearningRecordStatus.ACTIVE,
        source_session_id=request.source_session_id,
        source_artifact_id=request.source_artifact_id,
        evidence_refs=request.evidence_refs,
        created_at=_placeholder_time(),
        updated_at=_placeholder_time(),
        title=request.title,
        description=request.description,
        weakness_type=request.weakness_type,
        severity=request.severity,
        state=request.state,
        skill_tags=request.skill_tags,
        target_application_ids=request.target_application_ids,
        source_report_ids=request.source_report_ids,
        related_task_ids=request.related_task_ids,
        related_note_ids=request.related_note_ids,
        last_observed_at=request.last_observed_at,
        resolved_at=request.resolved_at,
        resolution_summary=request.resolution_summary,
    )
    return ok(weakness_tracker_view(store.save_weakness_tracker(record)))


@router.get("/weaknesses/{weakness_id}", response_model=StandardResponse[WeaknessTrackerView])
def get_weakness_tracker(
    weakness_id: str,
    include_archived: bool = Query(default=False),
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[WeaknessTrackerView]:
    record = _require_visible(
        store.get_weakness_tracker(weakness_id),
        include_archived=include_archived,
        record_type="WeaknessTracker",
        record_id=weakness_id,
    )
    return ok(weakness_tracker_view(record))


@admin_router.patch("/weaknesses/{weakness_id}", response_model=StandardResponse[WeaknessTrackerView])
def update_weakness_tracker(
    weakness_id: str,
    request: WeaknessTrackerUpdateRequest,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[WeaknessTrackerView]:
    _require_visible(
        store.get_weakness_tracker(weakness_id),
        include_archived=False,
        record_type="WeaknessTracker",
        record_id=weakness_id,
    )
    return ok(weakness_tracker_view(store.update_weakness_tracker(weakness_id, updates=_updates(request))))


@admin_router.post("/weaknesses/{weakness_id}/archive", response_model=StandardResponse[WeaknessTrackerView])
def archive_weakness_tracker(
    weakness_id: str,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[WeaknessTrackerView]:
    record = store.archive_weakness_tracker(weakness_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"WeaknessTracker not found: {weakness_id}")
    return ok(weakness_tracker_view(record))


@router.get("/reviews", response_model=StandardResponse[list[ReviewScheduleView]])
def list_review_schedules(
    include_archived: bool = Query(default=False),
    learning_plan_id: str | None = Query(default=None),
    learning_task_id: str | None = Query(default=None),
    weakness_id: str | None = Query(default=None),
    state: str | None = Query(default=None),
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[list[ReviewScheduleView]]:
    return ok([
        review_schedule_view(item)
        for item in store.list_review_schedules(
            include_archived=include_archived,
            learning_plan_id=learning_plan_id,
            learning_task_id=learning_task_id,
            weakness_id=weakness_id,
            state=state,
        )
    ])


@admin_router.post("/reviews", response_model=StandardResponse[ReviewScheduleView])
def create_review_schedule(
    request: ReviewScheduleCreateRequest,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[ReviewScheduleView]:
    record = ReviewSchedule(
        review_schedule_id=request.review_schedule_id or _new_review_schedule_id(),
        status=LearningRecordStatus.ACTIVE,
        source_session_id=request.source_session_id,
        source_artifact_id=request.source_artifact_id,
        evidence_refs=request.evidence_refs,
        created_at=_placeholder_time(),
        updated_at=_placeholder_time(),
        title=request.title,
        learning_plan_id=request.learning_plan_id,
        learning_task_id=request.learning_task_id,
        weakness_id=request.weakness_id,
        review_type=request.review_type,
        review_at=request.review_at,
        interval_days=request.interval_days,
        state=request.state,
        resource_refs=request.resource_refs,
        question_refs=request.question_refs,
        note_refs=request.note_refs,
        last_reviewed_at=request.last_reviewed_at,
        next_review_at=request.next_review_at,
        summary=request.summary,
    )
    return ok(review_schedule_view(store.save_review_schedule(record)))


@router.get("/reviews/{review_schedule_id}", response_model=StandardResponse[ReviewScheduleView])
def get_review_schedule(
    review_schedule_id: str,
    include_archived: bool = Query(default=False),
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[ReviewScheduleView]:
    record = _require_visible(
        store.get_review_schedule(review_schedule_id),
        include_archived=include_archived,
        record_type="ReviewSchedule",
        record_id=review_schedule_id,
    )
    return ok(review_schedule_view(record))


@admin_router.patch("/reviews/{review_schedule_id}", response_model=StandardResponse[ReviewScheduleView])
def update_review_schedule(
    review_schedule_id: str,
    request: ReviewScheduleUpdateRequest,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[ReviewScheduleView]:
    _require_visible(
        store.get_review_schedule(review_schedule_id),
        include_archived=False,
        record_type="ReviewSchedule",
        record_id=review_schedule_id,
    )
    return ok(review_schedule_view(store.update_review_schedule(review_schedule_id, updates=_updates(request))))


@admin_router.post("/reviews/{review_schedule_id}/archive", response_model=StandardResponse[ReviewScheduleView])
def archive_review_schedule(
    review_schedule_id: str,
    store: LearningStore = Depends(get_learning_store),
) -> StandardResponse[ReviewScheduleView]:
    record = store.archive_review_schedule(review_schedule_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ReviewSchedule not found: {review_schedule_id}",
        )
    return ok(review_schedule_view(record))


def _require_visible(
    record: _RecordT | None,
    *,
    include_archived: bool,
    record_type: str,
    record_id: str,
) -> _RecordT:
    if record is None or (record.status == LearningRecordStatus.ARCHIVED and not include_archived):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{record_type} not found: {record_id}",
        )
    return record


def _updates(request: Any) -> dict[str, object]:
    if not hasattr(request, "model_dump"):
        raise ValidationError("Learning update payload is invalid.")
    updates = cast(dict[str, object], request.model_dump(exclude_unset=True))
    if not updates:
        raise ValidationError("Learning update must include at least one editable field.")
    return updates


def _new_learning_plan_id() -> str:
    return f"learning_plan_{uuid4().hex}"


def _new_learning_task_id() -> str:
    return f"learning_task_{uuid4().hex}"


def _new_checkin_id() -> str:
    return f"checkin_{uuid4().hex}"


def _new_weakness_id() -> str:
    return f"weakness_{uuid4().hex}"


def _new_review_schedule_id() -> str:
    return f"review_{uuid4().hex}"


def _placeholder_time() -> datetime:
    return app_now()

