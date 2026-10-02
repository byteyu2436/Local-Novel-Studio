"""Versioned embedding profiles.

Revision ID: 0015_embedding_profile
Revises: 0014_canon_chunks
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_embedding_profile"
down_revision: str | None = "0014_canon_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "embedding_profiles",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("embedding_model_id", sa.String(length=128), nullable=False),
        sa.Column("embedding_model_tag", sa.String(length=64), nullable=False),
        sa.Column("embedding_model_version", sa.String(length=128), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("normalization", sa.String(length=16), nullable=False),
        sa.Column("chunking_version", sa.String(length=64), nullable=False),
        sa.Column("index_version", sa.String(length=64), nullable=False),
        sa.Column("rebuild_required", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "normalization IN ('none', 'l2')",
            name="ck_embedding_profiles_normalization",
        ),
        sa.CheckConstraint("dimension > 0", name="ck_embedding_profiles_dimension"),
    )
    op.create_index(
        "uq_embedding_profiles_active",
        "embedding_profiles",
        ["is_active"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
    )
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("text_checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=True),
        sa.Column("vector", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("batch_no", sa.Integer(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('ready', 'failed')",
            name="ck_chunk_embeddings_status",
        ),
    )
    op.create_index(
        "uq_chunk_embeddings_chunk_profile",
        "chunk_embeddings",
        ["chunk_id", "profile_id"],
        unique=True,
    )
    op.create_index("ix_chunk_embeddings_novel_id", "chunk_embeddings", ["novel_id"])


def downgrade() -> None:
    op.drop_index("ix_chunk_embeddings_novel_id", table_name="chunk_embeddings")
    op.drop_index("uq_chunk_embeddings_chunk_profile", table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")
    op.drop_index("uq_embedding_profiles_active", table_name="embedding_profiles")
    op.drop_table("embedding_profiles")
