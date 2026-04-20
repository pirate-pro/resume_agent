from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class SkillFact:
    raw_name: str
    normalized_name: str
    category: str
    evidence_text: str
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ExperienceFact:
    company_name: str
    job_title: str
    start_date: str | None
    end_date: str | None
    duration_months: int
    description: str
    evidence_text: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ProjectFact:
    project_name: str
    role_name: str
    tech_stack: list[str]
    domain_tags: list[str]
    result_text: str
    evidence_text: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class CandidateProfile:
    candidate_id: str
    resume_id: str
    name: str
    email: str | None
    phone: str | None
    summary: str
    target_city: str | None
    education_level: str | None
    total_experience_months: int
    skills: list[SkillFact] = field(default_factory=list)
    experiences: list[ExperienceFact] = field(default_factory=list)
    projects: list[ProjectFact] = field(default_factory=list)
    evidence_summary: dict = field(default_factory=dict)
    risk_items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "resume_id": self.resume_id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "summary": self.summary,
            "target_city": self.target_city,
            "education_level": self.education_level,
            "total_experience_months": self.total_experience_months,
            "skills": [skill.to_dict() for skill in self.skills],
            "experiences": [experience.to_dict() for experience in self.experiences],
            "projects": [project.to_dict() for project in self.projects],
            "evidence_summary": self.evidence_summary,
            "risk_items": self.risk_items,
        }
