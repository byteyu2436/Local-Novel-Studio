"""Store official Canon chunks for retrieval.

Revision ID: 0014_canon_chunks
Revises: 0013_memory_conflict
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_canon_chunks"
down_revision: str | None = "0013_memory_conflict"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canon_chunks",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("source_version_id", sa.String(length=36), nullable=False),
        sa.Column("source_version_kind", sa.String(length=16), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_checksum", sa.String(length=64), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("overlap_tokens", sa.Integer(), nullable=False),
        sa.Column("characters", sa.JSON(), nullable=False),
        sa.Column("locations", sa.JSON(), nullable=False),
        sa.Column("event_ids", sa.JSON(), nullable=False),
        sa.Column("importance", sa.String(length=16), nullable=False),
        sa.Column("canon_status", sa.String(length=16), nullable=False),
        sa.Column("chunking_version", sa.String(length=64), nullable=False),
        sa.Column("embedding_profile_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_version_kind IN ('ORIGINAL', 'ACCEPTED')",
            name="ck_canon_chunks_source_kind",
        ),
        sa.CheckConstraint(
            "canon_status IN ('active', 'inactive')",
            name="ck_canon_chunks_status",
        ),
        sa.CheckConstraint("length(text) > 0", name="ck_canon_chunks_text"),
    )
    op.create_index("ix_canon_chunks_novel_id", "canon_chunks", ["novel_id"])
    op.create_index("ix_canon_chunks_chapter_id", "canon_chunks", ["chapter_id"])
    op.create_index(
        "uq_canon_chunks_active_index",
        "canon_chunks",
        ["chapter_id", "source_version_id", "chunking_version", "chunk_index"],
        unique=True,
        sqlite_where=sa.text("canon_status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_canon_chunks_active_index", table_name="canon_chunks")
    op.drop_index("ix_canon_chunks_chapter_id", table_name="canon_chunks")
    op.drop_index("ix_canon_chunks_novel_id", table_name="canon_chunks")
    op.drop_table("canon_chunks")
