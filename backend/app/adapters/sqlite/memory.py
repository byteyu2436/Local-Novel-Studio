from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.sqlite.base import Base
from app.domain.memory import (
    FACT_ORIGINS,
    FACT_STATUSES,
    FORESHADOWING_STATUSES,
    MEMORY_SUBJECT_KINDS,
)

_SUBJECTS = ", ".join(f"'{item}'" for item in MEMORY_SUBJECT_KINDS)
_FORESHADOW = ", ".join(f"'{item}'" for item in FORESHADOWING_STATUSES)
_ORIGINS = ", ".join(f"'{item}'" for item in FACT_ORIGINS)
_FACT_STATUS = ", ".join(f"'{item}'" for item in FACT_STATUSES)


class MemoryCharacter(Base):
    """Stable character identity. Location, injury, and age live on active facts."""

    __tablename__ = "memory_characters"
    __table_args__ = (Index("ix_memory_characters_novel_id", "novel_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    aliases: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryRelationship(Base):
    __tablename__ = "memory_relationships"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "source_character_id",
            "target_character_id",
            name="uq_memory_relationships_pair",
        ),
        Index("ix_memory_relationships_novel_id", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    source_character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("memory_characters.id", ondelete="CASCADE"), nullable=False
    )
    target_character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("memory_characters.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryEvent(Base):
    __tablename__ = "memory_events"
    __table_args__ = (Index("ix_memory_events_novel_id", "novel_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryTimeline(Base):
    __tablename__ = "memory_timelines"
    __table_args__ = (Index("ix_memory_timelines_novel_id", "novel_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryForeshadowing(Base):
    __tablename__ = "memory_foreshadowings"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_FORESHADOW})",
            name="ck_memory_foreshadowings_status",
        ),
        Index("ix_memory_foreshadowings_novel_id", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryWorldFact(Base):
    __tablename__ = "memory_world_facts"
    __table_args__ = (Index("ix_memory_world_facts_novel_id", "novel_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryStyleProfile(Base):
    """Style features and counts only. Chapter prose is not copied here."""

    __tablename__ = "memory_style_profiles"
    __table_args__ = (
        UniqueConstraint("novel_id", name="uq_memory_style_profiles_novel"),
        Index("ix_memory_style_profiles_novel_id", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    statistics: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryFact(Base):
    """Mutable state revision. Current entity state is the active row, not a second copy."""

    __tablename__ = "memory_facts"
    __table_args__ = (
        UniqueConstraint(
            "subject_kind",
            "subject_id",
            "fact_key",
            "revision",
            name="uq_memory_facts_revision",
        ),
        CheckConstraint(f"subject_kind IN ({_SUBJECTS})", name="ck_memory_facts_subject_kind"),
        CheckConstraint(f"origin IN ({_ORIGINS})", name="ck_memory_facts_origin"),
        CheckConstraint(f"status IN ({_FACT_STATUS})", name="ck_memory_facts_status"),
        CheckConstraint(
            "(active = 1 AND status = 'active') OR (active = 0 AND status = 'superseded')",
            name="ck_memory_facts_active_status",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memory_facts_confidence"),
        CheckConstraint(
            "("
            "origin = 'explicit' AND source_start_offset IS NOT NULL "
            "AND source_end_offset IS NOT NULL AND source_text_hash IS NOT NULL"
            ") OR ("
            "origin = 'inferred' AND source_start_offset IS NULL "
            "AND source_end_offset IS NULL AND source_text_hash IS NULL"
            ")",
            name="ck_memory_facts_origin_span",
        ),
        Index("ix_memory_facts_novel_id", "novel_id"),
        Index("ix_memory_facts_source_version", "source_chapter_version_id"),
        Index("ix_memory_facts_subject", "subject_kind", "subject_id"),
        Index(
            "uq_memory_facts_active_key",
            "subject_kind",
            "subject_id",
            "fact_key",
            unique=True,
            sqlite_where=text("active = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(64), nullable=False)
    fact_value: Mapped[dict] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="inferred")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_chapter_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True
    )
    source_chapter_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chapter_versions.id", ondelete="SET NULL"), nullable=True
    )
    source_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_chunk_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class MemoryNamedEntity(Base):
    """Location or organization identity. Characters stay on memory_characters."""

    __tablename__ = "memory_named_entities"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('location', 'organization')",
            name="ck_memory_named_entities_kind",
        ),
        Index("ix_memory_named_entities_novel_id", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    aliases: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EntityResolutionRecord(Base):
    __tablename__ = "entity_resolution_records"
    __table_args__ = (
        CheckConstraint(
            "entity_kind IN ('character', 'location', 'organization')",
            name="ck_entity_resolutions_kind",
        ),
        CheckConstraint(
            "decision IN ('merged', 'created', 'candidate')",
            name="ck_entity_resolutions_decision",
        ),
        Index("ix_entity_resolutions_novel_id", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    entity_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    mention_name: Mapped[str] = mapped_column(String(256), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    candidate_entity_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    source_chapter_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_chapter_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryReduceApplication(Base):
    """A Canon chapter version already folded into Novel Memory."""

    __tablename__ = "memory_reduce_applications"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "source_chapter_version_id",
            name="uq_memory_reduce_applications_version",
        ),
        Index("ix_memory_reduce_applications_novel_id", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    source_chapter_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_chapter_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NovelMemoryRevision(Base):
    """Novel-level memory revision. Entity tables do not store a second mutable state."""

    __tablename__ = "novel_memory_revisions"

    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryConflict(Base):
    """An explicit fact contradiction. Reduce must not overwrite the existing fact."""

    __tablename__ = "memory_conflicts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')",
            name="ck_memory_conflicts_status",
        ),
        CheckConstraint(
            "resolution IS NULL OR resolution IN "
            "('keep_existing', 'accept_incoming', 'edit', 'dismiss')",
            name="ck_memory_conflicts_resolution",
        ),
        Index("ix_memory_conflicts_novel_id", "novel_id"),
        Index("ix_memory_conflicts_existing_fact", "existing_fact_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    existing_fact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("memory_facts.id", ondelete="CASCADE"), nullable=False
    )
    existing_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    existing_value: Mapped[dict] = mapped_column(JSON, nullable=False)
    existing_source_chapter_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    existing_source_chapter_version_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    incoming_value: Mapped[dict] = mapped_column(JSON, nullable=False)
    incoming_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    incoming_source_chapter_id: Mapped[str] = mapped_column(String(36), nullable=False)
    incoming_source_chapter_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryOperationLog(Base):
    __tablename__ = "memory_operation_logs"
    __table_args__ = (Index("ix_memory_operation_logs_novel_id", "novel_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    before_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    after_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemorySnapshot(Base):
    """Revision anchor. The snapshot does not copy the memory rows themselves."""

    __tablename__ = "memory_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "accepted_chapter_id",
            "memory_revision",
            name="uq_memory_snapshots_anchor",
        ),
        Index("ix_memory_snapshots_novel_id", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    accepted_chapter_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    memory_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
