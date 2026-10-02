"""Add fact provenance, origin, and revision status.

Revision ID: 0009_fact_provenance
Revises: 0008_memory
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_fact_provenance"
down_revision: str | None = "0008_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("memory_facts") as batch:
        batch.add_column(
            sa.Column("origin", sa.String(length=16), nullable=False, server_default="inferred")
        )
        batch.add_column(
            sa.Column("status", sa.String(length=16), nullable=False, server_default="active")
        )
        batch.add_column(sa.Column("confidence", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("source_chapter_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column("source_chapter_version_id", sa.String(length=36), nullable=True)
        )
        batch.add_column(sa.Column("source_snapshot_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("source_start_offset", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_end_offset", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_text_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("source_chunk_ids", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("superseded_by_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_memory_facts_source_chapter",
            "chapters",
            ["source_chapter_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_memory_facts_source_version",
            "chapter_versions",
            ["source_chapter_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "ck_memory_facts_origin", "origin IN ('explicit', 'inferred')"
        )
        batch.create_check_constraint(
            "ck_memory_facts_status", "status IN ('active', 'superseded')"
        )
        batch.create_check_constraint(
            "ck_memory_facts_active_status",
            "(active = 1 AND status = 'active') OR (active = 0 AND status = 'superseded')",
        )
        batch.create_check_constraint(
            "ck_memory_facts_confidence", "confidence >= 0 AND confidence <= 1"
        )
        batch.create_check_constraint(
            "ck_memory_facts_origin_span",
            "("
            "origin = 'explicit' AND source_start_offset IS NOT NULL "
            "AND source_end_offset IS NOT NULL AND source_text_hash IS NOT NULL"
            ") OR ("
            "origin = 'inferred' AND source_start_offset IS NULL "
            "AND source_end_offset IS NULL AND source_text_hash IS NULL"
            ")",
        )
        batch.create_index("ix_memory_facts_source_version", ["source_chapter_version_id"])
    op.execute("UPDATE memory_facts SET updated_at = created_at WHERE updated_at IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("memory_facts") as batch:
        batch.drop_index("ix_memory_facts_source_version")
        batch.drop_constraint("ck_memory_facts_origin_span", type_="check")
        batch.drop_constraint("ck_memory_facts_confidence", type_="check")
        batch.drop_constraint("ck_memory_facts_active_status", type_="check")
        batch.drop_constraint("ck_memory_facts_status", type_="check")
        batch.drop_constraint("ck_memory_facts_origin", type_="check")
        batch.drop_constraint("fk_memory_facts_source_version", type_="foreignkey")
        batch.drop_constraint("fk_memory_facts_source_chapter", type_="foreignkey")
        for name in (
            "updated_at",
            "superseded_by_id",
            "source_chunk_ids",
            "source_text_hash",
            "source_end_offset",
            "source_start_offset",
            "source_snapshot_id",
            "source_chapter_version_id",
            "source_chapter_id",
            "locked",
            "confidence",
            "status",
            "origin",
        ):
            batch.drop_column(name)
