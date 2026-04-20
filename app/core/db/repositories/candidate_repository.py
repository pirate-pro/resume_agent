from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db.models.entities import (
    Candidate,
    CandidateExperience,
    CandidateProfile,
    CandidateProject,
    CandidateResume,
    CandidateResumeBlock,
    CandidateSkill,
)
from app.domain.models.candidate import CandidateProfile as CandidateProfileModel
from app.domain.models.resume import ResumeBlock


class CandidateRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_candidate(self, name: str | None = None) -> Candidate:
        candidate = Candidate(name=name)
        self._db.add(candidate)
        self._db.flush()
        return candidate

    def get_candidate(self, candidate_id: str) -> Candidate:
        return self._db.get(Candidate, candidate_id)

    def create_resume(self, candidate_id: str, file_name: str, file_type: str, file_path: str) -> CandidateResume:
        resume = CandidateResume(
            candidate_id=candidate_id,
            file_name=file_name,
            file_type=file_type,
            file_path=file_path,
        )
        self._db.add(resume)
        self._db.flush()
        return resume

    def get_resume(self, resume_id: str) -> CandidateResume:
        return self._db.get(CandidateResume, resume_id)

    def replace_blocks(self, resume_id: str, blocks: list[ResumeBlock]) -> list[CandidateResumeBlock]:
        self._db.execute(delete(CandidateResumeBlock).where(CandidateResumeBlock.resume_id == resume_id))
        rows = [
            CandidateResumeBlock(
                resume_id=resume_id,
                page_no=block.page_no,
                block_type=block.block_type,
                block_index=block.block_index,
                raw_text=block.raw_text,
                normalized_text=block.normalized_text,
                bbox_json=block.bbox_json,
                confidence=block.confidence,
            )
            for block in blocks
        ]
        self._db.add_all(rows)
        self._db.flush()
        return rows

    def update_resume_status(self, resume_id: str, status: str) -> None:
        resume = self.get_resume(resume_id)
        resume.parsed_status = status
        self._db.add(resume)
        self._db.flush()

    def upsert_profile(self, profile: CandidateProfileModel) -> CandidateProfile:
        existing = self._db.scalar(
            select(CandidateProfile).where(CandidateProfile.resume_id == profile.resume_id)
        )
        if existing is None:
            existing = CandidateProfile(
                candidate_id=profile.candidate_id,
                resume_id=profile.resume_id,
                profile_json=profile.to_dict(),
                confidence_json={"profile": 0.92},
            )
        else:
            existing.profile_json = profile.to_dict()
            existing.confidence_json = {"profile": 0.92}
        self._db.add(existing)

        self._db.execute(delete(CandidateSkill).where(CandidateSkill.candidate_id == profile.candidate_id))
        self._db.execute(
            delete(CandidateExperience).where(CandidateExperience.candidate_id == profile.candidate_id)
        )
        self._db.execute(delete(CandidateProject).where(CandidateProject.candidate_id == profile.candidate_id))

        skill_rows = [
            CandidateSkill(
                candidate_id=profile.candidate_id,
                skill_name_raw=skill.raw_name,
                skill_name_norm=skill.normalized_name,
                skill_category=skill.category,
                evidence_text=skill.evidence_text,
                confidence=skill.confidence,
            )
            for skill in profile.skills
        ]
        exp_rows = [
            CandidateExperience(
                candidate_id=profile.candidate_id,
                company_name=experience.company_name,
                job_title=experience.job_title,
                start_date=experience.start_date,
                end_date=experience.end_date,
                duration_months=experience.duration_months,
                description=experience.description,
                evidence_block_id=None,
            )
            for experience in profile.experiences
        ]
        project_rows = [
            CandidateProject(
                candidate_id=profile.candidate_id,
                project_name=project.project_name,
                role_name=project.role_name,
                tech_stack_json=project.tech_stack,
                domain_tags_json=project.domain_tags,
                result_text=project.result_text,
                evidence_block_id=None,
            )
            for project in profile.projects
        ]
        self._db.add_all(skill_rows + exp_rows + project_rows)
        self._db.flush()
        return existing

    def get_profile(self, resume_id: str) -> CandidateProfile | None:
        return self._db.scalar(select(CandidateProfile).where(CandidateProfile.resume_id == resume_id))
