from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.sqlite.memory import MemoryConflict, MemoryFact
from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.memory_conflict import ConflictStatus, value_fingerprint


def open_memory_conflict(
    session: Session,
    *,
    novel_id: str,
    subject_kind: str,
    subject_id: str,
    fact_key: str,
    category: str,
    existing: MemoryFact,
    incoming_value: dict,
    source_chapter: Chapter,
    source_version: ChapterVersion,
) -> MemoryConflict:
    """Record one open contradiction. The same incoming claim does not stack."""

    fingerprint = value_fingerprint(incoming_value)
    found = session.scalar(
        select(MemoryConflict).where(
            MemoryConflict.novel_id == novel_id,
            MemoryConflict.existing_fact_id == existing.id,
            MemoryConflict.fact_key == fact_key,
            MemoryConflict.incoming_fingerprint == fingerprint,
            MemoryConflict.status == ConflictStatus.OPEN.value,
        )
    )
    if found is not None:
        return found
    row = MemoryConflict(
        id=str(uuid4()),
        novel_id=novel_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        fact_key=fact_key,
        category=category,
        existing_fact_id=existing.id,
        existing_revision=existing.revision,
        existing_value=dict(existing.fact_value),
        existing_source_chapter_id=existing.source_chapter_id,
        existing_source_chapter_version_id=existing.source_chapter_version_id,
        incoming_value=incoming_value,
        incoming_fingerprint=fingerprint,
        incoming_source_chapter_id=source_chapter.id,
        incoming_source_chapter_version_id=source_version.id,
        reason=category,
        status=ConflictStatus.OPEN.value,
        resolution=None,
        created_at=datetime.now(UTC),
        resolved_at=None,
    )
    session.add(row)
    session.flush()
    return row


def list_open_conflicts(session: Session, novel_id: str) -> list[MemoryConflict]:
    return list(
        session.scalars(
            select(MemoryConflict)
            .where(
                MemoryConflict.novel_id == novel_id,
                MemoryConflict.status == ConflictStatus.OPEN.value,
            )
            .order_by(MemoryConflict.created_at, MemoryConflict.id)
        )
    )
