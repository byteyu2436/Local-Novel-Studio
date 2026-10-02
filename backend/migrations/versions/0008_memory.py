"""Create novel memory entities and fact revisions.

Revision ID: 0008_memory
Revises: 0007_jobs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_memory"
down_revision: str | None = "0007_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUBJECTS = (
    "character",
    "relationship",
    "event",
    "timeline",
    "foreshadowing",
    "world_fact",
    "style_profile",
)
_FORESHADOW = ("planted", "reinforced", "resolved", "abandoned")


def _entity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _novel_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "memory_characters",
        *_entity_columns(),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        _novel_fk(),
    )
    op.create_index("ix_memory_characters_novel_id", "memory_characters", ["novel_id"])
    op.create_table(
        "memory_relationships",
        *_entity_columns(),
        sa.Column("source_character_id", sa.String(length=36), nullable=False),
        sa.Column("target_character_id", sa.String(length=36), nullable=False),
        _novel_fk(),
        sa.ForeignKeyConstraint(
            ["source_character_id"], ["memory_characters.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_character_id"], ["memory_characters.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "novel_id",
            "source_character_id",
            "target_character_id",
            name="uq_memory_relationships_pair",
        ),
    )
    op.create_index("ix_memory_relationships_novel_id", "memory_relationships", ["novel_id"])
    for table, label in (
        ("memory_events", "label"),
        ("memory_timelines", "label"),
        ("memory_world_facts", "topic"),
    ):
        op.create_table(
            table,
            *_entity_columns(),
            sa.Column(label, sa.String(length=256), nullable=False),
            _novel_fk(),
        )
        op.create_index(f"ix_{table}_novel_id", table, ["novel_id"])
    foreshadow = ", ".join(f"'{item}'" for item in _FORESHADOW)
    op.create_table(
        "memory_foreshadowings",
        *_entity_columns(),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        _novel_fk(),
        sa.CheckConstraint(f"status IN ({foreshadow})", name="ck_memory_foreshadowings_status"),
    )
    op.create_index("ix_memory_foreshadowings_novel_id", "memory_foreshadowings", ["novel_id"])
    op.create_table(
        "memory_style_profiles",
        *_entity_columns(),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("statistics", sa.JSON(), nullable=False),
        _novel_fk(),
        sa.UniqueConstraint("novel_id", name="uq_memory_style_profiles_novel"),
    )
    op.create_index("ix_memory_style_profiles_novel_id", "memory_style_profiles", ["novel_id"])
    subjects = ", ".join(f"'{item}'" for item in _SUBJECTS)
    op.create_table(
        "memory_facts",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("fact_key", sa.String(length=64), nullable=False),
        sa.Column("fact_value", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _novel_fk(),
        sa.UniqueConstraint(
            "subject_kind",
            "subject_id",
            "fact_key",
            "revision",
            name="uq_memory_facts_revision",
        ),
        sa.CheckConstraint(f"subject_kind IN ({subjects})", name="ck_memory_facts_subject_kind"),
    )
    op.create_index("ix_memory_facts_novel_id", "memory_facts", ["novel_id"])
    op.create_index("ix_memory_facts_subject", "memory_facts", ["subject_kind", "subject_id"])
    op.create_index(
        "uq_memory_facts_active_key",
        "memory_facts",
        ["subject_kind", "subject_id", "fact_key"],
        unique=True,
        sqlite_where=sa.text("active = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_memory_facts_active_key", table_name="memory_facts")
    op.drop_index("ix_memory_facts_subject", table_name="memory_facts")
    op.drop_index("ix_memory_facts_novel_id", table_name="memory_facts")
    op.drop_table("memory_facts")
    op.drop_index("ix_memory_style_profiles_novel_id", table_name="memory_style_profiles")
    op.drop_table("memory_style_profiles")
    op.drop_index("ix_memory_foreshadowings_novel_id", table_name="memory_foreshadowings")
    op.drop_table("memory_foreshadowings")
    for table in ("memory_world_facts", "memory_timelines", "memory_events"):
        op.drop_index(f"ix_{table}_novel_id", table_name=table)
        op.drop_table(table)
    op.drop_index("ix_memory_relationships_novel_id", table_name="memory_relationships")
    op.drop_table("memory_relationships")
    op.drop_index("ix_memory_characters_novel_id", table_name="memory_characters")
    op.drop_table("memory_characters")
