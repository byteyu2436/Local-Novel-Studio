from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.sqlite.memory import (
    MemoryEvent,
    MemoryForeshadowing,
    MemoryNamedEntity,
    MemoryReduceApplication,
    MemoryRelationship,
    MemoryStyleProfile,
    MemoryTimeline,
    MemoryWorldFact,
)
from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.entity_resolution import EntityKind, ResolutionAction
from app.domain.memory import FactOrigin, FactStatus, MemorySubjectKind
from app.domain.memory_conflict import contradiction_category, split_rule
from app.schemas.analysis import (
    ChapterAnalysisPayload,
    CharacterMention,
    EventRecord,
    ForeshadowingItem,
    RelationshipRecord,
    StyleSignals,
    TimelineEntry,
    WorldFactItem,
    parse_stored_analysis_payload,
)
from app.services import catalog
from app.services.analysis import get_chapter_analysis
from app.services.entity_resolution import resolve_mention
from app.services.memory_conflicts import open_memory_conflict
from app.services.memory_facts import require_canon_memory_source
from app.services.memory_repository import MemoryRepository

_REPEAT_CONFIDENCE = 0.7
_FORWARD_FORESHADOWING = {
    "planted": {"reinforced", "resolved", "abandoned"},
    "reinforced": {"resolved", "abandoned"},
    "resolved": set(),
    "abandoned": set(),
}


@dataclass(frozen=True)
class ConflictSignal:
    subject_kind: str
    subject_id: str
    fact_key: str
    current_value: dict
    incoming_value: dict
    source_chapter_id: str
    reason: str = "value_conflict"


@dataclass
class ReduceReport:
    chapters_applied: int = 0
    chapters_skipped: int = 0
    chapter_ids: list[str] = field(default_factory=list)
    facts_created: int = 0
    facts_reinforced: int = 0
    conflicts: list[ConflictSignal] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    replay: bool = False


def reduce_novel_memory(session: Session, novel_id: str) -> ReduceReport:
    """Fold stored Canon analyses into Novel Memory, in chapter sequence."""

    catalog.require_novel(session, novel_id)
    report = ReduceReport()
    for chapter in catalog.list_chapters(session, novel_id):
        if chapter.current_canon_version_id is None:
            continue
        version = session.get(ChapterVersion, chapter.current_canon_version_id)
        if version is None:
            continue
        stored = get_chapter_analysis(session, chapter.id, version.id)
        if stored is None:
            continue
        payload = parse_stored_analysis_payload(
            stored.payload, schema_version=stored.schema_version
        )
        reduce_chapter_analysis(
            session,
            novel_id=novel_id,
            chapter=chapter,
            source_version=version,
            payload=payload,
            report=report,
        )
    return report


def reduce_chapter_analysis(
    session: Session,
    *,
    novel_id: str,
    chapter: Chapter,
    source_version: ChapterVersion,
    payload: ChapterAnalysisPayload,
    report: ReduceReport | None = None,
) -> ReduceReport:
    """Merge one chapter. Draft text is rejected before any memory write."""

    require_canon_memory_source(chapter, source_version, novel_id)
    current = report or ReduceReport()
    if _already_reduced(session, novel_id, source_version.id):
        current.chapters_skipped += 1
        current.chapter_ids.append(chapter.id)
        return current
    repo = MemoryRepository(session)
    _characters(session, repo, novel_id, chapter, source_version, payload.characters, current)
    _locations(session, repo, novel_id, chapter, source_version, payload.locations, current)
    _relationships(session, repo, novel_id, chapter, source_version, payload.relationships, current)
    _events(session, repo, novel_id, chapter, source_version, payload.events, current)
    _timeline(session, repo, novel_id, chapter, source_version, payload.timeline, current)
    _foreshadowing(session, repo, novel_id, chapter, source_version, payload.foreshadowing, current)
    _world_facts(session, repo, novel_id, chapter, source_version, payload.world_facts, current)
    _style(session, repo, novel_id, chapter, source_version, payload.style_signals, current)
    session.add(
        MemoryReduceApplication(
            id=str(uuid4()),
            novel_id=novel_id,
            source_chapter_id=chapter.id,
            source_chapter_version_id=source_version.id,
            created_at=datetime.now(UTC),
        )
    )
    session.flush()
    current.chapters_applied += 1
    current.chapter_ids.append(chapter.id)
    return current


