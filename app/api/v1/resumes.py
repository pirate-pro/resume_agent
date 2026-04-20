from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.application.dto.schemas import ResumeUploadResponse
from app.core.db.repositories.candidate_repository import CandidateRepository
from app.core.db.session import get_db
from app.core.middleware.error_handler import WorkflowError
from app.infra.storage.workspace import WorkspaceManager

router = APIRouter()


@router.post("/upload", response_model=ResumeUploadResponse)
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ResumeUploadResponse:
    if not file.filename:
        raise WorkflowError("file_name_missing", status_code=422)
    suffix = file.filename.rsplit(".", maxsplit=1)[-1].lower()
    if suffix not in {"pdf", "docx"}:
        raise WorkflowError("unsupported_file_type", status_code=422)

    repo = CandidateRepository(db)
    workspace = WorkspaceManager()
    candidate = repo.create_candidate()
    file_bytes = await file.read()
    temp_path = workspace.save_upload("temp", file.filename, file_bytes)
    resume = repo.create_resume(candidate.id, file.filename, suffix, temp_path)
    final_path = workspace.save_upload(resume.id, file.filename, file_bytes)
    resume.file_path = final_path
    db.add(resume)
    db.commit()
    return ResumeUploadResponse(
        candidate_id=candidate.id,
        resume_id=resume.id,
        file_name=resume.file_name,
        file_path=resume.file_path,
    )
