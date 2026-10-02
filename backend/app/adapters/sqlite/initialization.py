from datetime import UTC, datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.sqlite.base import Base

INIT_STATES = ("queued", "running", "paused", "failed", "completed", "cancelled")
INIT_PHASES = (
    "analysis",
    "memory_reduce",
    "chunk",
    "embedding",
    "index_validate_activate",
    "ready",
)


class NovelInitializationRun(Base):
    """One initialization operation for a novel. Ready is not implied by a partial run."""

    __tablename__ = "novel_initialization_runs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued', 'running', 'paused', 'failed', 'completed', 'cancelled')",
            name="ck_init_runs_state",
        ),
        CheckConstraint(
            "current_phase IN ("
            "'analysis', 'memory_reduce', 'chunk', 'embedding', "
            "'index_validate_activate', 'ready')",
            name="ck_init_runs_phase",
        ),
        Index("uq_init_runs_novel", "novel_id", unique=True),
        Index(
            "uq_init_runs_active",
            "novel_id",
            unique=True,
            sqlite_where=text("state IN ('queued', 'running', 'paused')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(String(36), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    current_phase: Mapped[str] = mapped_column(String(32), nullable=False)
    child_job_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    progress_done: Mapped[int] = mapped_column(Integer, nullable=False)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False)
    checkpoint: Mapped[dict] = mapped_column(JSON, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    index_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def init_now() -> datetime:
    return datetime.now(UTC)