def _already_reduced(session: Session, novel_id: str, version_id: str) -> bool:
    return (
        session.scalar(
            select(MemoryReduceApplication.id).where(
                MemoryReduceApplication.novel_id == novel_id,
                MemoryReduceApplication.source_chapter_version_id == version_id,
            )
        )
        is not None
    )


def _characters(
    session, repo, novel_id, chapter, version, mentions: list[CharacterMention], report
):
    for mention in mentions:
        subject_id = _subject(
            session,
            novel_id,
            EntityKind.CHARACTER,
            mention.name,
            chapter,
            version,
            report,
            aliases=mention.aliases,
        )
        if subject_id is None:
            continue
        for key in ("identity", "personality", "goal", "secret", "current_state"):
            text = getattr(mention, key).strip()
            if text:
                _write_fact(
                    repo,
                    novel_id=novel_id,
                    kind=MemorySubjectKind.CHARACTER,
                    subject_id=subject_id,
                    fact_key=key,
                    value={"value": text},
                    chapter=chapter,
                    version=version,
                    report=report,
                    evolve=key == "current_state",
                )


def _locations(session, repo, novel_id, chapter, version, mentions, report) -> None:
    for mention in mentions:
        _subject(
            session,
            novel_id,
            EntityKind.LOCATION,
            mention.name,
            chapter,
            version,
            report,
            aliases=mention.aliases,
        )
        description = mention.description.strip()
        if not description:
            continue
        row = session.scalar(
            select(MemoryWorldFact).where(
                MemoryWorldFact.novel_id == novel_id,
                MemoryWorldFact.topic == mention.name.strip(),
            )
        )
        if row is None:
            row = repo.create_world_fact(novel_id, mention.name)
        _write_fact(
            repo,
            novel_id=novel_id,
            kind=MemorySubjectKind.WORLD_FACT,
            subject_id=row.id,
            fact_key="description",
            value={"value": description},
            chapter=chapter,
            version=version,
            report=report,
        )


def _relationships(
    session, repo, novel_id, chapter, version, records: list[RelationshipRecord], report
) -> None:
    for record in records:
        source_id = _subject(
            session, novel_id, EntityKind.CHARACTER, record.source, chapter, version, report
        )
        target_id = _subject(
            session, novel_id, EntityKind.CHARACTER, record.target, chapter, version, report
        )
        if source_id is None or target_id is None:
            continue
        row = session.scalar(
            select(MemoryRelationship).where(
                MemoryRelationship.novel_id == novel_id,
                MemoryRelationship.source_character_id == source_id,
                MemoryRelationship.target_character_id == target_id,
            )
        )
        if row is None:
            row = repo.create_relationship(novel_id, source_id, target_id)
        _write_fact(
            repo,
            novel_id=novel_id,
            kind=MemorySubjectKind.RELATIONSHIP,
            subject_id=row.id,
            fact_key="relation_type",
            value={"value": record.relation_type},
            chapter=chapter,
            version=version,
            report=report,
            evolve=True,
        )
        if record.trust_or_conflict.strip():
            _write_fact(
                repo,
                novel_id=novel_id,
                kind=MemorySubjectKind.RELATIONSHIP,
                subject_id=row.id,
                fact_key="trust_or_conflict",
                value={"value": record.trust_or_conflict.strip()},
                chapter=chapter,
                version=version,
                report=report,
                evolve=True,
            )
        if record.current_state.strip():
            _write_fact(
                repo,
                novel_id=novel_id,
                kind=MemorySubjectKind.RELATIONSHIP,
                subject_id=row.id,
                fact_key="current_state",
                value={"value": record.current_state.strip()},
                chapter=chapter,
                version=version,
                report=report,
                evolve=True,
            )


def _events(session, repo, novel_id, chapter, version, records: list[EventRecord], report) -> None:
    for record in records:
        row = _ensure_labeled(
            session, repo, MemoryEvent, novel_id, record.summary, repo.create_event
        )
        _write_fact(
            repo,
            novel_id=novel_id,
            kind=MemorySubjectKind.EVENT,
            subject_id=row.id,
            fact_key="importance",
            value={"value": record.importance},
            chapter=chapter,
            version=version,
            report=report,
        )


