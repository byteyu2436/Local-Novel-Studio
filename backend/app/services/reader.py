from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.catalog import CatalogError
from app.domain.chapter import VersionKind
from app.services.catalog import list_chapters, require_chapter, require_novel


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


def require_canon_version(chapter: Chapter) -> ChapterVersion:
    if chapter.current_canon_version_id is None:
        raise CatalogError("canon_missing", "Chapter has no readable Canon version.")
    for version in chapter.versions:
        if version.id != chapter.current_canon_version_id:
            continue
        if version.version_kind == VersionKind.DRAFT.value:
            raise CatalogError("canon_missing", "Chapter has no readable Canon version.")
        return version
    raise CatalogError("canon_missing", "Chapter has no readable Canon version.")


@dataclass(frozen=True, slots=True)
class ChapterNav:
    chapter_id: str
    sequence: int
    display_title: str


@dataclass(frozen=True, slots=True)
class CanonChapterRead:
    novel_id: str
    chapter_id: str
    sequence: int
    original_label: str
    original_title: str
    display_title: str
    title_source: str
    body: str
    version_id: str
    version_kind: str
    is_canon: bool
    has_draft: bool
    previous: ChapterNav | None
    next: ChapterNav | None


def _nav_for(chapter: Chapter) -> ChapterNav:
    return ChapterNav(
        chapter_id=chapter.id,
        sequence=chapter.sequence,
        display_title=chapter.display_title,
    )


def read_canon_chapter(session: Session, chapter_id: str) -> CanonChapterRead:
    """Read the current Canon body. Unaccepted Drafts are never returned as body."""

    chapter = require_chapter(session, chapter_id)
    siblings = list_chapters(session, chapter.novel_id)
    index = next(i for i, item in enumerate(siblings) if item.id == chapter.id)
    current = siblings[index]
    canon = require_canon_version(current)
    previous = _nav_for(siblings[index - 1]) if index > 0 else None
    nxt = _nav_for(siblings[index + 1]) if index < len(siblings) - 1 else None
    return CanonChapterRead(
        novel_id=current.novel_id,
        chapter_id=current.id,
        sequence=current.sequence,
        original_label=current.original_label,
        original_title=current.original_title,
        display_title=current.display_title,
        title_source=current.title_source,
        body=canon.body,
        version_id=canon.id,
        version_kind=canon.version_kind,
        is_canon=True,
        has_draft=_has_draft(current),
        previous=previous,
        next=nxt,
    )
