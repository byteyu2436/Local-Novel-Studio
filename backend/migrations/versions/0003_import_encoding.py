"""Add detected encoding fields to import_sources.

Revision ID: 0003_import_encoding
Revises: 0002_import_sources
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_import_encoding"
down_revision: str | None = "0002_import_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("import_sources") as batch:
        batch.add_column(sa.Column("detected_encoding", sa.String(length=16), nullable=True))
        batch.add_column(
            sa.Column(
                "encoding_uncertain",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_import_sources_immutable
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
    with op.batch_alter_table("import_sources") as batch:
        batch.drop_column("encoding_uncertain")
        batch.drop_column("detected_encoding")
