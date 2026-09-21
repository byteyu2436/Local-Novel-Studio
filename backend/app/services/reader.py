from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.chapter import VersionKind
from app.services.catalog import list_chapters, require_novel


@dataclass(frozen=True, slots=True)
class ChapterTocItem:
    chapter_id: str
    sequence: int
    original_label: str
    display_title: str
    title_source: str
    canon_version_id: str | None
    canon_kind: str | None
    has_draft: bool


def _canon_kind(chapter: Chapter) -> str | None:
    if chapter.current_canon_version_id is None:
        return None
    for version in chapter.versions:
        if version.id == chapter.current_canon_version_id:
            if version.version_kind == VersionKind.DRAFT.value:
                return None
            return version.version_kind
    return None


def _has_draft(chapter: Chapter) -> bool:
    return any(item.version_kind == VersionKind.DRAFT.value for item in chapter.versions)


def novel_chapter_toc(
    session: Session, novel_id: str
) -> tuple[str, str, tuple[ChapterTocItem, ...]]:
    """Read-only chapter directory. Drafts are flags, never the Canon kind."""

    novel = require_novel(session, novel_id)
    items = tuple(
        ChapterTocItem(
            chapter_id=chapter.id,
            sequence=chapter.sequence,
            original_label=chapter.original_label,
            display_title=chapter.display_title,
            title_source=chapter.title_source,
            canon_version_id=chapter.current_canon_version_id,
            canon_kind=_canon_kind(chapter),
            has_draft=_has_draft(chapter),
        )
        for chapter in list_chapters(session, novel.id)
    )
    return novel.id, novel.title, items


def require_canon_version(chapter: Chapter) -> ChapterVersion | None:
    if chapter.current_canon_version_id is None:
        return None
    for version in chapter.versions:
        if version.id != chapter.current_canon_version_id:
            continue
        if version.version_kind == VersionKind.DRAFT.value:
            return None
        return version
    return None
