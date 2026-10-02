from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.sqlite.memory import (
    MemoryCharacter,
    MemoryEvent,
    MemoryFact,
    MemoryForeshadowing,
    MemoryRelationship,
    MemoryStyleProfile,
    MemoryTimeline,
    MemoryWorldFact,
    NovelMemoryRevision,
)
from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.memory import (
    FactOrigin,
    FactStatus,
    ForeshadowingStatus,
    MemoryError,
    MemorySubjectKind,
)
from app.services import catalog
from app.services.memory_audit import write_operation
from app.services.memory_facts import (
    FactProvenance,
    read_fact_provenance,
    record_memory_fact,
    require_canon_memory_source,
)


@dataclass(frozen=True)
class CharacterState:
    id: str
    novel_id: str
    name: str
    aliases: list
    current: dict[str, dict]


def _now() -> datetime:
    return datetime.now(UTC)


@contextmanager
def memory_transaction(session: Session) -> Iterator[None]:
    """Flush a group of memory writes, or roll them back together."""

    try:
        yield
        session.flush()
    except Exception:
        session.rollback()
        raise


class MemoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def memory_revision(self, novel_id: str) -> int:
        catalog.require_novel(self.session, novel_id)
        row = self.session.get(NovelMemoryRevision, novel_id)
        return 0 if row is None else row.revision

    def create_character(
        self, novel_id: str, name: str, aliases: list[str] | None = None
    ) -> MemoryCharacter:
        catalog.require_novel(self.session, novel_id)
        now = _now()
        row = MemoryCharacter(
            id=_new_id(),
            novel_id=novel_id,
            name=name.strip(),
            aliases=list(aliases or []),
            created_at=now,
            updated_at=now,
        )
        if not row.name:
            raise MemoryError("character_name_empty", "Character name cannot be empty.")
        self.session.add(row)
        self._bump(novel_id)
        self.session.flush()
        return row

    def create_relationship(
        self, novel_id: str, source_character_id: str, target_character_id: str
    ) -> MemoryRelationship:
        self._require_character(novel_id, source_character_id)
        self._require_character(novel_id, target_character_id)
        now = _now()
        row = MemoryRelationship(
            id=_new_id(),
            novel_id=novel_id,
            source_character_id=source_character_id,
            target_character_id=target_character_id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self._bump(novel_id)
        self.session.flush()
        return row

    def create_event(self, novel_id: str, label: str) -> MemoryEvent:
        return self._create_labeled(MemoryEvent, novel_id, label)

    def create_timeline(self, novel_id: str, label: str) -> MemoryTimeline:
        return self._create_labeled(MemoryTimeline, novel_id, label)

    def create_world_fact(self, novel_id: str, topic: str) -> MemoryWorldFact:
        catalog.require_novel(self.session, novel_id)
        cleaned = topic.strip()
        if not cleaned:
            raise MemoryError("world_fact_topic_empty", "World fact topic cannot be empty.")
        now = _now()
        row = MemoryWorldFact(
            id=_new_id(),
            novel_id=novel_id,
            topic=cleaned,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self._bump(novel_id)
        self.session.flush()
        return row

    def create_foreshadowing(
        self, novel_id: str, label: str, status: ForeshadowingStatus | str
    ) -> MemoryForeshadowing:
        catalog.require_novel(self.session, novel_id)
        cleaned = label.strip()
        if not cleaned:
            raise MemoryError("foreshadowing_label_empty", "Foreshadowing label cannot be empty.")
        now = _now()
        row = MemoryForeshadowing(
            id=_new_id(),
            novel_id=novel_id,
            label=cleaned,
            status=ForeshadowingStatus(status).value,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self._bump(novel_id)
        self.session.flush()
        return row

    def create_style_profile(
        self, novel_id: str, features: dict, statistics: dict
    ) -> MemoryStyleProfile:
        catalog.require_novel(self.session, novel_id)
        now = _now()
        row = MemoryStyleProfile(
            id=_new_id(),
            novel_id=novel_id,
            features=features,
            statistics=statistics,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self._bump(novel_id)
        self.session.flush()
        return row

    def list_characters(self, novel_id: str) -> list[MemoryCharacter]:
        return self._list(MemoryCharacter, novel_id)

    def list_events(self, novel_id: str) -> list[MemoryEvent]:
        return self._list(MemoryEvent, novel_id)

    def character_state(self, character_id: str) -> CharacterState:
        character = self.session.get(MemoryCharacter, character_id)
        if character is None:
            raise MemoryError("character_not_found", "Character does not exist.")
        facts = self.query_facts(
            character.novel_id,
            subject_kind=MemorySubjectKind.CHARACTER,
            subject_id=character.id,
            status=FactStatus.ACTIVE,
        )
        return CharacterState(
            id=character.id,
            novel_id=character.novel_id,
            name=character.name,
            aliases=list(character.aliases),
            current={fact.fact_key: fact.fact_value for fact in facts},
        )

    def query_facts(
        self,
        novel_id: str,
        *,
        subject_kind: MemorySubjectKind | str | None = None,
        subject_id: str | None = None,
        status: FactStatus | str | None = None,
        revision: int | None = None,
        fact_key: str | None = None,
    ) -> list[MemoryFact]:
        catalog.require_novel(self.session, novel_id)
        stmt = select(MemoryFact).where(MemoryFact.novel_id == novel_id)
        if subject_kind is not None:
            stmt = stmt.where(MemoryFact.subject_kind == MemorySubjectKind(subject_kind).value)
        if subject_id is not None:
            stmt = stmt.where(MemoryFact.subject_id == subject_id)
        if status is not None:
            stmt = stmt.where(MemoryFact.status == FactStatus(status).value)
        if revision is not None:
            stmt = stmt.where(MemoryFact.revision == revision)
        if fact_key is not None:
            stmt = stmt.where(MemoryFact.fact_key == fact_key)
        stmt = stmt.order_by(MemoryFact.revision, MemoryFact.id)
        return list(self.session.scalars(stmt))

    def revise_fact(
        self,
        *,
        novel_id: str,
        subject_kind: MemorySubjectKind | str,
        subject_id: str,
        fact_key: str,
        fact_value: dict,
        source_chapter: Chapter,
        source_version: ChapterVersion,
        origin: FactOrigin | str,
        confidence: float,
        start_offset: int | None = None,
        end_offset: int | None = None,
        locked: bool = False,
    ) -> MemoryFact:
        require_canon_memory_source(source_chapter, source_version, novel_id)
        kind = MemorySubjectKind(subject_kind)
        previous = self._active_fact(novel_id, kind, subject_id, fact_key)
        if previous is not None and previous.locked:
            raise MemoryError("fact_locked", "A locked fact cannot be revised.")
        with self.session.begin_nested():
            next_revision = 1 if previous is None else previous.revision + 1
            if previous is not None:
                previous.active = False
                previous.status = FactStatus.SUPERSEDED.value
                previous.updated_at = _now()
                self.session.flush()
            created = record_memory_fact(
                self.session,
                novel_id=novel_id,
                subject_kind=kind,
                subject_id=subject_id,
                fact_key=fact_key,
                fact_value=fact_value,
                source_chapter=source_chapter,
                source_version=source_version,
                origin=origin,
                confidence=confidence,
                revision=next_revision,
                active=True,
                locked=locked,
                start_offset=start_offset,
                end_offset=end_offset,
            )
            if previous is not None:
                previous.superseded_by_id = created.id
                self.session.flush()
        self._bump(novel_id)
        self.session.flush()
        return created

    def reinforce_fact(self, fact: MemoryFact, *, confidence: float) -> MemoryFact:
        """Raise confidence for a repeated fact. The active row stays the only copy."""

        if not 0 <= confidence <= 1:
            raise MemoryError("confidence_out_of_range", "Confidence must be between 0 and 1.")
        if fact.locked:
            raise MemoryError("fact_locked", "A locked fact cannot be revised.")
        fact.confidence = min(1.0, round(max(fact.confidence, confidence) + 0.05, 2))
        fact.updated_at = _now()
        self._bump(fact.novel_id)
        self.session.flush()
        return fact

    def lock_fact(self, fact_id: str, novel_id: str) -> MemoryFact:
        fact = self._fact_in_novel(fact_id, novel_id)
        before = fact.revision
        if not fact.locked:
            fact.locked = True
            fact.updated_at = _now()
            self._bump(novel_id)
            write_operation(
                self.session,
                novel_id=novel_id,
                action="lock_fact",
                target_kind="fact",
                target_id=fact.id,
                before_revision=before,
                after_revision=fact.revision,
                detail={"locked": True},
            )
        return fact

    def unlock_fact(self, fact_id: str, novel_id: str) -> MemoryFact:
        fact = self._fact_in_novel(fact_id, novel_id)
        before = fact.revision
        if fact.locked:
            fact.locked = False
            fact.updated_at = _now()
            self._bump(novel_id)
            write_operation(
                self.session,
                novel_id=novel_id,
                action="unlock_fact",
                target_kind="fact",
                target_id=fact.id,
                before_revision=before,
                after_revision=fact.revision,
                detail={"locked": False},
            )
        return fact

    def supersede_fact(
        self,
        *,
        fact_id: str,
        novel_id: str,
        fact_value: dict,
        source_chapter: Chapter,
        source_version: ChapterVersion,
        origin: FactOrigin | str,
        confidence: float,
    ) -> MemoryFact:
        previous = self._fact_in_novel(fact_id, novel_id)
        if previous.locked:
            raise MemoryError("fact_locked", "A locked fact cannot be revised.")
        created = self.revise_fact(
            novel_id=novel_id,
            subject_kind=previous.subject_kind,
            subject_id=previous.subject_id,
            fact_key=previous.fact_key,
            fact_value=fact_value,
            source_chapter=source_chapter,
            source_version=source_version,
            origin=origin,
            confidence=confidence,
        )
        self.guard_supersede_link(previous, created)
        write_operation(
            self.session,
            novel_id=novel_id,
            action="supersede_fact",
            target_kind="fact",
            target_id=previous.id,
            before_revision=previous.revision,
            after_revision=created.revision,
            detail={"successor_id": created.id},
        )
        return created

    def guard_supersede_link(self, previous: MemoryFact, successor: MemoryFact) -> None:
        if previous.novel_id != successor.novel_id:
            raise MemoryError("cross_novel_supersede", "Facts from different novels cannot link.")
        if previous.id == successor.id:
            raise MemoryError("supersede_cycle", "A fact cannot supersede itself.")
        seen = {previous.id}
        cursor: MemoryFact | None = successor
        while cursor is not None:
            if cursor.id in seen:
                raise MemoryError("supersede_cycle", "Supersede links cannot form a cycle.")
            seen.add(cursor.id)
            if cursor.superseded_by_id is None:
                break
            cursor = self.session.get(MemoryFact, cursor.superseded_by_id)

    def _fact_in_novel(self, fact_id: str, novel_id: str) -> MemoryFact:
        fact = self.session.get(MemoryFact, fact_id)
        if fact is None or fact.novel_id != novel_id:
            raise MemoryError("fact_not_found", "Fact does not exist in this novel.")
        return fact

    def note_revision(self, novel_id: str) -> int:
        return self._bump(novel_id)

    def provenance(self, fact_id: str) -> FactProvenance:
        return read_fact_provenance(self.session, fact_id)

    def _active_fact(
        self, novel_id: str, kind: MemorySubjectKind, subject_id: str, fact_key: str
    ) -> MemoryFact | None:
        return self.session.scalar(
            select(MemoryFact).where(
                MemoryFact.novel_id == novel_id,
                MemoryFact.subject_kind == kind.value,
                MemoryFact.subject_id == subject_id,
                MemoryFact.fact_key == fact_key,
                MemoryFact.active.is_(True),
            )
        )

    def _require_character(self, novel_id: str, character_id: str) -> MemoryCharacter:
        row = self.session.get(MemoryCharacter, character_id)
        if row is None or row.novel_id != novel_id:
            raise MemoryError("character_not_found", "Character does not exist in this novel.")
        return row

    def _create_labeled(self, model, novel_id: str, label: str):  # type: ignore[no-untyped-def]
        catalog.require_novel(self.session, novel_id)
        cleaned = label.strip()
        if not cleaned:
            raise MemoryError("memory_label_empty", "Memory label cannot be empty.")
        now = _now()
        row = model(
            id=_new_id(),
            novel_id=novel_id,
            label=cleaned,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self._bump(novel_id)
        self.session.flush()
        return row

    def _list(self, model, novel_id: str):  # type: ignore[no-untyped-def]
        catalog.require_novel(self.session, novel_id)
        return list(
            self.session.scalars(
                select(model).where(model.novel_id == novel_id).order_by(model.created_at, model.id)
            )
        )

    def _bump(self, novel_id: str) -> int:
        row = self.session.get(NovelMemoryRevision, novel_id)
        now = _now()
        if row is None:
            row = NovelMemoryRevision(novel_id=novel_id, revision=1, updated_at=now)
            self.session.add(row)
        else:
            row.revision += 1
            row.updated_at = now
        self.session.flush()
        return row.revision


def _new_id() -> str:
    from uuid import uuid4

    return str(uuid4())
