"""Store conflicts, operation logs, snapshots, and title metadata.

Revision ID: 0013_memory_conflict
Revises: 0012_reduce_application
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_memory_conflict"
down_revision: str | None = "0012_reduce_application"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "novels",
        sa.Column("auto_title_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "chapters",
        sa.Column("title_candidates", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "memory_conflicts",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("fact_key", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("existing_fact_id", sa.String(length=36), nullable=False),
        sa.Column("existing_revision", sa.Integer(), nullable=False),
        sa.Column("existing_value", sa.JSON(), nullable=False),
        sa.Column("existing_source_chapter_id", sa.String(length=36), nullable=True),
        sa.Column("existing_source_chapter_version_id", sa.String(length=36), nullable=True),
        sa.Column("incoming_value", sa.JSON(), nullable=False),
        sa.Column("incoming_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("incoming_source_chapter_id", sa.String(length=36), nullable=False),
        sa.Column("incoming_source_chapter_version_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["existing_fact_id"], ["memory_facts.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')",
            name="ck_memory_conflicts_status",
        ),
        sa.CheckConstraint(
            "resolution IS NULL OR resolution IN "
            "('keep_existing', 'accept_incoming', 'edit', 'dismiss')",
            name="ck_memory_conflicts_resolution",
        ),
    )
    op.create_index("ix_memory_conflicts_novel_id", "memory_conflicts", ["novel_id"])
    op.create_index("ix_memory_conflicts_existing_fact", "memory_conflicts", ["existing_fact_id"])
    op.create_table(
        "memory_operation_logs",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("before_revision", sa.Integer(), nullable=True),
        sa.Column("after_revision", sa.Integer(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_memory_operation_logs_novel_id", "memory_operation_logs", ["novel_id"])
    op.create_table(
        "memory_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("accepted_chapter_id", sa.String(length=36), nullable=False),
        sa.Column("memory_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["accepted_chapter_id"], ["chapters.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "novel_id",
            "accepted_chapter_id",
            "memory_revision",
            name="uq_memory_snapshots_anchor",
        ),
    )
    op.create_index("ix_memory_snapshots_novel_id", "memory_snapshots", ["novel_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_snapshots_novel_id", table_name="memory_snapshots")
    op.drop_table("memory_snapshots")
    op.drop_index("ix_memory_operation_logs_novel_id", table_name="memory_operation_logs")
    op.drop_table("memory_operation_logs")
    op.drop_index("ix_memory_conflicts_existing_fact", table_name="memory_conflicts")
    op.drop_index("ix_memory_conflicts_novel_id", table_name="memory_conflicts")
    op.drop_table("memory_conflicts")
    op.drop_column("chapters", "title_candidates")
    op.drop_column("novels", "auto_title_enabled")
