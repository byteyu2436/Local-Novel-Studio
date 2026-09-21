from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, event, inspect
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
