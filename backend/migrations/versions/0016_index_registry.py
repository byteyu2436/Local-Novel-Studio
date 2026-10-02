"""Active Milvus index version registry.

Revision ID: 0016_index_registry
Revises: 0015_embedding_profile
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_index_registry"
down_revision: str | None = "0015_embedding_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "index_versions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("collection_name", sa.String(length=255), nullable=False),
        sa.Column("embedding_profile_id", sa.String(length=64), nullable=False),
        sa.Column("chunking_version", sa.String(length=64), nullable=False),
        sa.Column("index_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("manifest_checksum", sa.String(length=64), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('building', 'validating', 'active', 'failed', 'superseded', 'retired')",
            name="ck_index_versions_status",
        ),
        sa.CheckConstraint("record_count >= 0", name="ck_index_versions_record_count"),
    )
    op.create_index(
        "uq_index_versions_active",
        "index_versions",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_index_versions_active", table_name="index_versions")
    op.drop_table("index_versions")
