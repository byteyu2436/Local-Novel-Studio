from uuid import uuid4

from sqlalchemy.orm import Session

from app.adapters.sqlite.import_sources import (
    create_paste_source,
    create_txt_source,
    get_import_source,
    set_parse_status,
    upsert_normalized_text,
)
from app.adapters.sqlite.models import ImportSource
from app.domain.importing import (
    TXT_PREVIEW_CHARS,
    ImportValidationError,
    ParseStatus,
    PasteImportOutcome,
    TxtImportOutcome,
    TxtPreviewOutcome,
    normalize_imported_text,
    validate_paste_text,
    validate_txt_filename,
)
from app.domain.txt_encoding import TxtDecodeResult, decode_txt_bytes
from app.settings import Settings
from app.storage.imports import (
    TXT_MAX_BYTES,
    original_txt_path,
    remove_original_txt,
    write_original_txt,
)


def import_pasted_text(session: Session, text: str) -> PasteImportOutcome:
    """Persist an immutable paste snapshot, then a derived normalized copy.

    The original snapshot is committed before derived text is written so a later
    normalize/write failure cannot erase Original Source.
    """

    validate_paste_text(text)
    source = create_paste_source(session, text)
    session.commit()
    source_id = source.id
    try:
        stored = get_import_source(session, source_id)
        if stored is None:
            raise RuntimeError("Paste snapshot disappeared after commit.")
        upsert_normalized_text(session, stored, normalize_imported_text(text))
        session.commit()
    except Exception as exc:
        session.rollback()
        stored = get_import_source(session, source_id)
        if stored is not None:
            set_parse_status(session, stored, ParseStatus.FAILED)
            session.commit()
        return PasteImportOutcome(
            source_id=source_id,
            parse_status=ParseStatus.FAILED,
            error_code="import_normalize_failed",
            error_message=str(exc.__class__.__name__),
        )
    return PasteImportOutcome(source_id=source_id, parse_status=ParseStatus.NORMALIZED)


def _decode_txt_payload(
    *,
    filename: str,
    payload: bytes,
    encoding: str | None,
) -> tuple[str, TxtDecodeResult]:
    safe_name = validate_txt_filename(filename)
    if len(payload) > TXT_MAX_BYTES:
        raise ImportValidationError(
            "txt_too_large",
            f"TXT file exceeds the {TXT_MAX_BYTES} byte limit.",
        )
    decoded = decode_txt_bytes(payload, encoding=encoding)
    if not decoded.ok or decoded.normalized_text is None:
        raise ImportValidationError(
            decoded.error_code or "txt_decode_failed",
            decoded.error_message or "The TXT file could not be decoded.",
        )
    return safe_name, decoded


def preview_txt_file(
    *,
    filename: str,
    payload: bytes,
    encoding: str | None = None,
) -> TxtPreviewOutcome:
    """Decode a TXT for UI preview without writing Original Source."""

    safe_name, decoded = _decode_txt_payload(
        filename=filename,
        payload=payload,
        encoding=encoding,
    )
    text = decoded.normalized_text or ""
    truncated = len(text) > TXT_PREVIEW_CHARS
    return TxtPreviewOutcome(
        original_filename=safe_name,
        raw_byte_size=len(payload),
        detected_encoding=decoded.encoding,
        encoding_uncertain=decoded.uncertain,
        preview_text=text[:TXT_PREVIEW_CHARS],
        preview_truncated=truncated,
        char_count=len(text),
    )


def import_txt_file(
    session: Session,
    settings: Settings,
    *,
    filename: str,
    payload: bytes,
    encoding: str | None = None,
) -> TxtImportOutcome:
    """Persist original TXT bytes, then a derived normalized copy."""

    safe_name, decoded = _decode_txt_payload(
        filename=filename,
        payload=payload,
        encoding=encoding,
    )

    source_id = str(uuid4())
    try:
        relative = write_original_txt(
            settings,
            source_id=source_id,
            filename=safe_name,
            payload=payload,
        )
    except OSError as exc:
        raise ImportValidationError(
            "txt_persist_failed",
            "Could not save the original TXT file.",
        ) from exc
    try:
        create_txt_source(
            session,
            source_id=source_id,
            original_filename=safe_name,
            original_storage_path=relative,
            raw_bytes=payload,
            detected_encoding=decoded.encoding,
            encoding_uncertain=decoded.uncertain,
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        remove_original_txt(settings, relative)
        raise ImportValidationError(
            "txt_persist_failed",
            "Could not record the original TXT file.",
        ) from exc

    try:
        stored = get_import_source(session, source_id)
        if stored is None:
            raise RuntimeError("TXT snapshot disappeared after commit.")
        upsert_normalized_text(session, stored, decoded.normalized_text)
        session.commit()
    except Exception as exc:
        session.rollback()
        stored = get_import_source(session, source_id)
        if stored is not None:
            set_parse_status(session, stored, ParseStatus.FAILED)
            session.commit()
        return TxtImportOutcome(
            source_id=source_id,
            parse_status=ParseStatus.FAILED,
            error_code="import_normalize_failed",
            error_message=str(exc.__class__.__name__),
        )
    return TxtImportOutcome(source_id=source_id, parse_status=ParseStatus.NORMALIZED)


def original_txt_bytes(settings: Settings, source: ImportSource) -> bytes:
    if source.original_storage_path is None:
        raise ImportValidationError("txt_file_unavailable", "This import has no original TXT file.")
    path = original_txt_path(settings, source.original_storage_path)
    if not path.is_file():
        raise ImportValidationError("txt_file_missing", "The original TXT file is missing.")
    return path.read_bytes()


def require_import_source(session: Session, source_id: str) -> ImportSource:
    source = get_import_source(session, source_id)
    if source is None:
        raise ImportValidationError("import_not_found", "Import source was not found.")
    return source