def _timeline(session, repo, novel_id, chapter, version, entries: list[TimelineEntry], report):
    for entry in entries:
        row = _ensure_labeled(
            session, repo, MemoryTimeline, novel_id, entry.summary, repo.create_timeline
        )
        fields: dict[str, object] = {
            "order_key": entry.order_key,
            "uncertainty": entry.uncertainty,
        }
        if entry.explicit_time:
            fields["explicit_time"] = entry.explicit_time
        if entry.relative_time:
            fields["relative_time"] = entry.relative_time
        for key, raw in fields.items():
            _write_fact(
                repo,
                novel_id=novel_id,
                kind=MemorySubjectKind.TIMELINE,
                subject_id=row.id,
                fact_key=key,
                value={"value": raw},
                chapter=chapter,
                version=version,
                report=report,
                evolve=True,
            )


def _foreshadowing(
    session, repo, novel_id, chapter, version, items: list[ForeshadowingItem], report
) -> None:
    for item in items:
        row = session.scalar(
            select(MemoryForeshadowing).where(
                MemoryForeshadowing.novel_id == novel_id,
                MemoryForeshadowing.label == item.clue.strip(),
            )
        )
        if row is None:
            row = repo.create_foreshadowing(novel_id, item.clue, item.status)
            advancing = False
        else:
            advancing = item.status in _FORWARD_FORESHADOWING[row.status]
            if advancing:
                row.status = item.status
                row.updated_at = datetime.now(UTC)
        _write_fact(
            repo,
            novel_id=novel_id,
            kind=MemorySubjectKind.FORESHADOWING,
            subject_id=row.id,
            fact_key="status",
            value={"value": item.status},
            chapter=chapter,
            version=version,
            report=report,
            evolve=advancing,
        )


def _world_facts(
    session, repo, novel_id, chapter, version, items: list[WorldFactItem], report
) -> None:
    for item in items:
        topic, statement = split_rule(item.fact)
        if item.category == "organization":
            _subject(
                session,
                novel_id,
                EntityKind.ORGANIZATION,
                topic,
                chapter,
                version,
                report,
            )
        row = session.scalar(
            select(MemoryWorldFact).where(
                MemoryWorldFact.novel_id == novel_id,
                MemoryWorldFact.topic == topic,
            )
        )
        if row is None:
            row = repo.create_world_fact(novel_id, topic)
        _write_fact(
            repo,
            novel_id=novel_id,
            kind=MemorySubjectKind.WORLD_FACT,
            subject_id=row.id,
            fact_key="category",
            value={"value": item.category},
            chapter=chapter,
            version=version,
            report=report,
        )
        if statement:
            _write_fact(
                repo,
                novel_id=novel_id,
                kind=MemorySubjectKind.WORLD_FACT,
                subject_id=row.id,
                fact_key="statement",
                value={"value": statement},
                chapter=chapter,
                version=version,
                report=report,
            )


def _style(session, repo, novel_id, chapter, version, signals: StyleSignals, report) -> None:
    profile = session.scalar(
        select(MemoryStyleProfile).where(MemoryStyleProfile.novel_id == novel_id)
    )
    if profile is None:
        profile = repo.create_style_profile(novel_id, {}, {"chapter_count": 0})
    features = dict(profile.features)
    for key, value in signals.model_dump().items():
        if not value:
            continue
        outcome = _write_fact(
            repo,
            novel_id=novel_id,
            kind=MemorySubjectKind.STYLE_PROFILE,
            subject_id=profile.id,
            fact_key=key,
            value={"value": value},
            chapter=chapter,
            version=version,
            report=report,
        )
        if outcome != "conflict":
            features[key] = value
    statistics = dict(profile.statistics)
    statistics["chapter_count"] = int(statistics.get("chapter_count", 0)) + 1
    profile.features = features
    profile.statistics = statistics
    session.flush()


