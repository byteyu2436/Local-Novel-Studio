from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.sqlite.base import Base


def registry_now() -> datetime:
    return datetime.now(UTC)


class IndexVersionRecord(Base):
    """Which Milvus collection retrieval is allowed to read."""

    __tablename__ = "index_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('building', 'validating', 'active', 'failed', 'superseded', 'retired')",
            name="ck_index_versions_status",
        ),
        CheckConstraint("record_count >= 0", name="ck_index_versions_record_count"),
        Index(
            "uq_index_versions_active",
            "status",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    collection_name: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chunking_version: Mapped[str] = mapped_column(String(64), nullable=False)
    index_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
