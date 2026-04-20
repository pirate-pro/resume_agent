from __future__ import annotations

from dataclasses import dataclass

from app.core.config.settings import get_settings
from app.core.db.models.entities import JobPosting
from app.domain.models.candidate import CandidateProfile
from app.domain.models.matching import GapAnalysis, MatchScoreCard


@dataclass(slots=True)
class ScoreExplanation:
    matched_required_skills: list[str]
    matched_optional_skills: list[str]
    missing_required_skills: list[str]
    missing_optional_skills: list[str]
    experience_fit: str
    education_fit: str
    preference_fit: str


class MatchScoringService:
    def __init__(self) -> None:
        self._settings = get_settings()

    def score(self, profile: CandidateProfile, job: JobPosting) -> tuple[MatchScoreCard, GapAnalysis, ScoreExplanation]:
        candidate_skills = {skill.normalized_name for skill in profile.skills}
        required_skills = [
            requirement.skill_name_norm for requirement in job.skill_requirements if requirement.is_required
        ]
        optional_skills = [
            requirement.skill_name_norm for requirement in job.skill_requirements if not requirement.is_required
        ]
        matched_required = [skill for skill in required_skills if skill in candidate_skills]
        missing_required = [skill for skill in required_skills if skill not in candidate_skills]
        matched_optional = [skill for skill in optional_skills if skill in candidate_skills]
        missing_optional = [skill for skill in optional_skills if skill not in candidate_skills]

        skill_score = self._ratio(
            len(matched_required) + 0.5 * len(matched_optional),
            len(required_skills) + 0.5 * len(optional_skills),
        )
        candidate_years = profile.total_experience_months / 12
        required_years = float(job.experience_min_years or 0)
        experience_score = 1.0 if required_years == 0 else min(candidate_years / required_years, 1.0)

        project_skill_overlap = 0
        if profile.projects:
            project_skill_overlap = max(
                len(set(project.tech_stack) & set(required_skills + optional_skills)) for project in profile.projects
            )
        project_score = self._ratio(project_skill_overlap, max(len(required_skills), 1))

        education_score = self._education_score(profile.education_level, job.education_requirement)
        preference_score = self._preference_score(profile.target_city, job.city)
        overall_score = (
            skill_score * self._settings.score_weight_skill
            + experience_score * self._settings.score_weight_experience
            + project_score * self._settings.score_weight_project
            + education_score * self._settings.score_weight_education
            + preference_score * self._settings.score_weight_preference
        )

        score_card = MatchScoreCard(
            overall_score=round(overall_score, 4),
            skill_score=round(skill_score, 4),
            experience_score=round(experience_score, 4),
            project_score=round(project_score, 4),
            education_score=round(education_score, 4),
            preference_score=round(preference_score, 4),
        )
        gap = GapAnalysis(
            missing_required_skills=missing_required,
            missing_optional_skills=missing_optional,
            experience_gap=None if experience_score >= 1 else f"当前经验约 {candidate_years:.1f} 年，低于岗位要求 {required_years:.1f} 年",
            education_gap=None if education_score >= 1 else f"岗位要求 {job.education_requirement}",
        )
        explanation = ScoreExplanation(
            matched_required_skills=matched_required,
            matched_optional_skills=matched_optional,
            missing_required_skills=missing_required,
            missing_optional_skills=missing_optional,
            experience_fit="经验满足岗位要求" if experience_score >= 1 else "经验尚有差距",
            education_fit="学历满足要求" if education_score >= 1 else "学历可能不满足要求",
            preference_fit="意向城市匹配" if preference_score >= 1 else "城市存在偏差",
        )
        return score_card, gap, explanation

    def _ratio(self, numerator: float, denominator: float) -> float:
        return round(min(numerator / max(denominator, 1), 1.0), 4)

    def _education_score(self, candidate_level: str | None, required_level: str | None) -> float:
        rank = {"高中": 1, "大专": 2, "本科": 3, "硕士": 4, "博士": 5}
        if required_level is None:
            return 1.0
        if candidate_level is None:
            return 0.4
        return 1.0 if rank.get(candidate_level, 0) >= rank.get(required_level, 0) else 0.4

    def _preference_score(self, target_city: str | None, job_city: str | None) -> float:
        if not target_city or not job_city:
            return 1.0
        return 1.0 if target_city.lower() == job_city.lower() else 0.3
