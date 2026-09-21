from sqlalchemy.orm import Session

from app.adapters.sqlite.import_sources import (
    create_paste_source,
    get_import_source,
    set_parse_status,
    upsert_normalized_text,
)
from app.adapters.sqlite.models import ImportSource
from app.domain.importing import (
    ImportValidationError,
    ParseStatus,
    PasteImportOutcome,
    normalize_imported_text,
    validate_paste_text,
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


def require_import_source(session: Session, source_id: str) -> ImportSource:
    source = get_import_source(session, source_id)
    if source is None:
        raise ImportValidationError("import_not_found", "Import source was not found.")
    return source
