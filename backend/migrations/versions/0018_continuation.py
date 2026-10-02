"""Continuation plans, drafts, consistency issues, and accept operations.

Revision ID: 0018_continuation
Revises: 0017_initialization_run
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_continuation"
down_revision: str | None = "0017_initialization_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chapter_plan_versions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("target_sequence", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("chapter_goal", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model_ref", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("context_checksum", sa.String(length=64), nullable=False),
        sa.Column("is_confirmed_pointer", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'generated', 'edited', 'confirmed', 'superseded')",
            name="ck_plan_versions_status",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_plan_versions_novel",
        "chapter_plan_versions",
        ["novel_id", "target_sequence"],
    )
    op.create_index(
        "uq_plan_confirmed_pointer",
        "chapter_plan_versions",
        ["novel_id", "target_sequence"],
        unique=True,
        sqlite_where=sa.text("is_confirmed_pointer = 1"),
    )
    op.create_table(
        "draft_versions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("target_sequence", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=True),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "origin IN ('generated', 'user', 'rewrite')",
            name="ck_draft_versions_origin",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_draft_versions_novel", "draft_versions", ["novel_id"])
    op.create_table(
        "consistency_issues",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'blocking')",
            name="ck_consistency_issues_severity",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["draft_id"], ["draft_versions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_consistency_issues_draft", "consistency_issues", ["draft_id"])
    op.create_table(
        "accept_operations",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("memory_status", sa.String(length=32), nullable=False),
        sa.Column("index_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["draft_id"], ["draft_versions.id"], ondelete="CASCADE"),
    )
    op.create_index("uq_accept_operations_draft", "accept_operations", ["draft_id"], unique=True)
    op.create_index("ix_accept_operations_novel", "accept_operations", ["novel_id"])


def downgrade() -> None:
    op.drop_index("ix_accept_operations_novel", table_name="accept_operations")
    op.drop_index("uq_accept_operations_draft", table_name="accept_operations")
    op.drop_table("accept_operations")
    op.drop_index("ix_consistency_issues_draft", table_name="consistency_issues")
    op.drop_table("consistency_issues")
    op.drop_index("ix_draft_versions_novel", table_name="draft_versions")
    op.drop_table("draft_versions")
    op.drop_index("uq_plan_confirmed_pointer", table_name="chapter_plan_versions")
    op.drop_index("ix_plan_versions_novel", table_name="chapter_plan_versions")
    op.drop_table("chapter_plan_versions")
