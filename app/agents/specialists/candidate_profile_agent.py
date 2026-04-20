from app.domain.models.candidate import CandidateProfile
from app.domain.models.resume import ResumeParseResult
from app.domain.services.candidate_profile_service import CandidateProfileService


class CandidateProfileAgent:
    def __init__(self, service: CandidateProfileService | None = None) -> None:
        self._service = service or CandidateProfileService()

    def run(self, candidate_id: str, resume_id: str, parse_result: ResumeParseResult) -> CandidateProfile:
        return self._service.build(candidate_id, resume_id, parse_result)
