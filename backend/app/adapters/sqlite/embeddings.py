from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.sqlite.base import Base


def embedding_now() -> datetime:
    return datetime.now(UTC)


class EmbeddingProfileRecord(Base):
    """One semantic space. Vectors from another profile must not be written here."""

    __tablename__ = "embedding_profiles"
    __table_args__ = (
        CheckConstraint(
            "normalization IN ('none', 'l2')",
            name="ck_embedding_profiles_normalization",
        ),
        CheckConstraint("dimension > 0", name="ck_embedding_profiles_dimension"),
        Index(
            "uq_embedding_profiles_active",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    embedding_model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_model_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    normalization: Mapped[str] = mapped_column(String(16), nullable=False)
    chunking_version: Mapped[str] = mapped_column(String(64), nullable=False)
    index_version: Mapped[str] = mapped_column(String(64), nullable=False)
    rebuild_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready', 'failed')",
            name="ck_chunk_embeddings_status",
        ),
        Index(
            "uq_chunk_embeddings_chunk_profile",
            "chunk_id",
            "profile_id",
            unique=True,
        ),
        Index("ix_chunk_embeddings_novel_id", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(64), nullable=False)
    novel_id: Mapped[str] = mapped_column(String(36), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    text_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vector: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    batch_no: Mapped[int] = mapped_column(Integer, nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
