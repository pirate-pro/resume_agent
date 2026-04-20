from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents.orchestrator.orchestrator import WorkflowOrchestrator
from app.application.dto.schemas import OptimizationTaskCreateRequest, OptimizationTaskResponse, TaskAcceptedResponse
from app.core.config.settings import get_settings
from app.core.db.repositories.candidate_repository import CandidateRepository
from app.core.db.repositories.task_repository import TaskRepository
from app.core.db.session import get_db
from app.core.middleware.error_handler import WorkflowError

router = APIRouter()


@router.post("", response_model=TaskAcceptedResponse)
def create_optimization_task(
    request: OptimizationTaskCreateRequest,
    db: Session = Depends(get_db),
) -> TaskAcceptedResponse:
    candidate_repo = CandidateRepository(db)
    task_repo = TaskRepository(db)
    settings = get_settings()
    resume = candidate_repo.get_resume(request.resume_id)
    if resume is None:
        raise WorkflowError("resume_not_found", status_code=404)
    task = task_repo.create_optimization_task(
        candidate_id=resume.candidate_id,
        resume_id=resume.id,
        target_job_id=request.target_job_id,
        mode=request.mode,
        max_retries=settings.task_max_retries,
        stage_timeout_sec=settings.task_stage_timeout_sec,
    )
    task_repo.log_event(task.id, "task.enqueued", {"stage": task.stage, "task_status": task.status})
    db.commit()
    return TaskAcceptedResponse(
        task_id=task.id,
        task_status=task.status,
        stage=task.stage,
        failure_reason=task.failure_reason,
        retry_count=task.retry_count,
        max_retries=task.max_retries,
        stage_timeout_sec=task.stage_timeout_sec,
    )


@router.get("/{task_id}", response_model=OptimizationTaskResponse)
def get_optimization_task(task_id: str, db: Session = Depends(get_db)) -> OptimizationTaskResponse:
    orchestrator = WorkflowOrchestrator(db)
    snapshot = orchestrator.get_optimization_snapshot(task_id)
    return OptimizationTaskResponse.model_validate(snapshot)
