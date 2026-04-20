from app.domain.models.candidate import CandidateProfile, ExperienceFact, ProjectFact, SkillFact
from app.domain.models.matching import GapAnalysis, MatchResult, MatchScoreCard
from app.domain.models.optimization import OptimizationDraft
from app.domain.services.resume_optimization_service import ResumeOptimizationService
from app.domain.services.review_guard_service import ReviewGuardService


class FakeLLMClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def is_available(self) -> bool:
        return True

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        assert system_prompt
        assert user_prompt
        return self._payload


class FakeCompany:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeSkillRequirement:
    def __init__(self, name: str, is_required: bool, weight: float) -> None:
        self.skill_name_norm = name
        self.is_required = is_required
        self.weight = weight


class FakeJob:
    def __init__(self) -> None:
        self.id = "job-1"
        self.job_title = "Senior FastAPI Engineer"
        self.city = "Shanghai"
        self.education_requirement = "本科"
        self.experience_min_years = 3
        self.job_description_clean = "Build workflow APIs."
        self.company = FakeCompany("Blue River Tech")
        self.skill_requirements = [
            FakeSkillRequirement("python", True, 1.0),
            FakeSkillRequirement("fastapi", True, 1.0),
            FakeSkillRequirement("postgresql", True, 0.8),
        ]


def build_candidate_profile() -> CandidateProfile:
    return CandidateProfile(
        candidate_id="candidate-1",
        resume_id="resume-1",
        name="王小明",
        email="wang@example.com",
        phone="13800000000",
        summary="Python 后端工程师",
        target_city="Shanghai",
        education_level="本科",
        total_experience_months=60,
        skills=[
            SkillFact("Python", "python", "core", "Skills: Python"),
            SkillFact("FastAPI", "fastapi", "core", "Skills: FastAPI"),
        ],
        experiences=[
            ExperienceFact("Blue River Tech", "Backend Engineer", "2021-01", "2024-12", 48, "Built APIs", "exp")
        ],
        projects=[ProjectFact("Resume Match", "Lead", ["python", "fastapi"], ["resume"], "Improved", "project")],
    )


def build_match_result() -> MatchResult:
    return MatchResult(
        job_posting_id="job-1",
        company_name="Blue River Tech",
        job_title="Senior FastAPI Engineer",
        city="Shanghai",
        score_card=MatchScoreCard(0.9, 1.0, 1.0, 0.8, 1.0, 1.0),
        explanation={"matched_required_skills": ["python", "fastapi"], "matched_optional_skills": []},
        gap=GapAnalysis(missing_required_skills=["postgresql"]),
        rank_no=1,
    )


def test_resume_optimization_service_uses_llm_payload() -> None:
    service = ResumeOptimizationService(
        llm_client=FakeLLMClient(
            {
                "optimized_resume_markdown": "# 王小明\n\n## 岗位对齐摘要\n聚焦 FastAPI。\n\n## 核心技能\n- python\n- fastapi\n\n## 重点经历\n- Blue River Tech | Backend Engineer | Built APIs\n\n## 代表项目\n- Resume Match | Lead | python, fastapi | Improved\n\n## 待补强方向\n- postgresql：待补强",
                "change_summary": [
                    {"section": "核心技能", "action": "重排", "reason": "突出岗位相关能力"},
                ],
                "risk_notes": [{"level": "medium", "message": "postgresql 仍缺证据"}],
            }
        )
    )

    draft = service.create_targeted_resume(build_candidate_profile(), FakeJob(), build_match_result())

    assert "聚焦 FastAPI" in draft.optimized_resume_markdown
    assert draft.change_summary[0].section == "核心技能"
    assert draft.risk_notes[0].level == "medium"


def test_review_guard_service_combines_llm_and_deterministic_issues() -> None:
    service = ReviewGuardService(
        llm_client=FakeLLMClient(
            {
                "issues": [
                    {"level": "high", "message": "postgresql 被误写为已掌握核心技能"},
                ]
            }
        )
    )
    draft = OptimizationDraft(
        optimized_resume_markdown="# 王小明\n\n## 核心技能\n- Python\n- PostgreSQL\n\n## 待补强方向\n- PostgreSQL：待补强",
        change_summary=[],
        risk_notes=[],
    )

    report = service.review(build_candidate_profile(), build_match_result(), draft)

    assert report.allow_delivery is False
    assert any(issue.level == "high" for issue in report.issues)
