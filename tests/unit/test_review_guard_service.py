from app.domain.models.candidate import CandidateProfile, ExperienceFact, ProjectFact, SkillFact
from app.domain.models.matching import GapAnalysis, MatchResult, MatchScoreCard
from app.domain.models.optimization import ChangeItem, OptimizationDraft, RiskNote
from app.domain.services.review_guard_service import ReviewGuardService


def _candidate_profile() -> CandidateProfile:
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


def test_review_guard_blocks_missing_skill_written_as_fact() -> None:
    service = ReviewGuardService()
    match_result = MatchResult(
        job_posting_id="job-1",
        company_name="Blue River Tech",
        job_title="Senior FastAPI Engineer",
        city="Shanghai",
        score_card=MatchScoreCard(0.9, 1.0, 1.0, 0.8, 1.0, 1.0),
        explanation={"matched_required_skills": ["python"], "matched_optional_skills": []},
        gap=GapAnalysis(missing_required_skills=["postgresql"]),
        rank_no=1,
    )
    draft = OptimizationDraft(
        optimized_resume_markdown="# 王小明\n\n## 核心技能\n- Python\n- PostgreSQL\n\n## 待补强方向\n- PostgreSQL：待补强",
        change_summary=[ChangeItem("核心技能", "重排", "突出技能")],
        risk_notes=[RiskNote("medium", "缺少 PostgreSQL")],
    )

    report = service.review(_candidate_profile(), match_result, draft)

    assert report.allow_delivery is False
    assert any("postgresql" in issue.message.lower() for issue in report.issues)
