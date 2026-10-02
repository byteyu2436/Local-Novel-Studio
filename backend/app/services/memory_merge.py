from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.sqlite.memory import MemoryCharacter, MemoryFact, MemoryRelationship
from app.domain.memory import FactStatus, MemoryError, MemorySubjectKind
from app.services.memory_audit import write_operation


def merge_characters(
    session: Session, novel_id: str, source_id: str, target_id: str
) -> MemoryCharacter:
    """Confirm an alias merge. Facts and relationships move onto the target character."""

    if source_id == target_id:
        raise MemoryError("merge_same_entity", "A character cannot be merged into itself.")
    source = _character(session, novel_id, source_id)
    target = _character(session, novel_id, target_id)
    with session.begin_nested():
        _move_facts(session, novel_id, source.id, target.id)
        _move_relationships(session, novel_id, source.id, target.id)
        aliases = list(target.aliases)
        for extra in (source.name, *list(source.aliases)):
            if extra and extra != target.name and extra not in aliases:
                aliases.append(extra)
        target.aliases = aliases
        write_operation(
            session,
            novel_id=novel_id,
            action="merge_alias",
            target_kind="character",
            target_id=target.id,
            before_revision=None,
            after_revision=None,
            detail={"source_id": source.id, "source_name": source.name},
        )
        session.delete(source)
        session.flush()
    return target


def _character(session: Session, novel_id: str, character_id: str) -> MemoryCharacter:
    row = session.get(MemoryCharacter, character_id)
    if row is None or row.novel_id != novel_id:
        raise MemoryError("entity_not_found", "Character does not exist in this novel.")
    return row


def _move_facts(session: Session, novel_id: str, source_id: str, target_id: str) -> None:
    facts = session.scalars(
        select(MemoryFact).where(
            MemoryFact.novel_id == novel_id,
            MemoryFact.subject_kind == MemorySubjectKind.CHARACTER.value,
            MemoryFact.subject_id == source_id,
        )
    ).all()
    for fact in facts:
        clash = session.scalar(
            select(MemoryFact).where(
                MemoryFact.novel_id == novel_id,
                MemoryFact.subject_kind == MemorySubjectKind.CHARACTER.value,
                MemoryFact.subject_id == target_id,
                MemoryFact.fact_key == fact.fact_key,
                MemoryFact.active.is_(True),
            )
        )
        if fact.active and clash is not None:
            fact.active = False
            fact.status = FactStatus.SUPERSEDED.value
            fact.superseded_by_id = clash.id
            continue
        fact.subject_id = target_id


def _move_relationships(session: Session, novel_id: str, source_id: str, target_id: str) -> None:
    rows = session.scalars(
        select(MemoryRelationship).where(
            MemoryRelationship.novel_id == novel_id,
            (MemoryRelationship.source_character_id == source_id)
            | (MemoryRelationship.target_character_id == source_id),
        )
    ).all()
    for row in rows:
        new_source = target_id if row.source_character_id == source_id else row.source_character_id
        new_target = target_id if row.target_character_id == source_id else row.target_character_id
        if new_source == new_target:
            session.delete(row)
            continue
        clash = session.scalar(
            select(MemoryRelationship).where(
                MemoryRelationship.novel_id == novel_id,
                MemoryRelationship.source_character_id == new_source,
                MemoryRelationship.target_character_id == new_target,
                MemoryRelationship.id != row.id,
            )
        )
        if clash is not None:
            _retarget_relationship_facts(session, novel_id, row.id, clash.id)
            session.delete(row)
            continue
        row.source_character_id = new_source
        row.target_character_id = new_target


def _retarget_relationship_facts(
    session: Session, novel_id: str, source_rel: str, target_rel: str
) -> None:
    facts = session.scalars(
        select(MemoryFact).where(
            MemoryFact.novel_id == novel_id,
            MemoryFact.subject_kind == MemorySubjectKind.RELATIONSHIP.value,
            MemoryFact.subject_id == source_rel,
        )
    ).all()
    for fact in facts:
        fact.subject_id = target_rel
