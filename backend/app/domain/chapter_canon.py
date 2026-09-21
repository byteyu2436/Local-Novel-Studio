from uuid import uuid4

from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.chapter import VersionKind


class ChapterCanonError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def require_version_for_chapter(chapter: Chapter, version: ChapterVersion) -> None:
    if version.chapter_id != chapter.id:
        raise ChapterCanonError(
            "version_chapter_mismatch",
            "Version does not belong to this chapter.",
        )


def set_canon_pointer(chapter: Chapter, version: ChapterVersion) -> None:
    """Point Canon at ORIGINAL or ACCEPTED. Draft cannot become Canon."""

    require_version_for_chapter(chapter, version)
    if version.version_kind == VersionKind.DRAFT.value:
        raise ChapterCanonError(
            "draft_cannot_be_canon",
            "A Draft version cannot be the current Canon.",
        )
    if version.version_kind not in {VersionKind.ORIGINAL.value, VersionKind.ACCEPTED.value}:
        raise ChapterCanonError("invalid_version_kind", "Unsupported version kind.")
    chapter.current_canon_version_id = version.id


def add_draft_version(
    chapter: Chapter,
    *,
    body: str,
    parent: ChapterVersion | None,
    created_at,
) -> ChapterVersion:
    if parent is not None:
        require_version_for_chapter(chapter, parent)
    draft = ChapterVersion(
        id=str(uuid4()),
        chapter_id=chapter.id,
        version_kind=VersionKind.DRAFT.value,
        body=body,
        parent_version_id=None if parent is None else parent.id,
        created_at=created_at,
    )
    chapter.versions.append(draft)
    return draft


def make_accepted_from_draft(
    chapter: Chapter,
    draft: ChapterVersion,
    *,
    created_at,
) -> ChapterVersion:
    require_version_for_chapter(chapter, draft)
    if draft.version_kind != VersionKind.DRAFT.value:
        raise ChapterCanonError("accept_requires_draft", "Only a Draft version can be accepted.")
    return ChapterVersion(
        id=str(uuid4()),
        chapter_id=chapter.id,
        version_kind=VersionKind.ACCEPTED.value,
        body=draft.body,
        parent_version_id=draft.id,
        created_at=created_at,
    )


def mark_superseded(previous: ChapterVersion, replacement: ChapterVersion) -> None:
    if previous.version_kind != VersionKind.ACCEPTED.value:
        return
    if previous.id == replacement.id:
        raise ChapterCanonError("invalid_supersede", "A version cannot supersede itself.")
    previous.superseded_by_id = replacement.id
