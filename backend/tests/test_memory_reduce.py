from datetime import UTC, datetime

import pytest
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.memory import (
    MemoryCharacter,
    MemoryEvent,
    MemoryForeshadowing,
    MemoryStyleProfile,
    MemoryTimeline,
    MemoryWorldFact,
)
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chapter_canon import add_draft_version
from app.domain.memory import FactStatus, MemoryError, MemorySubjectKind
from app.schemas.analysis import (
    ChapterAnalysisPayload,
    ChapterSummary,
    CharacterMention,
    EventRecord,
    ForeshadowingItem,
    LocationMention,
    RelationshipRecord,
    StyleSignals,
    TimelineEntry,
    WorldFactItem,
)
from app.services import catalog
from app.services.analysis import persist_chapter_analysis
from app.services.memory_reduce import (
    named_entity_count,
    reduce_chapter_analysis,
    reduce_novel_memory,
)
from app.services.memory_repository import MemoryRepository
from sqlalchemy import func, select


def _now() -> datetime:
    return datetime.now(UTC)


def _payload(sequence: int, *, goal: str = "找伞") -> ChapterAnalysisPayload:
    return ChapterAnalysisPayload(
        summary=ChapterSummary(synopsis=f"第{sequence}章"),
        characters=[
            CharacterMention(
                name="林深",
                aliases=["阿深"] if sequence == 2 else [],
                identity="雨巷少年",
                goal=goal,
            )
        ],
        locations=[LocationMention(name="雨巷", description="窄")],
        events=[EventRecord(summary="遇见旧伞", participants=["林深"], importance="medium")],
        relationships=[RelationshipRecord(source="林深", target="阿婉", relation_type="相识")],
        timeline=[TimelineEntry(order_key=sequence, summary=f"第{sequence}日")],
        foreshadowing=[ForeshadowingItem(clue="旧伞", status="planted")],
        open_questions=[],
        world_facts=[WorldFactItem(fact="雨巷常年阴雨", category="rule")],
        style_signals=StyleSignals(pov="third", pacing="slow"),
    )


def _store(session, chapter, payload: ChapterAnalysisPayload) -> None:
    version = session.get(ChapterVersion, chapter.current_canon_version_id)
    assert version is not None
    persist_chapter_analysis(
        session,
        chapter,
        version,
        payload=payload,
        analyzer_version="test",
        model_profile_id="fake",
        prompt_version="p",
        profile_version="s",
    )


def test_eighteen_chapters_reduce_in_sequence(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapters = [
                catalog.create_chapter(session, novel.id, body=f"第{index}章。")
                for index in range(1, 19)
            ]
            for index, chapter in enumerate(chapters, start=1):
                _store(session, chapter, _payload(index))
            report = reduce_novel_memory(session, novel.id)
            assert report.chapter_ids == [chapter.id for chapter in chapters]
            assert report.conflicts == []
            assert report.unresolved == []
            names = {
                row.name: list(row.aliases)
                for row in session.scalars(
                    select(MemoryCharacter).where(MemoryCharacter.novel_id == novel.id)
                )
            }
            assert names["林深"] == ["阿深"]
            assert "阿婉" in names
            assert _count(session, MemoryEvent, novel.id) == 1
            assert _count(session, MemoryTimeline, novel.id) == 18
            assert _count(session, MemoryForeshadowing, novel.id) == 1
            assert _count(session, MemoryWorldFact, novel.id) == 2
            assert named_entity_count(session, novel.id) == 1
            profile = session.scalar(
                select(MemoryStyleProfile).where(MemoryStyleProfile.novel_id == novel.id)
            )
            assert profile is not None
            assert profile.features["pov"] == "third"
            assert profile.statistics["chapter_count"] == 18
            repo = MemoryRepository(session)
            goals = repo.query_facts(
                novel.id,
                subject_kind=MemorySubjectKind.CHARACTER,
                fact_key="goal",
                status=FactStatus.ACTIVE,
            )
            assert len(goals) == 1
            assert goals[0].fact_value == {"value": "找伞"}
            assert goals[0].confidence > 0.7
            assert goals[0].source_chapter_version_id
            sourced = repo.query_facts(novel.id, status=FactStatus.ACTIVE)
            assert sourced
            assert all(fact.source_chapter_version_id for fact in sourced)
    finally:
        engine.dispose()


def test_repeated_fact_reinforces_and_conflict_does_not_overwrite(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            first = catalog.create_chapter(session, novel.id, body="第一章。")
            second = catalog.create_chapter(session, novel.id, body="第二章。")
            _store(session, first, _payload(1, goal="找伞"))
            _store(session, second, _payload(2, goal="放弃"))
            report = reduce_novel_memory(session, novel.id)
            goals = MemoryRepository(session).query_facts(
                novel.id,
                subject_kind=MemorySubjectKind.CHARACTER,
                fact_key="goal",
                status=FactStatus.ACTIVE,
            )
            assert len(goals) == 1
            assert goals[0].fact_value == {"value": "找伞"}
            assert report.facts_reinforced > 0
            assert any(item.fact_key == "goal" for item in report.conflicts)
            assert _count(session, MemoryCharacter, novel.id) == 2
    finally:
        engine.dispose()


def test_draft_source_is_not_reduced(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="原文。")
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            draft = add_draft_version(chapter, body="草稿。", parent=canon, created_at=_now())
            session.flush()
            with pytest.raises(MemoryError) as caught:
                reduce_chapter_analysis(
                    session,
                    novel_id=novel.id,
                    chapter=chapter,
                    source_version=draft,
                    payload=_payload(1),
                )
            assert caught.value.code == "draft_cannot_be_memory_source"
            assert _count(session, MemoryCharacter, novel.id) == 0
    finally:
        engine.dispose()


def _count(session, model, novel_id: str) -> int:
    return int(
        session.scalar(select(func.count()).select_from(model).where(model.novel_id == novel_id))
        or 0
    )
