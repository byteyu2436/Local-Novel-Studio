"""Novel initialization run.

Revision ID: 0017_initialization_run
Revises: 0016_index_registry
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_initialization_run"
down_revision: str | None = "0016_index_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "novel_initialization_runs",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("current_phase", sa.String(length=32), nullable=False),
        sa.Column("child_job_ids", sa.JSON(), nullable=False),
        sa.Column("progress_done", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("profile_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("index_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'paused', 'failed', 'completed', 'cancelled')",
            name="ck_init_runs_state",
        ),
        sa.CheckConstraint(
            "current_phase IN ('analysis', 'memory_reduce', 'chunk', 'embedding', "
            "'index_validate_activate', 'ready')",
            name="ck_init_runs_phase",
        ),
    )
    op.create_index("uq_init_runs_novel", "novel_initialization_runs", ["novel_id"], unique=True)
    op.create_index(
        "uq_init_runs_active",
        "novel_initialization_runs",
        ["novel_id"],
        unique=True,
        sqlite_where=sa.text("state IN ('queued', 'running', 'paused')"),
    )


def downgrade() -> None:
    op.drop_index("uq_init_runs_active", table_name="novel_initialization_runs")
    op.drop_index("uq_init_runs_novel", table_name="novel_initialization_runs")
    op.drop_table("novel_initialization_runs")
