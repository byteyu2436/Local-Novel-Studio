from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.sqlite.base import Base

PLAN_STATUSES = ("draft", "generated", "edited", "confirmed", "superseded")
DRAFT_ORIGINS = ("generated", "user", "rewrite")
ISSUE_SEVERITIES = ("info", "warning", "blocking")


def continuation_now() -> datetime:
    return datetime.now(UTC)


class ChapterPlanVersion(Base):
    __tablename__ = "chapter_plan_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'generated', 'edited', 'confirmed', 'superseded')",
            name="ck_plan_versions_status",
        ),
        Index("ix_plan_versions_novel", "novel_id", "target_sequence"),
        Index(
            "uq_plan_confirmed_pointer",
            "novel_id",
            "target_sequence",
            unique=True,
            sqlite_where=text("is_confirmed_pointer = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    target_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    chapter_goal: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    profile_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    context_checksum: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_confirmed_pointer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DraftVersion(Base):
    __tablename__ = "draft_versions"
    __table_args__ = (
        CheckConstraint(
            "origin IN ('generated', 'user', 'rewrite')",
            name="ck_draft_versions_origin",
        ),
        Index("ix_draft_versions_novel", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    target_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConsistencyIssueRecord(Base):
    __tablename__ = "consistency_issues"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'warning', 'blocking')",
            name="ck_consistency_issues_severity",
        ),
        Index("ix_consistency_issues_draft", "draft_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    draft_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("draft_versions.id", ondelete="CASCADE"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AcceptOperation(Base):
    __tablename__ = "accept_operations"
    __table_args__ = (
        Index("uq_accept_operations_draft", "draft_id", unique=True),
        Index("ix_accept_operations_novel", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    draft_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("draft_versions.id", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(36), nullable=False)
    memory_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    index_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
