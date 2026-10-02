from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.sqlite.memory import MemorySnapshot
from app.adapters.sqlite.models import Chapter
from app.domain.memory import MemoryError
from app.services import catalog
from app.services.memory_repository import MemoryRepository


def create_memory_snapshot(session: Session, novel_id: str, chapter_id: str) -> MemorySnapshot:
    """Anchor the current memory revision to a Canon chapter. Repeats return the same row."""

    catalog.require_novel(session, novel_id)
    chapter = catalog.require_chapter(session, chapter_id)
    if chapter.novel_id != novel_id:
        raise MemoryError("snapshot_chapter_mismatch", "Snapshot chapter belongs to another novel.")
    revision = MemoryRepository(session).memory_revision(novel_id)
    found = session.scalar(
        select(MemorySnapshot).where(
            MemorySnapshot.novel_id == novel_id,
            MemorySnapshot.accepted_chapter_id == chapter.id,
            MemorySnapshot.memory_revision == revision,
        )
    )
    if found is not None:
        return found
    row = MemorySnapshot(
        id=str(uuid4()),
        novel_id=novel_id,
        accepted_chapter_id=chapter.id,
        memory_revision=revision,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def get_memory_snapshot(session: Session, snapshot_id: str) -> MemorySnapshot:
    row = session.get(MemorySnapshot, snapshot_id)
    if row is None:
        raise MemoryError("snapshot_not_found", "Memory snapshot does not exist.")
    return row


def list_memory_snapshots(session: Session, novel_id: str) -> list[MemorySnapshot]:
    catalog.require_novel(session, novel_id)
    return list(
        session.scalars(
            select(MemorySnapshot)
            .where(MemorySnapshot.novel_id == novel_id)
            .order_by(MemorySnapshot.memory_revision, MemorySnapshot.created_at)
        )
    )


def latest_memory_snapshot(session: Session, novel_id: str) -> MemorySnapshot | None:
    catalog.require_novel(session, novel_id)
    return session.scalar(
        select(MemorySnapshot)
        .where(MemorySnapshot.novel_id == novel_id)
        .order_by(MemorySnapshot.memory_revision.desc(), MemorySnapshot.created_at.desc())
    )


def snapshot_chapter(session: Session, snapshot: MemorySnapshot) -> Chapter:
    chapter = session.get(Chapter, snapshot.accepted_chapter_id)
    if chapter is None:
        raise MemoryError("snapshot_chapter_missing", "Snapshot chapter does not exist.")
    return chapter
