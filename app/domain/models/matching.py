from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class MatchScoreCard:
    overall_score: float
    skill_score: float
    experience_score: float
    project_score: float
    education_score: float
    preference_score: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class GapAnalysis:
    missing_required_skills: list[str] = field(default_factory=list)
    missing_optional_skills: list[str] = field(default_factory=list)
    experience_gap: str | None = None
    education_gap: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class MatchResult:
    job_posting_id: str
    company_name: str
    job_title: str
    city: str | None
    score_card: MatchScoreCard
    explanation: dict
    gap: GapAnalysis
    rank_no: int

    def to_dict(self) -> dict:
        return {
            "job_posting_id": self.job_posting_id,
            "company_name": self.company_name,
            "job_title": self.job_title,
            "city": self.city,
            "score_card": self.score_card.to_dict(),
            "explanation": self.explanation,
            "gap": self.gap.to_dict(),
            "rank_no": self.rank_no,
        }
