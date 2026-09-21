from sqlalchemy.orm import Session

from app.adapters.sqlite.models import ImportSource
from app.domain.chapter_candidate import (
    DetectionResult,
    candidate_preview,
    candidates_from_detection,
    slice_normalized_text,
)
from app.domain.chapter_detect import ChapterDetector, detect_chapter_structure
from app.domain.importing import ImportValidationError, ParseStatus
from app.services.importer import require_import_source


def _normalized_source(session: Session, source_id: str) -> tuple[ImportSource, str]:
    source = require_import_source(session, source_id)
    if source.parse_status != ParseStatus.NORMALIZED.value or source.normalized is None:
        raise ImportValidationError(
            "import_normalized_unavailable",
            "Normalized text is not available for chapter detection.",
        )
    return source, source.normalized.text


def detect_import_chapters(
    session: Session,
    source_id: str,
    detector: ChapterDetector | None = None,
) -> DetectionResult:
    """Build a DetectionResult from ImportSource. Never creates Chapter records."""

    source, text = _normalized_source(session, source_id)
    detection = detect_chapter_structure(text, detector=detector)
    candidates, warnings = candidates_from_detection(text, detection)
    return DetectionResult(
        import_source_id=source.id,
        checksum=source.checksum,
        classification=detection.shape,
        candidates=candidates,
        warnings=warnings,
        normalized_char_count=len(text),
    )


def preview_candidate_text(session: Session, source_id: str, start: int, end: int) -> str:
    _source, text = _normalized_source(session, source_id)
    return slice_normalized_text(text, start, end)


def candidate_preview_for(text: str, start: int, end: int) -> str:
    return candidate_preview(text, start, end)
