"""Create import_sources and derived normalized text tables.

Revision ID: 0002_import_sources
Revises: 0001_app_settings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_import_sources"
down_revision: str | None = "0001_app_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_sources",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parse_status", sa.String(length=16), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=True),
        sa.Column("original_storage_path", sa.String(length=1024), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("raw_byte_size", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('paste', 'txt')",
            name="ck_import_sources_source_type",
        ),
        sa.CheckConstraint(
            "parse_status IN ('received', 'normalized', 'failed')",
            name="ck_import_sources_parse_status",
        ),
        sa.CheckConstraint(
            "(source_type = 'paste' AND raw_text IS NOT NULL) OR "
            "(source_type = 'txt' AND original_storage_path IS NOT NULL)",
            name="ck_import_sources_payload",
        ),
    )
    op.create_index("ix_import_sources_checksum", "import_sources", ["checksum"])
    op.create_table(
        "import_source_normalized_texts",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("import_source_id", sa.String(length=36), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalization_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_source_id"],
            ["import_sources.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("import_source_id", name="uq_import_source_normalized_texts_source"),
    )
    op.execute(
        """
        CREATE TRIGGER trg_import_sources_immutable
        BEFORE UPDATE ON import_sources
        BEGIN
            SELECT CASE
                WHEN NEW.id IS NOT OLD.id
                  OR NEW.source_type IS NOT OLD.source_type
                  OR NEW.checksum IS NOT OLD.checksum
                  OR NEW.created_at IS NOT OLD.created_at
                  OR NEW.raw_text IS NOT OLD.raw_text
                  OR NEW.raw_byte_size IS NOT OLD.raw_byte_size
                  OR NEW.original_filename IS NOT OLD.original_filename
                  OR NEW.original_storage_path IS NOT OLD.original_storage_path
                THEN RAISE(ABORT, 'import_sources raw snapshot is immutable')
            END;
        END;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_import_sources_immutable")
    op.drop_table("import_source_normalized_texts")
    op.drop_index("ix_import_sources_checksum", table_name="import_sources")
    op.drop_table("import_sources")
