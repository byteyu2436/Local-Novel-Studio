from datetime import UTC, datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.sqlite.base import Base


class CanonChunk(Base):
    """Official retrieval chunk. Draft text is not stored here."""

    __tablename__ = "canon_chunks"
    __table_args__ = (
        CheckConstraint(
            "source_version_kind IN ('ORIGINAL', 'ACCEPTED')",
            name="ck_canon_chunks_source_kind",
        ),
        CheckConstraint(
            "canon_status IN ('active', 'inactive')",
            name="ck_canon_chunks_status",
        ),
        CheckConstraint("length(text) > 0", name="ck_canon_chunks_text"),
        Index("ix_canon_chunks_novel_id", "novel_id"),
        Index("ix_canon_chunks_chapter_id", "chapter_id"),
        Index(
            "uq_canon_chunks_active_index",
            "chapter_id",
            "source_version_id",
            "chunking_version",
            "chunk_index",
            unique=True,
            sqlite_where=text("canon_status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    novel_id: Mapped[str] = mapped_column(String(36), nullable=False)
    chapter_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_version_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    overlap_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    characters: Mapped[list] = mapped_column(JSON, nullable=False)
    locations: Mapped[list] = mapped_column(JSON, nullable=False)
    event_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    importance: Mapped[str] = mapped_column(String(16), nullable=False)
    canon_status: Mapped[str] = mapped_column(String(16), nullable=False)
    chunking_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def chunk_now() -> datetime:
    return datetime.now(UTC)
