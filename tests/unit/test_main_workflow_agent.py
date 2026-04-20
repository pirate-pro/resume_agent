from pathlib import Path

from app.agents.main_agent import MainWorkflowAgent
from app.agents.runtime import AgentResult, AgentToolTrace
from app.domain.models.candidate import CandidateProfile, ExperienceFact, ProjectFact, SkillFact
from app.domain.models.matching import GapAnalysis, MatchResult, MatchScoreCard
from app.domain.models.optimization import ChangeItem, OptimizationDraft, RiskNote
from app.domain.models.review import ReviewIssue, ReviewReport


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


class FakeOptimizeAgent:
    def run(self, context) -> AgentResult:
        draft = OptimizationDraft(
            optimized_resume_markdown="# 王小明\n\n## 核心技能\n- Python\n\n## 待补强方向\n- postgresql",
            change_summary=[ChangeItem(section="核心技能", action="重排", reason="提升匹配可读性")],
            risk_notes=[RiskNote(level="medium", message="postgresql 缺少直接证据")],
        )
        return AgentResult(
            status="completed",
            output=draft,
            observations=["sub optimize completed"],
            tool_traces=[AgentToolTrace(tool_name="opt_tool", status="completed")],
            confidence=0.86,
            next_stage_hint="review",
            metadata={"mode": "reflection", "context_id": context.context_id},
        )


class FakeReviewAgent:
    def run(self, context) -> AgentResult:
        report = ReviewReport(
            allow_delivery=False,
            risk_level="high",
            issues=[ReviewIssue(level="high", message="缺口技能被写入核心技能")],
        )
        return AgentResult(
            status="blocked",
            output=report,
            observations=["sub review blocked"],
            tool_traces=[AgentToolTrace(tool_name="review_tool", status="completed")],
            confidence=0.9,
            next_stage_hint="blocked",
            metadata={"mode": "react", "context_id": context.context_id},
        )


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
        skills=[SkillFact("Python", "python", "core", "Skills: Python")],
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
        explanation={"matched_required_skills": ["python"], "matched_optional_skills": []},
        gap=GapAnalysis(missing_required_skills=["postgresql"]),
        rank_no=1,
    )


def test_main_agent_plan_and_delegate_optimization() -> None:
    main_agent = MainWorkflowAgent(
        optimize_agent=FakeOptimizeAgent(),  # type: ignore[arg-type]
        review_agent=FakeReviewAgent(),  # type: ignore[arg-type]
    )
    result = main_agent.run_optimization(
        task_id="task-1",
        attempt=0,
        profile=build_candidate_profile(),
        target_job=FakeJob(),
        match_result=build_match_result(),
    )

    assert result.status == "completed"
    assert result.metadata["mode"] == "plan_and_solve"
    assert result.metadata["delegated_agent"]["name"] == "ResumeOptimizeAgent"
    contexts = result.metadata["contexts"]
    assert len(contexts) == 2
    assert any(frame["agent_name"] == "MainWorkflowAgent" for frame in contexts.values())
    assert any(frame["agent_name"] == "ResumeOptimizeAgent" for frame in contexts.values())
    run_trace = result.metadata["run_trace"]
    assert Path(run_trace["manifest_path"]).exists()
    assert Path(run_trace["contexts_path"]).exists()
    assert Path(run_trace["timeline_path"]).exists()
    assert Path(run_trace["summary_path"]).exists()


def test_main_agent_plan_and_delegate_review() -> None:
    main_agent = MainWorkflowAgent(
        optimize_agent=FakeOptimizeAgent(),  # type: ignore[arg-type]
        review_agent=FakeReviewAgent(),  # type: ignore[arg-type]
    )
    draft = OptimizationDraft(
        optimized_resume_markdown="# 王小明\n\n## 核心技能\n- Python\n- PostgreSQL",
        change_summary=[],
        risk_notes=[],
    )

    result = main_agent.run_review(
        task_id="task-1",
        attempt=1,
        profile=build_candidate_profile(),
        target_job=FakeJob(),
        match_result=build_match_result(),
        draft=draft,
    )

    assert result.status == "blocked"
    assert result.metadata["mode"] == "plan_and_solve"
    assert result.metadata["delegated_agent"]["name"] == "ReviewGuardAgent"
    assert result.output.allow_delivery is False
    run_trace = result.metadata["run_trace"]
    assert Path(run_trace["manifest_path"]).exists()
    assert Path(run_trace["contexts_path"]).exists()
    assert Path(run_trace["timeline_path"]).exists()
    assert Path(run_trace["summary_path"]).exists()
