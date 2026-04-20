from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Candidate(Base):
    __tablename__ = "candidate"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    resumes: Mapped[list[CandidateResume]] = relationship(back_populates="candidate")


class CandidateResume(Base):
    __tablename__ = "candidate_resume"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate.id", ondelete="CASCADE"))
    file_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(50))
    file_path: Mapped[str] = mapped_column(String(512))
    parsed_status: Mapped[str] = mapped_column(String(50), default="pending")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    candidate: Mapped[Candidate] = relationship(back_populates="resumes")
    blocks: Mapped[list[CandidateResumeBlock]] = relationship(back_populates="resume")


class CandidateResumeBlock(Base):
    __tablename__ = "candidate_resume_block"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    resume_id: Mapped[str] = mapped_column(ForeignKey("candidate_resume.id", ondelete="CASCADE"))
    page_no: Mapped[int] = mapped_column(Integer, default=1)
    block_type: Mapped[str] = mapped_column(String(50))
    block_index: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    bbox_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    resume: Mapped[CandidateResume] = relationship(back_populates="blocks")


class CandidateProfile(Base):
    __tablename__ = "candidate_profile"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate.id", ondelete="CASCADE"))
    resume_id: Mapped[str] = mapped_column(ForeignKey("candidate_resume.id", ondelete="CASCADE"))
    profile_json: Mapped[dict] = mapped_column(JSONB)
    confidence_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CandidateSkill(Base):
    __tablename__ = "candidate_skill"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate.id", ondelete="CASCADE"))
    skill_name_raw: Mapped[str] = mapped_column(String(255))
    skill_name_norm: Mapped[str] = mapped_column(String(255))
    skill_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evidence_text: Mapped[str] = mapped_column(Text)
    evidence_block_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidate_resume_block.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class CandidateExperience(Base):
    __tablename__ = "candidate_experience"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate.id", ondelete="CASCADE"))
    company_name: Mapped[str] = mapped_column(String(255))
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    industry_tag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    duration_months: Mapped[int] = mapped_column(Integer, default=12)
    description: Mapped[str] = mapped_column(Text)
    evidence_block_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidate_resume_block.id", ondelete="SET NULL"), nullable=True
    )


class CandidateProject(Base):
    __tablename__ = "candidate_project"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate.id", ondelete="CASCADE"))
    project_name: Mapped[str] = mapped_column(String(255))
    role_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tech_stack_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    domain_tags_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    result_text: Mapped[str] = mapped_column(Text)
    evidence_block_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidate_resume_block.id", ondelete="SET NULL"), nullable=True
    )


class Company(Base):
    __tablename__ = "company"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company_size: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company_stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JobPosting(Base):
    __tablename__ = "job_posting"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id", ondelete="CASCADE"))
    job_title: Mapped[str] = mapped_column(String(255))
    job_title_norm: Mapped[str] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experience_min_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experience_max_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    education_requirement: Mapped[str | None] = mapped_column(String(100), nullable=True)
    job_description_raw: Mapped[str] = mapped_column(Text)
    job_description_clean: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="active")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    company: Mapped[Company] = relationship()
    skill_requirements: Mapped[list[JobSkillRequirement]] = relationship(back_populates="job_posting")


class JobSkillRequirement(Base):
    __tablename__ = "job_skill_requirement"
    __table_args__ = (UniqueConstraint("job_posting_id", "skill_name_norm"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_posting_id: Mapped[str] = mapped_column(ForeignKey("job_posting.id", ondelete="CASCADE"))
    skill_name_raw: Mapped[str] = mapped_column(String(255))
    skill_name_norm: Mapped[str] = mapped_column(String(255))
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)

    job_posting: Mapped[JobPosting] = relationship(back_populates="skill_requirements")


class MatchTask(Base):
    __tablename__ = "match_task"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate.id", ondelete="CASCADE"))
    resume_id: Mapped[str] = mapped_column(ForeignKey("candidate_resume.id", ondelete="CASCADE"))
    task_status: Mapped[str] = mapped_column(String(50), default="queued")
    stage: Mapped[str] = mapped_column(String(50), default="intake")
    target_company_id: Mapped[str | None] = mapped_column(ForeignKey("company.id"), nullable=True)
    target_job_id: Mapped[str | None] = mapped_column(ForeignKey("job_posting.id"), nullable=True)
    input_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    stage_timeout_sec: Mapped[int] = mapped_column(Integer, default=180)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stage_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JobMatchResult(Base):
    __tablename__ = "job_match_result"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("match_task.id", ondelete="CASCADE"))
    job_posting_id: Mapped[str] = mapped_column(ForeignKey("job_posting.id", ondelete="CASCADE"))
    overall_score: Mapped[float] = mapped_column(Float)
    skill_score: Mapped[float] = mapped_column(Float)
    experience_score: Mapped[float] = mapped_column(Float)
    project_score: Mapped[float] = mapped_column(Float)
    education_score: Mapped[float] = mapped_column(Float)
    preference_score: Mapped[float] = mapped_column(Float)
    explanation_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    gap_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    rank_no: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResumeOptimizationTask(Base):
    __tablename__ = "resume_optimization_task"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate.id", ondelete="CASCADE"))
    resume_id: Mapped[str] = mapped_column(ForeignKey("candidate_resume.id", ondelete="CASCADE"))
    target_job_id: Mapped[str] = mapped_column(ForeignKey("job_posting.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(50), default="targeted")
    status: Mapped[str] = mapped_column(String(50), default="queued")
    stage: Mapped[str] = mapped_column(String(50), default="optimize")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    stage_timeout_sec: Mapped[int] = mapped_column(Integer, default=180)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stage_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ResumeOptimizationResult(Base):
    __tablename__ = "resume_optimization_result"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    optimization_task_id: Mapped[str] = mapped_column(
        ForeignKey("resume_optimization_task.id", ondelete="CASCADE")
    )
    optimized_resume_markdown: Mapped[str] = mapped_column(Text)
    change_summary_json: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    risk_note_json: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    review_report_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentTask(Base):
    __tablename__ = "agent_task"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    parent_task_id: Mapped[str] = mapped_column(String(36))
    task_type: Mapped[str] = mapped_column(String(50))
    agent_role: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    timeout_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    output_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventLog(Base):
    __tablename__ = "event_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(100))
    event_payload_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
