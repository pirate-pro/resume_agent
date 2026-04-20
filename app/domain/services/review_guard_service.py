from __future__ import annotations

import json

from app.core.llm.client import LLMClientError, OpenAICompatibleLLMClient, get_llm_client
from app.domain.models.candidate import CandidateProfile
from app.domain.models.matching import MatchResult
from app.domain.models.optimization import OptimizationDraft
from app.domain.models.review import ReviewIssue, ReviewReport

FORBIDDEN_TOKENS = ["面相", "八字", "性别", "年龄", "籍贯", "民族", "宗教"]


class ReviewGuardService:
    def __init__(self, llm_client: OpenAICompatibleLLMClient | None = None) -> None:
        self._llm_client = llm_client if llm_client is not None else get_llm_client()

    def review(
        self,
        profile: CandidateProfile,
        match_result: MatchResult,
        draft: OptimizationDraft,
    ) -> ReviewReport:
        issues = self._deterministic_issues(profile, match_result, draft)
        if self._llm_client.is_available():
            try:
                issues.extend(self._llm_issues(profile, match_result, draft))
            except LLMClientError:
                pass
        issues = self._deduplicate_issues(issues)
        allow_delivery = not any(issue.level == "high" for issue in issues)
        risk_level = "high" if not allow_delivery else ("medium" if issues else "low")
        return ReviewReport(allow_delivery=allow_delivery, risk_level=risk_level, issues=issues)

    def _deterministic_issues(
        self,
        profile: CandidateProfile,
        match_result: MatchResult,
        draft: OptimizationDraft,
    ) -> list[ReviewIssue]:
        issues: list[ReviewIssue] = []
        markdown = draft.optimized_resume_markdown

        for token in FORBIDDEN_TOKENS:
            if token in markdown:
                issues.append(ReviewIssue(level="high", message=f"发现禁止进入主决策链的字段：{token}"))

        split_marker = "## 待补强方向"
        before_gap_section = markdown.split(split_marker)[0].lower()
        for missing_skill in match_result.gap.missing_required_skills:
            if missing_skill.lower() in before_gap_section:
                issues.append(
                    ReviewIssue(level="high", message=f"缺口技能 {missing_skill} 被写入已掌握内容，存在越界风险")
                )

        candidate_skill_set = {skill.normalized_name for skill in profile.skills}
        for line in markdown.splitlines():
            if line.startswith("- ") and "##" not in line:
                token = line[2:].split("：", maxsplit=1)[0].split(":", maxsplit=1)[0].strip().lower()
                if token and token in {"python", "fastapi", "sqlalchemy", "postgresql", "docker", "redis"}:
                    if token not in candidate_skill_set and token not in [
                        skill.lower() for skill in match_result.gap.missing_required_skills
                    ]:
                        issues.append(ReviewIssue(level="medium", message=f"技能 {token} 缺少证据支撑"))

        if not markdown.strip():
            issues.append(ReviewIssue(level="high", message="优化稿为空"))
        return issues

    def _llm_issues(
        self,
        profile: CandidateProfile,
        match_result: MatchResult,
        draft: OptimizationDraft,
    ) -> list[ReviewIssue]:
        system_prompt = (
            "You are a strict resume compliance reviewer. "
            "Use only the provided candidate evidence, match result, and draft. "
            "Return one JSON object only."
        )
        user_prompt = (
            "Review the targeted resume draft.\n"
            "Return JSON with exactly one key: issues.\n"
            "issues must be a list of objects with level and message.\n"
            "Focus on fabricated skills, evidence mismatch, prohibited hiring attributes, "
            "and contradictions between draft and source evidence.\n"
            "Use level values low, medium, high.\n\n"
            f"CandidateProfile={json.dumps(profile.to_dict(), ensure_ascii=False)}\n"
            f"MatchResult={json.dumps(match_result.to_dict(), ensure_ascii=False)}\n"
            f"OptimizationDraft={json.dumps(draft.to_dict(), ensure_ascii=False)}"
        )
        payload = self._llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        issues: list[ReviewIssue] = []
        raw_issues = payload.get("issues", [])
        if not isinstance(raw_issues, list):
            return issues
        for row in raw_issues:
            if not isinstance(row, dict):
                continue
            level = str(row.get("level", "")).strip().lower()
            message = str(row.get("message", "")).strip()
            if level in {"low", "medium", "high"} and message:
                issues.append(ReviewIssue(level=level, message=message))
        return issues

    def _deduplicate_issues(self, issues: list[ReviewIssue]) -> list[ReviewIssue]:
        seen: set[tuple[str, str]] = set()
        unique: list[ReviewIssue] = []
        for issue in issues:
            key = (issue.level, issue.message)
            if key not in seen:
                seen.add(key)
                unique.append(issue)
        return unique
