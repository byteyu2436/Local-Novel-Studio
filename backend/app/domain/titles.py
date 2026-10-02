from app.adapters.sqlite.models import Chapter
from app.domain.chapter import TitleSource, fallback_chapter_title
from app.schemas.title import TitleCandidate


def choose_display_title(
    chapter: Chapter, candidates: list[TitleCandidate], *, auto_title: bool
) -> tuple[str, TitleSource, float]:
    """user beats original, original beats generated, and generated needs the switch on."""

    if chapter.title_source == TitleSource.USER.value and chapter.display_title.strip():
        return chapter.display_title, TitleSource.USER, chapter.title_confidence
    if chapter.original_title.strip() or (
        chapter.title_source == TitleSource.ORIGINAL.value and chapter.original_label.strip()
    ):
        title = fallback_chapter_title(
            chapter.sequence,
            original_label=chapter.original_label,
            original_title=chapter.original_title,
        )
        return title, TitleSource.ORIGINAL, 1.0
    if not auto_title or not candidates:
        return (
            fallback_chapter_title(chapter.sequence, original_label=chapter.original_label),
            TitleSource.FALLBACK,
            0.0,
        )
    best = max(candidates, key=lambda item: item.confidence)
    return best.text, TitleSource.GENERATED, best.confidence


def apply_display_title(
    chapter: Chapter, candidates: list[TitleCandidate], *, auto_title: bool
) -> None:
    chapter.title_candidates = [item.model_dump() for item in candidates]
    if chapter.title_source == TitleSource.USER.value:
        return
    text, source, confidence = choose_display_title(chapter, candidates, auto_title=auto_title)
    if source is TitleSource.ORIGINAL:
        return
    chapter.display_title = text
    chapter.title_source = source.value
    chapter.title_confidence = confidence


def set_user_title(chapter: Chapter, title: str) -> None:
    cleaned = title.strip()
    if not cleaned:
        from app.domain.catalog import CatalogError

        raise CatalogError("title_empty", "User title cannot be empty.")
    chapter.display_title = cleaned
    chapter.title_source = TitleSource.USER.value
    chapter.title_confidence = 1.0
