from sqlalchemy.orm import Session

from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.chapter_canon import (
    make_accepted_from_draft,
    mark_superseded,
    set_canon_pointer,
)


def persist_accepted_canon(
    session: Session,
    chapter: Chapter,
    draft: ChapterVersion,
    *,
    created_at,
) -> ChapterVersion:
    """Insert ACCEPTED first, then move the Canon pointer. Original is not updated."""

    current = (
        session.get(ChapterVersion, chapter.current_canon_version_id)
        if chapter.current_canon_version_id
        else None
    )
    accepted = make_accepted_from_draft(chapter, draft, created_at=created_at)
    session.add(accepted)
    session.flush()
    if current is not None:
        mark_superseded(current, accepted)
    set_canon_pointer(chapter, accepted)
    session.flush()
    return accepted
