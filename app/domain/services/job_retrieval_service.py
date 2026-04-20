from __future__ import annotations

from app.core.db.models.entities import JobPosting
from app.domain.models.candidate import CandidateProfile
from app.domain.models.matching import MatchResult
from app.domain.services.match_scoring_service import MatchScoringService


class JobRetrievalService:
    def __init__(self, scoring_service: MatchScoringService | None = None) -> None:
        self._scoring_service = scoring_service or MatchScoringService()

    def retrieve_and_rank(self, profile: CandidateProfile, jobs: list[JobPosting], top_k: int) -> list[MatchResult]:
        results: list[MatchResult] = []
        filtered_jobs = [job for job in jobs if self._passes_hard_filters(profile, job)]
        for job in filtered_jobs:
            score_card, gap, explanation = self._scoring_service.score(profile, job)
            results.append(
                MatchResult(
                    job_posting_id=job.id,
                    company_name=job.company.name,
                    job_title=job.job_title,
                    city=job.city,
                    score_card=score_card,
                    explanation={
                        "matched_required_skills": explanation.matched_required_skills,
                        "matched_optional_skills": explanation.matched_optional_skills,
                        "experience_fit": explanation.experience_fit,
                        "education_fit": explanation.education_fit,
                        "preference_fit": explanation.preference_fit,
                        "evidence": {
                            "candidate_summary": profile.summary,
                            "top_skills": [skill.normalized_name for skill in profile.skills[:5]],
                        },
                    },
                    gap=gap,
                    rank_no=0,
                )
            )
        ranked = sorted(results, key=lambda item: item.score_card.overall_score, reverse=True)[:top_k]
        for index, item in enumerate(ranked, start=1):
            item.rank_no = index
        return ranked

    def _passes_hard_filters(self, profile: CandidateProfile, job: JobPosting) -> bool:
        if profile.target_city and job.city and profile.target_city.lower() != job.city.lower():
            return False
        if job.education_requirement and profile.education_level is None:
            return False
        return True
