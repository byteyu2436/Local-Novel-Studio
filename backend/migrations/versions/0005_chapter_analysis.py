"""Create chapter_analysis for official Canon chapter structured results.

Revision ID: 0005_chapter_analysis
Revises: 0004_novels_chapters
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_chapter_analysis"
down_revision: str | None = "0004_novels_chapters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chapter_analysis",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("source_version_id", sa.String(length=36), nullable=False),
        sa.Column("source_version_kind", sa.String(length=16), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("analyzer_version", sa.String(length=64), nullable=False),
        sa.Column("model_profile_id", sa.String(length=128), nullable=False),
        sa.Column("model_ref", sa.String(length=128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_version_id"], ["chapter_versions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "chapter_id",
            "source_version_id",
            name="uq_chapter_analysis_chapter_source",
        ),
        sa.CheckConstraint(
            "source_version_kind IN ('ORIGINAL', 'ACCEPTED')",
            name="ck_chapter_analysis_source_kind",
        ),
    )
    op.create_index("ix_chapter_analysis_chapter_id", "chapter_analysis", ["chapter_id"])


def downgrade() -> None:
    op.drop_index("ix_chapter_analysis_chapter_id", table_name="chapter_analysis")
    op.drop_table("chapter_analysis")