def _subject(
    session,
    novel_id: str,
    kind: EntityKind,
    name: str,
    chapter: Chapter,
    version: ChapterVersion,
    report: ReduceReport,
    aliases: list[str] | None = None,
) -> str | None:
    record = resolve_mention(
        session,
        novel_id=novel_id,
        kind=kind,
        name=name,
        aliases=aliases,
        source_chapter=chapter,
        source_version=version,
    )
    if record.decision in {ResolutionAction.MERGED.value, ResolutionAction.CREATED.value}:
        return record.entity_id
    candidate_ids = list(record.candidate_entity_ids)
    if record.reason == "same_name" and len(candidate_ids) == 1:
        return candidate_ids[0]
    report.unresolved.append(f"{kind.value}:{name}:{record.reason}")
    return None


def _ensure_labeled(session, repo, model, novel_id: str, label: str, create):
    cleaned = label.strip()
    column = model.label
    row = session.scalar(select(model).where(model.novel_id == novel_id, column == cleaned))
    if row is None:
        row = create(novel_id, cleaned)
    return row


def _write_fact(
    repo: MemoryRepository,
    *,
    novel_id: str,
    kind: MemorySubjectKind,
    subject_id: str,
    fact_key: str,
    value: dict,
    chapter: Chapter,
    version: ChapterVersion,
    report: ReduceReport,
    evolve: bool = False,
) -> str:
    existing = repo.query_facts(
        novel_id,
        subject_kind=kind,
        subject_id=subject_id,
        status=FactStatus.ACTIVE,
        fact_key=fact_key,
    )
    if not existing:
        repo.revise_fact(
            novel_id=novel_id,
            subject_kind=kind,
            subject_id=subject_id,
            fact_key=fact_key,
            fact_value=value,
            source_chapter=chapter,
            source_version=version,
            origin=FactOrigin.INFERRED,
            confidence=_REPEAT_CONFIDENCE,
        )
        report.facts_created += 1
        return "created"
    current = existing[0]
    if current.locked:
        if current.fact_value != value:
            _remember_conflict(
                repo,
                novel_id=novel_id,
                kind=kind,
                subject_id=subject_id,
                fact_key=fact_key,
                current=current,
                value=value,
                chapter=chapter,
                version=version,
                report=report,
                reason="fact_locked",
            )
        return "locked"
    if current.fact_value == value:
        if report.replay:
            return "replayed"
        repo.reinforce_fact(current, confidence=_REPEAT_CONFIDENCE)
        report.facts_reinforced += 1
        return "reinforced"
    if evolve:
        repo.revise_fact(
            novel_id=novel_id,
            subject_kind=kind,
            subject_id=subject_id,
            fact_key=fact_key,
            fact_value=value,
            source_chapter=chapter,
            source_version=version,
            origin=FactOrigin.INFERRED,
            confidence=_REPEAT_CONFIDENCE,
        )
        report.facts_created += 1
        return "evolved"
    _remember_conflict(
        repo,
        novel_id=novel_id,
        kind=kind,
        subject_id=subject_id,
        fact_key=fact_key,
        current=current,
        value=value,
        chapter=chapter,
        version=version,
        report=report,
        reason="supersede_candidate",
    )
    return "conflict"


def _remember_conflict(
    repo,
    *,
    novel_id: str,
    kind: MemorySubjectKind,
    subject_id: str,
    fact_key: str,
    current,
    value: dict,
    chapter: Chapter,
    version: ChapterVersion,
    report: ReduceReport,
    reason: str,
) -> None:
    category = contradiction_category(kind.value, fact_key, current.fact_value, value)
    report.conflicts.append(
        ConflictSignal(
            subject_kind=kind.value,
            subject_id=subject_id,
            fact_key=fact_key,
            current_value=dict(current.fact_value),
            incoming_value=value,
            source_chapter_id=chapter.id,
            reason=category or reason,
        )
    )
    if category is None:
        return
    open_memory_conflict(
        repo.session,
        novel_id=novel_id,
        subject_kind=kind.value,
        subject_id=subject_id,
        fact_key=fact_key,
        category=category,
        existing=current,
        incoming_value=value,
        source_chapter=chapter,
        source_version=version,
    )


def named_entity_count(session: Session, novel_id: str) -> int:
    return len(
        session.scalars(
            select(MemoryNamedEntity).where(MemoryNamedEntity.novel_id == novel_id)
        ).all()
    )
