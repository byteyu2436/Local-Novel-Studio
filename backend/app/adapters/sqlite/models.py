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
    Text,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.adapters.sqlite.base import Base
from app.domain.importing import ImportSourceImmutableError, ParseStatus, SourceType

_IMMUTABLE_IMPORT_COLUMNS = (
    "id",
    "source_type",
    "checksum",
    "created_at",
    "raw_text",
    "raw_byte_size",
    "original_filename",
    "original_storage_path",
)


class AppSetting(Base):
    """Key/value local settings stored in SQLite."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class ImportSource(Base):
    """Immutable Original Source for paste text or a retained TXT file."""

    __tablename__ = "import_sources"
    __table_args__ = (
        CheckConstraint(
            f"source_type IN ('{SourceType.PASTE}', '{SourceType.TXT}')",
            name="ck_import_sources_source_type",
        ),
        CheckConstraint(
            "parse_status IN ("
            f"'{ParseStatus.RECEIVED}', '{ParseStatus.NORMALIZED}', '{ParseStatus.FAILED}')",
            name="ck_import_sources_parse_status",
        ),
        CheckConstraint(
            f"(source_type = '{SourceType.PASTE}' AND raw_text IS NOT NULL) OR "
            f"(source_type = '{SourceType.TXT}' AND original_storage_path IS NOT NULL)",
            name="ck_import_sources_payload",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(16), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    original_storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_encoding: Mapped[str | None] = mapped_column(String(16), nullable=True)
    encoding_uncertain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    normalized: Mapped["ImportSourceNormalizedText | None"] = relationship(
        back_populates="import_source",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ImportSourceNormalizedText(Base):
    """Derived normalized copy. Updating it must never rewrite the Raw Snapshot."""

    __tablename__ = "import_source_normalized_texts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    import_source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("import_sources.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    import_source: Mapped[ImportSource] = relationship(back_populates="normalized")


class Novel(Base):
    __tablename__ = "novels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="novel",
        cascade="all, delete-orphan",
        order_by="Chapter.sequence",
    )


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("novel_id", "sequence", name="uq_chapters_novel_sequence"),
        CheckConstraint(
            "title_source IN ('original', 'user', 'generated', 'fallback')",
            name="ck_chapters_title_source",
        ),
        Index("ix_chapters_novel_id", "novel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    original_label: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    original_title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    display_title: Mapped[str] = mapped_column(String(512), nullable=False)
    title_source: Mapped[str] = mapped_column(String(16), nullable=False)
    title_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    current_canon_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chapter_versions.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    import_source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("import_sources.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    novel: Mapped[Novel] = relationship(back_populates="chapters")
    versions: Mapped[list["ChapterVersion"]] = relationship(
        back_populates="chapter",
        cascade="all, delete-orphan",
        foreign_keys="ChapterVersion.chapter_id",
    )
    current_canon: Mapped["ChapterVersion | None"] = relationship(
        foreign_keys=[current_canon_version_id],
        post_update=True,
    )


class ChapterVersion(Base):
    __tablename__ = "chapter_versions"
    __table_args__ = (
        CheckConstraint(
            "version_kind IN ('ORIGINAL', 'DRAFT', 'ACCEPTED')",
            name="ck_chapter_versions_kind",
        ),
        Index("ix_chapter_versions_chapter_id", "chapter_id"),
        Index(
            "uq_chapter_versions_original",
            "chapter_id",
            unique=True,
            sqlite_where=text("version_kind = 'ORIGINAL'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    version_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chapter_versions.id", ondelete="SET NULL"), nullable=True
    )
    superseded_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chapter_versions.id", ondelete="SET NULL"), nullable=True
    )
    import_source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("import_sources.id", ondelete="SET NULL"), nullable=True
    )
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    chapter: Mapped[Chapter] = relationship(back_populates="versions", foreign_keys=[chapter_id])
    analyses: Mapped[list["ChapterAnalysis"]] = relationship(
        back_populates="source_version",
        cascade="all, delete-orphan",
        foreign_keys="ChapterAnalysis.source_version_id",
    )


class ChapterAnalysis(Base):
    """Official per-chapter structured analysis bound to a Canon ChapterVersion."""

    __tablename__ = "chapter_analysis"
    __table_args__ = (
        UniqueConstraint(
            "chapter_id",
            "source_version_id",
            name="uq_chapter_analysis_chapter_source",
        ),
        CheckConstraint(
            "source_version_kind IN ('ORIGINAL', 'ACCEPTED')",
            name="ck_chapter_analysis_source_kind",
        ),
        Index("ix_chapter_analysis_chapter_id", "chapter_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    source_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chapter_versions.id", ondelete="CASCADE"), nullable=False
    )
    source_version_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_profile_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    chapter: Mapped[Chapter] = relationship(foreign_keys=[chapter_id])
    source_version: Mapped[ChapterVersion] = relationship(
        back_populates="analyses",
        foreign_keys=[source_version_id],
    )


@event.listens_for(ImportSource, "before_update")
def reject_raw_snapshot_mutation(_mapper, _connection, target: ImportSource) -> None:
    state = inspect(target)
    changed = [
        name
        for name in _IMMUTABLE_IMPORT_COLUMNS
        if getattr(state.attrs, name).history.has_changes()
    ]
    if changed:
        raise ImportSourceImmutableError(
            f"ImportSource raw snapshot is immutable; refused changes to: {', '.join(changed)}"
        )
