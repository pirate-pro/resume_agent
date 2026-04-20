"""Initial schema for phase-1 resume agent."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260416_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candidate",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("target_city", sa.String(length=100), nullable=True),
        sa.Column("target_salary_min", sa.Integer(), nullable=True),
        sa.Column("target_salary_max", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "company",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("company_size", sa.String(length=100), nullable=True),
        sa.Column("company_stage", sa.String(length=100), nullable=True),
        sa.Column("location_city", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=True),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "candidate_resume",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), sa.ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=50), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("parsed_status", sa.String(length=50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "candidate_resume_block",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("resume_id", sa.String(length=36), sa.ForeignKey("candidate_resume.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=50), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("bbox_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "candidate_profile",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), sa.ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resume_id", sa.String(length=36), sa.ForeignKey("candidate_resume.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "candidate_skill",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), sa.ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_name_raw", sa.String(length=255), nullable=False),
        sa.Column("skill_name_norm", sa.String(length=255), nullable=False),
        sa.Column("skill_category", sa.String(length=100), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("evidence_block_id", sa.String(length=36), sa.ForeignKey("candidate_resume_block.id", ondelete="SET NULL"), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
    )
    op.create_table(
        "candidate_experience",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), sa.ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("job_title", sa.String(length=255), nullable=True),
        sa.Column("industry_tag", sa.String(length=100), nullable=True),
        sa.Column("start_date", sa.String(length=20), nullable=True),
        sa.Column("end_date", sa.String(length=20), nullable=True),
        sa.Column("duration_months", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_block_id", sa.String(length=36), sa.ForeignKey("candidate_resume_block.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_table(
        "candidate_project",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), sa.ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("role_name", sa.String(length=255), nullable=True),
        sa.Column("tech_stack_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("domain_tags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result_text", sa.Text(), nullable=False),
        sa.Column("evidence_block_id", sa.String(length=36), sa.ForeignKey("candidate_resume_block.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_table(
        "job_posting",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("company.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_title", sa.String(length=255), nullable=False),
        sa.Column("job_title_norm", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("experience_min_years", sa.Integer(), nullable=True),
        sa.Column("experience_max_years", sa.Integer(), nullable=True),
        sa.Column("education_requirement", sa.String(length=100), nullable=True),
        sa.Column("job_description_raw", sa.Text(), nullable=False),
        sa.Column("job_description_clean", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=True),
        sa.Column("source_url", sa.String(length=512), nullable=True),
    )
    op.create_table(
        "job_skill_requirement",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_posting_id", sa.String(length=36), sa.ForeignKey("job_posting.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_name_raw", sa.String(length=255), nullable=False),
        sa.Column("skill_name_norm", sa.String(length=255), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.UniqueConstraint("job_posting_id", "skill_name_norm"),
    )
    op.create_table(
        "match_task",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), sa.ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resume_id", sa.String(length=36), sa.ForeignKey("candidate_resume.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_status", sa.String(length=50), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("target_company_id", sa.String(length=36), sa.ForeignKey("company.id"), nullable=True),
        sa.Column("target_job_id", sa.String(length=36), sa.ForeignKey("job_posting.id"), nullable=True),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "job_match_result",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), sa.ForeignKey("match_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_posting_id", sa.String(length=36), sa.ForeignKey("job_posting.id", ondelete="CASCADE"), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("skill_score", sa.Float(), nullable=False),
        sa.Column("experience_score", sa.Float(), nullable=False),
        sa.Column("project_score", sa.Float(), nullable=False),
        sa.Column("education_score", sa.Float(), nullable=False),
        sa.Column("preference_score", sa.Float(), nullable=False),
        sa.Column("explanation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("gap_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rank_no", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "resume_optimization_task",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), sa.ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resume_id", sa.String(length=36), sa.ForeignKey("candidate_resume.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_job_id", sa.String(length=36), sa.ForeignKey("job_posting.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "resume_optimization_result",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("optimization_task_id", sa.String(length=36), sa.ForeignKey("resume_optimization_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("optimized_resume_markdown", sa.Text(), nullable=False),
        sa.Column("change_summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_note_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_task",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("parent_task_id", sa.String(length=36), nullable=False),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column("agent_role", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "event_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("event_log")
    op.drop_table("agent_task")
    op.drop_table("resume_optimization_result")
    op.drop_table("resume_optimization_task")
    op.drop_table("job_match_result")
    op.drop_table("match_task")
    op.drop_table("job_skill_requirement")
    op.drop_table("job_posting")
    op.drop_table("candidate_project")
    op.drop_table("candidate_experience")
    op.drop_table("candidate_skill")
    op.drop_table("candidate_profile")
    op.drop_table("candidate_resume_block")
    op.drop_table("candidate_resume")
    op.drop_table("company")
    op.drop_table("candidate")
