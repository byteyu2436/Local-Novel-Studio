from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.sqlite.models import ImportSource, ImportSourceNormalizedText
from app.domain.importing import ParseStatus, SourceType, sha256_hex


def create_paste_source(session: Session, raw_text: str) -> ImportSource:
    payload = raw_text.encode("utf-8")
    source = ImportSource(
        id=str(uuid4()),
        source_type=SourceType.PASTE.value,
        checksum=sha256_hex(payload),
        created_at=datetime.now(UTC),
        parse_status=ParseStatus.RECEIVED.value,
        original_filename=None,
        original_storage_path=None,
        raw_text=raw_text,
        raw_byte_size=len(payload),
        detected_encoding=None,
        encoding_uncertain=False,
    )
    session.add(source)
    session.flush()
    return source


def create_txt_source(
    session: Session,
    *,
    source_id: str,
    original_filename: str,
    original_storage_path: str,
    raw_bytes: bytes,
    detected_encoding: str | None,
    encoding_uncertain: bool = False,
) -> ImportSource:
    source = ImportSource(
        id=source_id,
        source_type=SourceType.TXT.value,
        checksum=sha256_hex(raw_bytes),
        created_at=datetime.now(UTC),
        parse_status=ParseStatus.RECEIVED.value,
        original_filename=original_filename,
        original_storage_path=original_storage_path,
        raw_text=None,
        raw_byte_size=len(raw_bytes),
        detected_encoding=detected_encoding,
        encoding_uncertain=encoding_uncertain,
    )
    session.add(source)
    session.flush()
    return source


def get_import_source(session: Session, source_id: str) -> ImportSource | None:
    return session.get(ImportSource, source_id)


def set_parse_status(session: Session, source: ImportSource, status: ParseStatus) -> ImportSource:
    source.parse_status = status.value
    session.flush()
    return source


def upsert_normalized_text(
    session: Session,
    source: ImportSource,
    text: str,
    *,
    version: str = "v1",
) -> ImportSourceNormalizedText:
    now = datetime.now(UTC)
    existing = session.scalar(
        select(ImportSourceNormalizedText).where(
            ImportSourceNormalizedText.import_source_id == source.id
        )
    )
    if existing is None:
        existing = ImportSourceNormalizedText(
            id=str(uuid4()),
            import_source_id=source.id,
            text=text,
            normalization_version=version,
            created_at=now,
            updated_at=now,
        )
        session.add(existing)
    else:
        existing.text = text
        existing.normalization_version = version
        existing.updated_at = now
    source.parse_status = ParseStatus.NORMALIZED.value
    session.flush()
    return existing
