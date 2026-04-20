from datetime import datetime

from pydantic import BaseModel, Field


class ResumeUploadResponse(BaseModel):
    candidate_id: str
    resume_id: str
    file_name: str
    file_path: str


class MatchTaskCreateRequest(BaseModel):
    resume_id: str
    target_city: str | None = None


class ScoreCardResponse(BaseModel):
    overall_score: float
    skill_score: float
    experience_score: float
    project_score: float
    education_score: float
    preference_score: float


class MatchResultResponse(BaseModel):
    job_posting_id: str
    company_name: str
    job_title: str
    city: str | None
    score_card: ScoreCardResponse
    explanation: dict
    gap: dict
    rank_no: int


class EventResponse(BaseModel):
    event_type: str
    payload: dict
    created_at: datetime


class MatchTaskResponse(BaseModel):
    task_id: str
    task_status: str
    stage: str
    candidate_id: str
    resume_id: str
    failure_reason: str | None = None
    retry_count: int = 0
    max_retries: int = 0
    stage_timeout_sec: int = 0
    matches: list[MatchResultResponse]
    events: list[EventResponse]


class TaskAcceptedResponse(BaseModel):
    task_id: str
    task_status: str
    stage: str
    failure_reason: str | None = None
    retry_count: int = 0
    max_retries: int = 0
    stage_timeout_sec: int = 0


class OptimizationTaskCreateRequest(BaseModel):
    resume_id: str
    target_job_id: str
    mode: str = Field(default="targeted")


class OptimizationTaskResponse(BaseModel):
    task_id: str
    task_status: str
    status: str
    stage: str
    target_job_id: str
    failure_reason: str | None = None
    retry_count: int = 0
    max_retries: int = 0
    stage_timeout_sec: int = 0
    optimized_resume_markdown: str
    change_summary: list[dict]
    risk_notes: list[dict]
    review_report: dict
    events: list[EventResponse]


class JobPostingResponse(BaseModel):
    id: str
    company_name: str
    title: str
    city: str | None
    education_requirement: str | None
    experience_min_years: int | None
    skills: list[dict]


class HealthResponse(BaseModel):
    status: str
    checks: dict
