"""Create jobs and analysis chapter units.

Revision ID: 0007_jobs
Revises: 0006_analysis_prompt_trace
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_jobs"
down_revision: str | None = "0006_analysis_prompt_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = (
    "IMPORT",
    "INITIALIZE_NOVEL",
    "ANALYZE_CHAPTER",
    "MEMORY_REDUCE",
    "BATCH_EMBED",
    "REBUILD_INDEX",
    "PLAN_CHAPTER",
    "GENERATE_SCENE",
    "CHECK_CONSISTENCY",
    "UPDATE_MEMORY",
    "BACKUP",
)


def upgrade() -> None:
    kinds = ", ".join(f"'{item}'" for item in _KINDS)
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=True),
        sa.Column("progress_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checkpoint", sa.JSON(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.CheckConstraint(f"kind IN ({kinds})", name="ck_jobs_kind"),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'paused', 'failed', 'completed', 'cancelled')",
            name="ck_jobs_state",
        ),
    )
    op.create_index("ix_jobs_novel_id", "jobs", ["novel_id"])
    op.create_index("ix_jobs_state", "jobs", ["state"])
    op.create_table(
        "analysis_chapter_units",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("source_version_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("analyzer_version", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("analysis_id", sa.String(length=36), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checkpoint", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_version_id"], ["chapter_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["chapter_analysis.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("job_id", "chapter_id", name="uq_analysis_unit_job_chapter"),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'failed', 'completed', 'cancelled')",
            name="ck_analysis_units_state",
        ),
    )
    op.create_index("ix_analysis_units_job_id", "analysis_chapter_units", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_units_job_id", table_name="analysis_chapter_units")
    op.drop_table("analysis_chapter_units")
    op.drop_index("ix_jobs_state", table_name="jobs")
    op.drop_index("ix_jobs_novel_id", table_name="jobs")
    op.drop_table("jobs")
