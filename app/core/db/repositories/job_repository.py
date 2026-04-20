from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.db.models.entities import Company, JobPosting, JobSkillRequirement


class JobRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_jobs(self) -> list[JobPosting]:
        stmt = (
            select(JobPosting)
            .options(selectinload(JobPosting.skill_requirements), selectinload(JobPosting.company))
            .where(JobPosting.status == "active")
            .order_by(JobPosting.job_title)
        )
        return list(self._db.scalars(stmt))

    def get_job(self, job_id: str) -> JobPosting:
        stmt = (
            select(JobPosting)
            .options(selectinload(JobPosting.skill_requirements), selectinload(JobPosting.company))
            .where(JobPosting.id == job_id)
        )
        return self._db.scalar(stmt)

    def count_jobs(self) -> int:
        return len(self.list_jobs())

    def create_company(
        self,
        name: str,
        *,
        industry: str,
        city: str,
        description: str,
    ) -> Company:
        company = Company(
            name=name,
            industry=industry,
            location_city=city,
            description=description,
            source_type="seed",
        )
        self._db.add(company)
        self._db.flush()
        return company

    def create_job(
        self,
        company_id: str,
        *,
        title: str,
        city: str,
        description: str,
        education_requirement: str,
        experience_min_years: int,
        skills: list[tuple[str, bool, float]],
    ) -> JobPosting:
        job = JobPosting(
            company_id=company_id,
            job_title=title,
            job_title_norm=title.lower(),
            city=city,
            job_description_raw=description,
            job_description_clean=description,
            education_requirement=education_requirement,
            experience_min_years=experience_min_years,
            source_type="seed",
        )
        self._db.add(job)
        self._db.flush()
        skill_rows = [
            JobSkillRequirement(
                job_posting_id=job.id,
                skill_name_raw=skill,
                skill_name_norm=skill.lower(),
                is_required=is_required,
                weight=weight,
            )
            for skill, is_required, weight in skills
        ]
        self._db.add_all(skill_rows)
        self._db.flush()
        return job
