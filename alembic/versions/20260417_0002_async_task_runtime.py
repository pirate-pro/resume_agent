"""Add async task runtime metadata and retry fields."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260417_0002"
down_revision: Union[str, None] = "20260416_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("match_task", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column("match_task", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("match_task", sa.Column("max_retries", sa.Integer(), nullable=False, server_default="2"))
    op.add_column("match_task", sa.Column("stage_timeout_sec", sa.Integer(), nullable=False, server_default="180"))
    op.add_column("match_task", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("match_task", sa.Column("locked_by", sa.String(length=100), nullable=True))
    op.add_column("match_task", sa.Column("stage_started_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE match_task SET task_status = 'queued' WHERE task_status = 'pending'")

    op.add_column("resume_optimization_task", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column(
        "resume_optimization_task",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "resume_optimization_task",
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="2"),
    )
    op.add_column(
        "resume_optimization_task",
        sa.Column("stage_timeout_sec", sa.Integer(), nullable=False, server_default="180"),
    )
    op.add_column("resume_optimization_task", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("resume_optimization_task", sa.Column("locked_by", sa.String(length=100), nullable=True))
    op.add_column(
        "resume_optimization_task", sa.Column("stage_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "resume_optimization_task",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.execute("UPDATE resume_optimization_task SET status = 'queued' WHERE status = 'pending'")

    op.add_column("agent_task", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column("agent_task", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_task", sa.Column("timeout_sec", sa.Integer(), nullable=True))

    op.alter_column("match_task", "retry_count", server_default=None)
    op.alter_column("match_task", "max_retries", server_default=None)
    op.alter_column("match_task", "stage_timeout_sec", server_default=None)
    op.alter_column("resume_optimization_task", "retry_count", server_default=None)
    op.alter_column("resume_optimization_task", "max_retries", server_default=None)
    op.alter_column("resume_optimization_task", "stage_timeout_sec", server_default=None)
    op.alter_column("resume_optimization_task", "updated_at", server_default=None)
    op.alter_column("agent_task", "retry_count", server_default=None)


def downgrade() -> None:
    op.drop_column("agent_task", "timeout_sec")
    op.drop_column("agent_task", "retry_count")
    op.drop_column("agent_task", "failure_reason")

    op.drop_column("resume_optimization_task", "updated_at")
    op.drop_column("resume_optimization_task", "stage_started_at")
    op.drop_column("resume_optimization_task", "locked_by")
    op.drop_column("resume_optimization_task", "locked_at")
    op.drop_column("resume_optimization_task", "stage_timeout_sec")
    op.drop_column("resume_optimization_task", "max_retries")
    op.drop_column("resume_optimization_task", "retry_count")
    op.drop_column("resume_optimization_task", "failure_reason")

    op.drop_column("match_task", "stage_started_at")
    op.drop_column("match_task", "locked_by")
    op.drop_column("match_task", "locked_at")
    op.drop_column("match_task", "stage_timeout_sec")
    op.drop_column("match_task", "max_retries")
    op.drop_column("match_task", "retry_count")
    op.drop_column("match_task", "failure_reason")
