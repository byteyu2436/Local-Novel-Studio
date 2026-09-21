"""Create novels, chapters, and chapter_versions.

Revision ID: 0004_novels_chapters
Revises: 0003_import_encoding
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_novels_chapters"
down_revision: str | None = "0003_import_encoding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "novels",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "chapters",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("original_label", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("original_title", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("display_title", sa.String(length=512), nullable=False),
        sa.Column("title_source", sa.String(length=16), nullable=False),
        sa.Column("title_confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("current_canon_version_id", sa.String(length=36), nullable=True),
        sa.Column("import_source_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["import_source_id"], ["import_sources.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("novel_id", "sequence", name="uq_chapters_novel_sequence"),
        sa.CheckConstraint(
            "title_source IN ('original', 'user', 'generated', 'fallback')",
            name="ck_chapters_title_source",
        ),
    )
    op.create_index("ix_chapters_novel_id", "chapters", ["novel_id"])
    op.create_table(
        "chapter_versions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("chapter_id", sa.String(length=36), nullable=False),
        sa.Column("version_kind", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("superseded_by_id", sa.String(length=36), nullable=True),
        sa.Column("import_source_id", sa.String(length=36), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("source_checksum", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["chapter_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["chapter_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["import_source_id"], ["import_sources.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "version_kind IN ('ORIGINAL', 'DRAFT', 'ACCEPTED')",
            name="ck_chapter_versions_kind",
        ),
    )
    op.create_index("ix_chapter_versions_chapter_id", "chapter_versions", ["chapter_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_chapter_versions_original "
        "ON chapter_versions(chapter_id) WHERE version_kind = 'ORIGINAL'"
    )
    with op.batch_alter_table("chapters") as batch:
        batch.create_foreign_key(
            "fk_chapters_current_canon_version_id",
            "chapter_versions",
            ["current_canon_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.execute(
        """
        CREATE TRIGGER trg_chapter_versions_original_immutable
        BEFORE UPDATE ON chapter_versions
        BEGIN
            SELECT CASE
                WHEN OLD.version_kind = 'ORIGINAL'
                 AND (
                      NEW.body IS NOT OLD.body
                   OR NEW.version_kind IS NOT OLD.version_kind
                   OR NEW.start_offset IS NOT OLD.start_offset
                   OR NEW.end_offset IS NOT OLD.end_offset
                   OR NEW.import_source_id IS NOT OLD.import_source_id
                   OR NEW.source_checksum IS NOT OLD.source_checksum
                 )
                THEN RAISE(ABORT, 'ORIGINAL chapter version is immutable')
            END;
        END;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_chapter_versions_original_immutable")
    op.drop_table("chapter_versions")
    op.drop_table("chapters")
    op.drop_table("novels")
