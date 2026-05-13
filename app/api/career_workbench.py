"""Career workbench HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_career_product_store, get_learning_store, get_note_store
from app.api.presenters import career_application_workbench_view, career_workbench_list_view
from app.api.responses import ok
from app.career.store import CareerProductStore
from app.career.workbench import CareerWorkbenchService
from app.learning.store import LearningStore
from app.notes.store import NoteStore
from app.schemas.career_workbench import CareerApplicationWorkbenchView, CareerWorkbenchListView
from app.schemas.common import StandardResponse

__all__ = ["router"]

router = APIRouter(prefix="/api/career/workbench", tags=["career-workbench"])


def _get_career_workbench_service(
    career_store: CareerProductStore = Depends(get_career_product_store),
    note_store: NoteStore = Depends(get_note_store),
    learning_store: LearningStore = Depends(get_learning_store),
) -> CareerWorkbenchService:
    return CareerWorkbenchService(
        career_store=career_store,
        note_store=note_store,
        learning_store=learning_store,
    )


@router.get("", response_model=StandardResponse[CareerWorkbenchListView])
def list_career_workbench(
    include_archived: bool = Query(default=False),
    service: CareerWorkbenchService = Depends(_get_career_workbench_service),
) -> StandardResponse[CareerWorkbenchListView]:
    return ok(career_workbench_list_view(service.list_workbench(include_archived=include_archived)))


@router.get("/applications/{application_id}", response_model=StandardResponse[CareerApplicationWorkbenchView])
def get_career_application_workbench(
    application_id: str,
    include_archived: bool = Query(default=False),
    service: CareerWorkbenchService = Depends(_get_career_workbench_service),
) -> StandardResponse[CareerApplicationWorkbenchView]:
    workbench = service.get_application_workbench(application_id, include_archived=include_archived)
    if workbench is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CareerApplication not found: {application_id}",
        )
    return ok(career_application_workbench_view(workbench))
