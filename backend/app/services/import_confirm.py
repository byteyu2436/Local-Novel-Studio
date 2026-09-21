from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.sqlite.models import Chapter, ImportSource
from app.domain.chapter_candidate import (
    ChapterCandidate,
    slice_normalized_text,
    validate_candidates,
)
from app.domain.chapter_detect import ChapterShape
from app.domain.importing import ImportValidationError, ParseStatus
from app.services.catalog import (
    chapter_provenance,
    create_chapter,
    create_novel,
    next_sequence,
    require_novel,
)
from app.services.importer import require_import_source


@dataclass(frozen=True, slots=True)
class ConfirmedChapter:
    chapter_id: str
    sequence: int
    display_title: str
    start_offset: int | None
    end_offset: int | None


@dataclass(frozen=True, slots=True)
class ImportConfirmOutcome:
    import_source_id: str
    novel_id: str
    novel_title: str
    destination: str
    idempotent: bool
    chapters: tuple[ConfirmedChapter, ...]


def _normalized_text(source: ImportSource) -> str:
    if source.parse_status != ParseStatus.NORMALIZED.value or source.normalized is None:
        raise ImportValidationError(
            "import_normalized_unavailable",
            "Normalized text is not available for import confirm.",
        )
    return source.normalized.text


def _chapters_for_source(session: Session, source_id: str) -> list[Chapter]:
    return list(
        session.scalars(
            select(Chapter)
            .where(Chapter.import_source_id == source_id)
            .order_by(Chapter.sequence, Chapter.id)
        )
    )


def _outcome_from_existing(
    session: Session,
    source: ImportSource,
    chapters: list[Chapter],
    destination: str,
) -> ImportConfirmOutcome:
    novel = require_novel(session, chapters[0].novel_id)
    return ImportConfirmOutcome(
        import_source_id=source.id,
        novel_id=novel.id,
        novel_title=novel.title,
        destination=destination,
        idempotent=True,
        chapters=tuple(
            ConfirmedChapter(
                chapter_id=item.id,
                sequence=item.sequence,
                display_title=item.display_title,
                start_offset=chapter_provenance(session, item.id).start_offset,
                end_offset=chapter_provenance(session, item.id).end_offset,
            )
            for item in chapters
        ),
    )


def _assign_sequences(candidates: tuple[ChapterCandidate, ...], existing_max: int) -> list[int]:
    requested = [item.sequence for item in candidates]
    if any(value < 1 for value in requested) or len(set(requested)) != len(requested):
        raise ImportValidationError(
            "chapter_sequence_invalid",
            "Confirmed chapter sequences must be unique integers >= 1.",
        )
    if existing_max > 0 and min(requested) <= existing_max:
        delta = existing_max + 1 - min(requested)
        return [value + delta for value in requested]
    return requested


def _default_novel_title(source: ImportSource, candidates: tuple[ChapterCandidate, ...]) -> str:
    for item in candidates:
        title = item.title_candidate.strip() or item.original_label.strip()
        if title:
            return title
    filename = (source.original_filename or "").strip()
    if filename:
        return filename.rsplit(".", 1)[0] or filename
    return "未命名小说"


def confirm_import(
    session: Session,
    source_id: str,
    *,
    checksum: str,
    destination: str,
    candidates: tuple[ChapterCandidate, ...],
    novel_id: str | None = None,
    novel_title: str | None = None,
    unstructured_ack: bool = False,
    classification: ChapterShape | str | None = None,
) -> ImportConfirmOutcome:
    """Persist confirmed candidates as Original chapters in one transaction.

    Callers must commit/rollback the session. A failure after the first chapter
    must not leave a partial Novel/Chapter set.
    """

    source = require_import_source(session, source_id)
    text = _normalized_text(source)
    if checksum != source.checksum:
        raise ImportValidationError(
            "import_checksum_mismatch",
            "Confirm checksum does not match the ImportSource snapshot.",
        )
    if not candidates:
        raise ImportValidationError("confirm_empty", "There are no chapters to confirm.")
    shape = ChapterShape(classification) if classification else candidates[0].classification
    if shape is ChapterShape.UNSTRUCTURED and not unstructured_ack:
        raise ImportValidationError(
            "unstructured_ack_required",
            "Unstructured imports must be acknowledged before confirm.",
        )
    if destination not in {"new_novel", "append"}:
        raise ImportValidationError("confirm_destination_invalid", "Unknown confirm destination.")

    existing = _chapters_for_source(session, source.id)
    if existing:
        return _outcome_from_existing(session, source, existing, destination)

    validate_candidates(text, candidates)
    if destination == "append":
        if not novel_id or not novel_id.strip():
            raise ImportValidationError(
                "confirm_novel_required",
                "Appending chapters requires an existing novel_id.",
            )
        novel = require_novel(session, novel_id.strip())
        existing_max = next_sequence(session, novel.id) - 1
    else:
        title = (novel_title or "").strip() or _default_novel_title(source, candidates)
        novel = create_novel(session, title)
        existing_max = 0

    sequences = _assign_sequences(candidates, existing_max)
    created: list[ConfirmedChapter] = []
    for sequence, candidate in zip(sequences, candidates, strict=True):
        body = slice_normalized_text(text, candidate.start_offset, candidate.end_offset)
        chapter = create_chapter(
            session,
            novel.id,
            body=body,
            sequence=sequence,
            original_label=candidate.original_label,
            original_title=candidate.title_candidate,
            import_source_id=source.id,
            start_offset=candidate.start_offset,
            end_offset=candidate.end_offset,
            source_checksum=source.checksum,
        )
        created.append(
            ConfirmedChapter(
                chapter_id=chapter.id,
                sequence=chapter.sequence,
                display_title=chapter.display_title,
                start_offset=candidate.start_offset,
                end_offset=candidate.end_offset,
            )
        )
    return ImportConfirmOutcome(
        import_source_id=source.id,
        novel_id=novel.id,
        novel_title=novel.title,
        destination=destination,
        idempotent=False,
        chapters=tuple(created),
    )
