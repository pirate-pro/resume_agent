from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.domain.models.candidate import CandidateProfile
from app.domain.models.matching import MatchResult
from app.domain.models.optimization import OptimizationDraft

REQUIRED_SECTIONS = [
    "## 岗位对齐摘要",
    "## 核心技能",
    "## 重点经历",
    "## 代表项目",
    "## 待补强方向",
]


@dataclass(slots=True)
class DraftQualityIssue:
    level: str
    message: str
    blocking: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class DraftQualityReport:
    confidence: float
    issues: list[DraftQualityIssue] = field(default_factory=list)

    @property
    def blocking_issue_count(self) -> int:
        return sum(1 for issue in self.issues if issue.blocking)

    @property
    def advisory_issue_count(self) -> int:
        return sum(1 for issue in self.issues if not issue.blocking)

    def has_blocking_issues(self) -> bool:
        return self.blocking_issue_count > 0

    def to_dict(self) -> dict:
        return {
            "confidence": self.confidence,
            "blocking_issue_count": self.blocking_issue_count,
            "advisory_issue_count": self.advisory_issue_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


class DraftQualityTool:
    def inspect(
        self,
        profile: CandidateProfile,
        match_result: MatchResult,
        draft: OptimizationDraft,
        *,
        expected_job_title: str | None = None,
    ) -> DraftQualityReport:
        markdown = draft.optimized_resume_markdown.strip()
        issues: list[DraftQualityIssue] = []
        if not markdown:
            issues.append(DraftQualityIssue(level="high", message="优化稿为空", blocking=True))
            return DraftQualityReport(confidence=0.0, issues=issues)

        if profile.name and not markdown.startswith(f"# {profile.name}"):
            issues.append(DraftQualityIssue(level="medium", message="标题未使用候选人姓名", blocking=False))

        if expected_job_title and f"- 目标岗位：{expected_job_title}" not in markdown:
            issues.append(
                DraftQualityIssue(level="medium", message=f"目标岗位行缺少 {expected_job_title}", blocking=False)
            )

        for section in REQUIRED_SECTIONS:
            if section not in markdown:
                issues.append(DraftQualityIssue(level="high", message=f"缺少必要章节：{section}", blocking=True))

        gap_marker = "## 待补强方向"
        before_gap_section = markdown.split(gap_marker, maxsplit=1)[0].lower()
        for missing_skill in match_result.gap.missing_required_skills:
            if missing_skill.lower() in before_gap_section:
                issues.append(
                    DraftQualityIssue(
                        level="high",
                        message=f"缺口技能 {missing_skill} 出现在待补强方向之前",
                        blocking=True,
                    )
                )

        confidence = max(
            0.0,
            1.0 - (0.35 * sum(1 for issue in issues if issue.blocking)) - (0.1 * sum(1 for issue in issues if not issue.blocking)),
        )
        return DraftQualityReport(confidence=round(confidence, 2), issues=issues)
