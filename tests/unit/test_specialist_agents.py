from app.agents.specialists.contracts import ResumeOptimizationContext, ReviewGuardContext
from app.agents.specialists.resume_optimize_agent import ResumeOptimizeAgent
from app.agents.specialists.review_guard_agent import ReviewGuardAgent
from app.domain.models.candidate import CandidateProfile, ExperienceFact, ProjectFact, SkillFact
from app.domain.models.matching import GapAnalysis, MatchResult, MatchScoreCard
from app.domain.models.optimization import ChangeItem, OptimizationDraft, RiskNote
from app.domain.models.review import ReviewReport


class FakeCompany:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeJob:
    def __init__(self) -> None:
        self.id = "job-1"
        self.job_title = "Senior FastAPI Engineer"
        self.city = "Shanghai"
        self.education_requirement = "本科"
        self.experience_min_years = 3
        self.job_description_clean = "Build workflow APIs."
        self.company = FakeCompany("Blue River Tech")
        self.skill_requirements = []


class FakeOptimizationService:
    def __init__(self, primary: OptimizationDraft, fallback: OptimizationDraft) -> None:
        self._primary = primary
        self._fallback = fallback

    def create_targeted_resume(
        self,
        profile: CandidateProfile,
        target_job: FakeJob,
        match_result: MatchResult,
    ) -> OptimizationDraft:
        del profile, target_job, match_result
        return self._primary

    def create_rule_based_resume(
        self,
        profile: CandidateProfile,
        target_job: FakeJob,
        match_result: MatchResult,
    ) -> OptimizationDraft:
        del profile, target_job, match_result
        return self._fallback


class FakeReviewService:
    def __init__(self, report: ReviewReport) -> None:
        self._report = report

    def review(
        self,
        profile: CandidateProfile,
        match_result: MatchResult,
        draft: OptimizationDraft,
    ) -> ReviewReport:
        del profile, match_result, draft
        return self._report


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


def test_resume_optimize_agent_uses_fallback_when_primary_draft_fails_quality() -> None:
    primary = OptimizationDraft(
        optimized_resume_markdown="# 王小明\n\n## 核心技能\n- Python\n- PostgreSQL",
        change_summary=[],
        risk_notes=[],
    )
    fallback = OptimizationDraft(
        optimized_resume_markdown=(
            "# 王小明\n\n"
            "- 邮箱：wang@example.com\n"
            "- 电话：13800000000\n"
            "- 目标岗位：Senior FastAPI Engineer\n\n"
            "## 岗位对齐摘要\n聚焦 FastAPI。\n\n"
            "## 核心技能\n- Python\n- FastAPI\n\n"
            "## 重点经历\n- Blue River Tech | Backend Engineer | Built APIs\n\n"
            "## 代表项目\n- Resume Match | Lead | python, fastapi | Improved\n\n"
            "## 待补强方向\n- postgresql：待补强"
        ),
        change_summary=[ChangeItem(section="核心技能", action="重排", reason="突出岗位相关能力")],
        risk_notes=[RiskNote(level="medium", message="postgresql 仍缺证据")],
    )
    agent = ResumeOptimizeAgent(service=FakeOptimizationService(primary=primary, fallback=fallback))

    result = agent.run(
        ResumeOptimizationContext(
            profile=build_candidate_profile(),
            target_job=FakeJob(),
            match_result=build_match_result(),
            task_id="opt-task-1",
            attempt=0,
        )
    )

    assert result.status == "completed"
    assert result.metadata["selected_strategy"] == "rule_based_fallback"
    assert result.output.optimized_resume_markdown == fallback.optimized_resume_markdown
    assert any(trace.tool_name == "rule_based_resume_fallback" for trace in result.tool_traces)


def test_review_guard_agent_blocks_delivery_when_quality_policy_fails() -> None:
    draft = OptimizationDraft(
        optimized_resume_markdown=(
            "# 王小明\n\n"
            "- 邮箱：wang@example.com\n"
            "- 电话：13800000000\n"
            "- 目标岗位：Senior FastAPI Engineer\n\n"
            "## 岗位对齐摘要\n聚焦 FastAPI。\n\n"
            "## 核心技能\n- Python\n- PostgreSQL\n\n"
            "## 重点经历\n- Blue River Tech | Backend Engineer | Built APIs\n\n"
            "## 代表项目\n- Resume Match | Lead | python, fastapi | Improved\n"
        ),
        change_summary=[],
        risk_notes=[],
    )
    agent = ReviewGuardAgent(
        service=FakeReviewService(report=ReviewReport(allow_delivery=True, risk_level="low", issues=[]))
    )

    result = agent.run(
        ReviewGuardContext(
            profile=build_candidate_profile(),
            match_result=build_match_result(),
            draft=draft,
            target_job_title="Senior FastAPI Engineer",
            task_id="opt-task-1",
            attempt=0,
        )
    )

    assert result.status == "blocked"
    assert result.output.allow_delivery is False
    assert any("缺少必要章节" in issue.message for issue in result.output.issues)
    assert any("postgresql" in issue.message.lower() for issue in result.output.issues)
    assert any(trace.tool_name == "delivery_policy" for trace in result.tool_traces)
