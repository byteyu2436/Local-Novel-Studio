"""Add prompt_version and profile_version to official chapter analysis.

Revision ID: 0006_analysis_prompt_trace
Revises: 0005_chapter_analysis
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_analysis_prompt_trace"
down_revision: str | None = "0005_chapter_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chapter_analysis") as batch:
        batch.add_column(
            sa.Column(
                "prompt_version",
                sa.String(length=64),
                nullable=False,
                server_default="",
            )
        )
        batch.add_column(
            sa.Column(
                "profile_version",
                sa.String(length=64),
                nullable=False,
                server_default="",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("chapter_analysis") as batch:
        batch.drop_column("profile_version")
        batch.drop_column("prompt_version")
