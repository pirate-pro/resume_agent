from app.domain.models.resume import ResumeParseResult
from app.domain.services.resume_parsing_service import ResumeParsingService


class ResumeParseAgent:
    def __init__(self, service: ResumeParsingService | None = None) -> None:
        self._service = service or ResumeParsingService()

    def run(self, file_path: str) -> ResumeParseResult:
        return self._service.parse(file_path)
