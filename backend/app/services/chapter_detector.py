from sqlalchemy.orm import Session

from app.adapters.sqlite.models import ImportSource
from app.domain.chapter_detect import (
    ChapterDetection,
    ChapterDetector,
    detect_chapter_structure,
)
from app.domain.importing import ImportValidationError, ParseStatus
from app.services.importer import require_import_source


def detect_import_chapters(
    session: Session,
    source_id: str,
    detector: ChapterDetector | None = None,
) -> tuple[ImportSource, ChapterDetection]:
    """Classify an ImportSource. Never creates Chapter records."""

    source = require_import_source(session, source_id)
    if source.parse_status != ParseStatus.NORMALIZED.value or source.normalized is None:
        raise ImportValidationError(
            "import_normalized_unavailable",
            "Normalized text is not available for chapter detection.",
        )
    return source, detect_chapter_structure(source.normalized.text, detector=detector)
