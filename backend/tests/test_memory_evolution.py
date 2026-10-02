from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.memory import MemoryForeshadowing, MemoryRelationship
from app.adapters.sqlite.models import ChapterVersion
from app.domain.memory import FactStatus, MemorySubjectKind
from app.schemas.analysis import (
    ChapterAnalysisPayload,
    ChapterSummary,
    CharacterMention,
    EventRecord,
    ForeshadowingItem,
    RelationshipRecord,
    StyleSignals,
    TimelineEntry,
)
from app.services import catalog
from app.services.analysis import persist_chapter_analysis
from app.services.memory_reduce import reduce_novel_memory
from app.services.memory_repository import MemoryRepository
from sqlalchemy import select


def _empty_payload() -> dict:
    return {
        "summary": ChapterSummary(synopsis="一章"),
        "characters": [],
        "locations": [],
        "events": [],
        "relationships": [],
        "timeline": [],
        "foreshadowing": [],
        "open_questions": [],
        "world_facts": [],
        "style_signals": StyleSignals(),
    }


def _store(session, chapter, **overrides) -> None:
    version = session.get(ChapterVersion, chapter.current_canon_version_id)
    assert version is not None
    payload = ChapterAnalysisPayload(**{**_empty_payload(), **overrides})
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


def test_character_state_keeps_history_and_goal_stays_candidate(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            first = catalog.create_chapter(session, novel.id, body="第一章。")
            second = catalog.create_chapter(session, novel.id, body="第二章。")
            _store(
                session,
                first,
                characters=[CharacterMention(name="林深", current_state="在雨巷", goal="找伞")],
            )
            _store(
                session,
                second,
                characters=[CharacterMention(name="林深", current_state="离开雨巷", goal="放弃")],
            )
            report = reduce_novel_memory(session, novel.id)
            repo = MemoryRepository(session)
            history = repo.query_facts(
                novel.id,
                subject_kind=MemorySubjectKind.CHARACTER,
                fact_key="current_state",
            )
            assert [item.fact_value["value"] for item in history] == ["在雨巷", "离开雨巷"]
            assert history[0].status == FactStatus.SUPERSEDED.value
            assert history[1].status == FactStatus.ACTIVE.value
            assert history[0].source_chapter_id == first.id
            assert history[1].source_chapter_id == second.id
            goals = repo.query_facts(
                novel.id,
                subject_kind=MemorySubjectKind.CHARACTER,
                fact_key="goal",
            )
            assert [item.fact_value["value"] for item in goals] == ["找伞"]
            assert any(
                item.fact_key == "goal" and item.reason == "supersede_candidate"
                for item in report.conflicts
            )
    finally:
        engine.dispose()


def test_relationship_evolution_keeps_earlier_source(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            first = catalog.create_chapter(session, novel.id, body="第一章。")
            second = catalog.create_chapter(session, novel.id, body="第二章。")
            _store(
                session,
                first,
                relationships=[
                    RelationshipRecord(
                        source="林深",
                        target="阿婉",
                        relation_type="相识",
                        trust_or_conflict="戒备",
                    )
                ],
            )
            _store(
                session,
                second,
                relationships=[
                    RelationshipRecord(
                        source="林深",
                        target="阿婉",
                        relation_type="同盟",
                        trust_or_conflict="信任",
                    )
                ],
            )
            reduce_novel_memory(session, novel.id)
            pair = session.scalar(
                select(MemoryRelationship).where(MemoryRelationship.novel_id == novel.id)
            )
            assert pair is not None
            history = MemoryRepository(session).query_facts(
                novel.id,
                subject_kind=MemorySubjectKind.RELATIONSHIP,
                subject_id=pair.id,
                fact_key="relation_type",
            )
            assert [item.fact_value["value"] for item in history] == ["相识", "同盟"]
            assert history[0].source_chapter_id == first.id
            assert history[1].source_chapter_id == second.id
            assert history[0].status == FactStatus.SUPERSEDED.value
    finally:
        engine.dispose()


def test_timeline_uncertainty_and_foreshadowing_lifecycle(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapters = [
                catalog.create_chapter(session, novel.id, body=f"第{index}章。")
                for index in range(1, 5)
            ]
            for chapter, status in zip(
                chapters, ["planted", "reinforced", "resolved", "planted"], strict=True
            ):
                _store(
                    session,
                    chapter,
                    timeline=[
                        TimelineEntry(
                            order_key=1,
                            summary="旧伞出现",
                            relative_time="三天后",
                            uncertainty="approximate",
                        )
                    ],
                    foreshadowing=[ForeshadowingItem(clue="旧伞", status=status)],
                    events=[EventRecord(summary="遇见旧伞")],
                )
            report = reduce_novel_memory(session, novel.id)
            repo = MemoryRepository(session)
            uncertainty = repo.query_facts(
                novel.id,
                subject_kind=MemorySubjectKind.TIMELINE,
                fact_key="uncertainty",
                status=FactStatus.ACTIVE,
            )
            relative = repo.query_facts(
                novel.id,
                subject_kind=MemorySubjectKind.TIMELINE,
                fact_key="relative_time",
                status=FactStatus.ACTIVE,
            )
            assert uncertainty[0].fact_value == {"value": "approximate"}
            assert relative[0].fact_value == {"value": "三天后"}
            clue = session.scalar(
                select(MemoryForeshadowing).where(MemoryForeshadowing.novel_id == novel.id)
            )
            assert clue is not None
            assert clue.status == "resolved"
            history = repo.query_facts(
                novel.id,
                subject_kind=MemorySubjectKind.FORESHADOWING,
                subject_id=clue.id,
                fact_key="status",
            )
            assert [item.fact_value["value"] for item in history] == [
                "planted",
                "reinforced",
                "resolved",
            ]
            assert history[0].source_chapter_id == chapters[0].id
            assert history[-1].source_chapter_id == chapters[2].id
            assert history[0].status == FactStatus.SUPERSEDED.value
            assert any(item.fact_key == "status" for item in report.conflicts)
    finally:
        engine.dispose()
