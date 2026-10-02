"""Store named-entity identities and resolution decisions.

Revision ID: 0011_entity_resolution
Revises: 0010_memory_revision
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_entity_resolution"
down_revision: str | None = "0010_memory_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_named_entities",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "kind IN ('location', 'organization')",
            name="ck_memory_named_entities_kind",
        ),
    )
    op.create_index("ix_memory_named_entities_novel_id", "memory_named_entities", ["novel_id"])
    op.create_table(
        "entity_resolution_records",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("entity_kind", sa.String(length=32), nullable=False),
        sa.Column("mention_name", sa.String(length=256), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("candidate_entity_ids", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("source_chapter_id", sa.String(length=36), nullable=False),
        sa.Column("source_chapter_version_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "entity_kind IN ('character', 'location', 'organization')",
            name="ck_entity_resolutions_kind",
        ),
        sa.CheckConstraint(
            "decision IN ('merged', 'created', 'candidate')",
            name="ck_entity_resolutions_decision",
        ),
    )
    op.create_index("ix_entity_resolutions_novel_id", "entity_resolution_records", ["novel_id"])


def downgrade() -> None:
    op.drop_index("ix_entity_resolutions_novel_id", table_name="entity_resolution_records")
    op.drop_table("entity_resolution_records")
    op.drop_index("ix_memory_named_entities_novel_id", table_name="memory_named_entities")
    op.drop_table("memory_named_entities")
