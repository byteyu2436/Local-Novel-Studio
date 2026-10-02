from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.sqlite.memory import (
    MemoryCharacter,
    MemoryConflict,
    MemoryEvent,
    MemoryFact,
    MemoryForeshadowing,
    MemoryRelationship,
    MemoryStyleProfile,
    MemoryTimeline,
    MemoryWorldFact,
)
from app.domain.memory import FactStatus, MemorySubjectKind
from app.services import catalog
from app.services.memory_facts import read_fact_provenance
from app.services.memory_repository import MemoryRepository


def list_memory_entities(session: Session, novel_id: str, kind: str) -> list[dict]:
    catalog.require_novel(session, novel_id)
    resolved = MemorySubjectKind(kind)
    model = {
        MemorySubjectKind.CHARACTER: MemoryCharacter,
        MemorySubjectKind.RELATIONSHIP: MemoryRelationship,
        MemorySubjectKind.EVENT: MemoryEvent,
        MemorySubjectKind.TIMELINE: MemoryTimeline,
        MemorySubjectKind.FORESHADOWING: MemoryForeshadowing,
        MemorySubjectKind.WORLD_FACT: MemoryWorldFact,
        MemorySubjectKind.STYLE_PROFILE: MemoryStyleProfile,
    }[resolved]
    rows = session.scalars(
        select(model).where(model.novel_id == novel_id).order_by(model.created_at, model.id)
    ).all()
    return [{"id": row.id, "kind": resolved.value, "label": _label(row)} for row in rows]


def list_memory_facts(
    session: Session,
    novel_id: str,
    *,
    kind: str | None = None,
    status: str | None = None,
    locked: bool | None = None,
) -> list[dict]:
    repo = MemoryRepository(session)
    facts = repo.query_facts(
        novel_id,
        subject_kind=kind,
        status=status,
    )
    if locked is not None:
        facts = [fact for fact in facts if fact.locked is locked]
    return [_fact_summary(session, fact) for fact in facts]


def fact_detail(session: Session, novel_id: str, fact_id: str) -> dict:
    fact = session.get(MemoryFact, fact_id)
    if fact is None or fact.novel_id != novel_id:
        from app.domain.memory import MemoryError

        raise MemoryError("fact_not_found", "Fact does not exist in this novel.")
    provenance = read_fact_provenance(session, fact.id)
    conflicts = session.scalars(
        select(MemoryConflict).where(
            MemoryConflict.novel_id == novel_id,
            MemoryConflict.existing_fact_id == fact.id,
        )
    ).all()
    return {
        "fact": _fact_summary(session, fact),
        "provenance": {
            "chapter_id": provenance.chapter_id,
            "chapter_version_id": provenance.chapter_version_id,
            "version_kind": provenance.version_kind,
            "origin": provenance.origin,
            "start_offset": provenance.start_offset,
            "end_offset": provenance.end_offset,
            "source_text_hash": provenance.source_text_hash,
        },
        "superseded_by_id": fact.superseded_by_id,
        "conflicts": [
            {
                "id": item.id,
                "status": item.status,
                "category": item.category,
                "incoming_value": item.incoming_value,
            }
            for item in conflicts
        ],
    }


def _fact_summary(session: Session, fact: MemoryFact) -> dict:
    chapter_title = ""
    if fact.source_chapter_id:
        from app.adapters.sqlite.models import Chapter

        chapter = session.get(Chapter, fact.source_chapter_id)
        if chapter is not None:
            chapter_title = chapter.display_title
    return {
        "id": fact.id,
        "novel_id": fact.novel_id,
        "subject_kind": fact.subject_kind,
        "subject_id": fact.subject_id,
        "fact_key": fact.fact_key,
        "value": fact.fact_value,
        "confidence": fact.confidence,
        "locked": fact.locked,
        "status": fact.status,
        "revision": fact.revision,
        "source_chapter_id": fact.source_chapter_id,
        "source_chapter_version_id": fact.source_chapter_version_id,
        "source_chapter_title": chapter_title,
        "active": fact.status == FactStatus.ACTIVE.value,
    }


def _label(row: object) -> str:
    for attr in ("name", "label", "topic"):
        value = getattr(row, attr, None)
        if isinstance(value, str) and value:
            return value
    return row.id
