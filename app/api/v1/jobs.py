from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.application.dto.schemas import JobPostingResponse
from app.core.db.repositories.job_repository import JobRepository
from app.core.db.session import get_db

router = APIRouter()


@router.get("", response_model=list[JobPostingResponse])
def list_jobs(db: Session = Depends(get_db)) -> list[JobPostingResponse]:
    repo = JobRepository(db)
    return [
        JobPostingResponse(
            id=job.id,
            company_name=job.company.name,
            title=job.job_title,
            city=job.city,
            education_requirement=job.education_requirement,
            experience_min_years=job.experience_min_years,
            skills=[
                {
                    "name": requirement.skill_name_norm,
                    "is_required": requirement.is_required,
                    "weight": requirement.weight,
                }
                for requirement in job.skill_requirements
            ],
        )
        for job in repo.list_jobs()
    ]
