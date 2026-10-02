"""Remember which Canon versions have already been reduced.

Revision ID: 0012_reduce_application
Revises: 0011_entity_resolution
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_reduce_application"
down_revision: str | None = "0011_entity_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_reduce_applications",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("source_chapter_id", sa.String(length=36), nullable=False),
        sa.Column("source_chapter_version_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "novel_id",
            "source_chapter_version_id",
            name="uq_memory_reduce_applications_version",
        ),
    )
    op.create_index(
        "ix_memory_reduce_applications_novel_id",
        "memory_reduce_applications",
        ["novel_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_reduce_applications_novel_id",
        table_name="memory_reduce_applications",
    )
    op.drop_table("memory_reduce_applications")
