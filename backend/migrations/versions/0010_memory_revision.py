"""Track a novel-level memory revision.

Revision ID: 0010_memory_revision
Revises: 0009_fact_provenance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_memory_revision"
down_revision: str | None = "0009_fact_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "novel_memory_revisions",
        sa.Column("novel_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("novel_memory_revisions")
