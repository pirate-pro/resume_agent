from app.core.db.models.entities import JobPosting
from app.domain.models.candidate import CandidateProfile
from app.domain.models.matching import MatchResult
from app.domain.services.job_retrieval_service import JobRetrievalService


class JobRetrievalMatchAgent:
    def __init__(self, service: JobRetrievalService | None = None) -> None:
        self._service = service or JobRetrievalService()

    def run(self, profile: CandidateProfile, jobs: list[JobPosting], top_k: int) -> list[MatchResult]:
        return self._service.retrieve_and_rank(profile, jobs, top_k)
