from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.sqlite.memory import (
    EntityResolutionRecord,
    MemoryCharacter,
    MemoryNamedEntity,
    NovelMemoryRevision,
)
from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.entity_resolution import (
    EntityKind,
    EntityRef,
    ResolutionAction,
    ResolutionMatch,
    aliases_from_phrase,
    classify_mention,
)
from app.domain.memory import MemoryError
from app.services.memory_facts import require_canon_memory_source


def resolve_mention(
    session: Session,
    *,
    novel_id: str,
    kind: EntityKind | str,
    name: str,
    source_chapter: Chapter,
    source_version: ChapterVersion,
    aliases: list[str] | None = None,
    phrase: str = "",
) -> EntityResolutionRecord:
    """Merge only on explicit alias evidence. Same names stay as reviewable candidates."""

    require_canon_memory_source(source_chapter, source_version, novel_id)
    resolved_kind = EntityKind(kind)
    cleaned = name.strip()
    if not cleaned:
        raise MemoryError("mention_name_empty", "Entity mention name cannot be empty.")
    entities = _load_refs(session, novel_id, resolved_kind)
    mention_aliases = [
        item.strip() for item in (*(aliases or []), *aliases_from_phrase(phrase)) if item.strip()
    ]
    match = classify_mention(cleaned, mention_aliases, entities)
    entity_id = _apply(session, novel_id, resolved_kind, cleaned, mention_aliases, match)
    now = datetime.now(UTC)
    record = EntityResolutionRecord(
        id=str(uuid4()),
        novel_id=novel_id,
        entity_kind=resolved_kind.value,
        mention_name=cleaned,
        decision=match.action.value,
        entity_id=entity_id,
        candidate_entity_ids=list(match.candidate_ids),
        reason=match.reason,
        source_chapter_id=source_chapter.id,
        source_chapter_version_id=source_version.id,
        created_at=now,
    )
    session.add(record)
    if match.action is not ResolutionAction.CANDIDATE:
        _bump(session, novel_id, now)
    session.flush()
    return record


def list_resolution_candidates(session: Session, novel_id: str) -> list[EntityResolutionRecord]:
    return list(
        session.scalars(
            select(EntityResolutionRecord)
            .where(
                EntityResolutionRecord.novel_id == novel_id,
                EntityResolutionRecord.decision == ResolutionAction.CANDIDATE.value,
            )
            .order_by(EntityResolutionRecord.created_at, EntityResolutionRecord.id)
        )
    )


def _apply(
    session: Session,
    novel_id: str,
    kind: EntityKind,
    name: str,
    aliases: list[str],
    match: ResolutionMatch,
) -> str | None:
    if match.action is ResolutionAction.CANDIDATE:
        return None
    if match.action is ResolutionAction.MERGED and match.entity_id is not None:
        _attach_aliases(session, kind, match.entity_id, name, aliases)
        return match.entity_id
    return _create_entity(session, novel_id, kind, name, aliases)


def _attach_aliases(
    session: Session, kind: EntityKind, entity_id: str, name: str, aliases: list[str]
) -> None:
    entity = _entity(session, kind, entity_id)
    merged = list(entity.aliases)
    for extra in (name, *aliases):
        cleaned = extra.strip()
        if cleaned and cleaned != entity.name and cleaned not in merged:
            merged.append(cleaned)
    entity.aliases = merged
    entity.updated_at = datetime.now(UTC)


def _create_entity(
    session: Session, novel_id: str, kind: EntityKind, name: str, aliases: list[str]
) -> str:
    now = datetime.now(UTC)
    extras = [item.strip() for item in aliases if item.strip() and item.strip() != name]
    if kind is EntityKind.CHARACTER:
        row = MemoryCharacter(
            id=str(uuid4()),
            novel_id=novel_id,
            name=name,
            aliases=extras,
            created_at=now,
            updated_at=now,
        )
    else:
        row = MemoryNamedEntity(
            id=str(uuid4()),
            novel_id=novel_id,
            kind=kind.value,
            name=name,
            aliases=extras,
            created_at=now,
            updated_at=now,
        )
    session.add(row)
    session.flush()
    return row.id


def _entity(
    session: Session, kind: EntityKind, entity_id: str
) -> MemoryCharacter | MemoryNamedEntity:
    model = MemoryCharacter if kind is EntityKind.CHARACTER else MemoryNamedEntity
    row = session.get(model, entity_id)
    if row is None:
        raise MemoryError("entity_not_found", "Resolved entity does not exist.")
    return row


def _load_refs(session: Session, novel_id: str, kind: EntityKind) -> list[EntityRef]:
    if kind is EntityKind.CHARACTER:
        rows = session.scalars(
            select(MemoryCharacter).where(MemoryCharacter.novel_id == novel_id)
        ).all()
    else:
        rows = session.scalars(
            select(MemoryNamedEntity).where(
                MemoryNamedEntity.novel_id == novel_id,
                MemoryNamedEntity.kind == kind.value,
            )
        ).all()
    return [EntityRef(id=row.id, name=row.name, aliases=tuple(row.aliases or [])) for row in rows]


def _bump(session: Session, novel_id: str, now: datetime) -> None:
    row = session.get(NovelMemoryRevision, novel_id)
    if row is None:
        session.add(NovelMemoryRevision(novel_id=novel_id, revision=1, updated_at=now))
    else:
        row.revision += 1
        row.updated_at = now
