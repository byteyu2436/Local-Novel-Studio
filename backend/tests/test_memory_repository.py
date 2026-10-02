from datetime import UTC, datetime

import pytest
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chapter_canon import add_draft_version
from app.domain.memory import FactOrigin, FactStatus, MemoryError
from app.services import catalog
from app.services.memory_repository import MemoryRepository, memory_transaction


def _now() -> datetime:
    return datetime.now(UTC)


def test_repository_projects_active_facts_and_isolates_novels(isolated_data_dir) -> None:
    body = "林深走进雨巷。"
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            other = catalog.create_novel(session, "另一本")
            chapter = catalog.create_chapter(session, novel.id, body=body)
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            repo = MemoryRepository(session)
            assert repo.memory_revision(novel.id) == 0
            character = repo.create_character(novel.id, "林深", ["阿深"])
            repo.create_event(novel.id, "相遇")
            assert repo.memory_revision(novel.id) == 2
            assert [item.label for item in repo.list_events(novel.id)] == ["相遇"]

            rain = body.index("雨巷")
            first = repo.revise_fact(
                novel_id=novel.id,
                subject_kind="character",
                subject_id=character.id,
                fact_key="location",
                fact_value={"text": "雨巷"},
                source_chapter=chapter,
                source_version=canon,
                origin=FactOrigin.EXPLICIT,
                confidence=0.95,
                start_offset=rain,
                end_offset=rain + len("雨巷"),
            )
            assert repo.character_state(character.id).current["location"]["text"] == "雨巷"
            gate = body.index("林深")
            second = repo.revise_fact(
                novel_id=novel.id,
                subject_kind="character",
                subject_id=character.id,
                fact_key="location",
                fact_value={"text": "林深"},
                source_chapter=chapter,
                source_version=canon,
                origin=FactOrigin.EXPLICIT,
                confidence=0.8,
                start_offset=gate,
                end_offset=gate + len("林深"),
            )
            assert second.revision == 2
            assert first.status == FactStatus.SUPERSEDED.value
            assert first.superseded_by_id == second.id
            assert repo.character_state(character.id).current["location"]["text"] == "林深"
            assert repo.memory_revision(novel.id) == 4
            previous = repo.query_facts(novel.id, subject_id=character.id, revision=1)
            assert [item.id for item in previous] == [first.id]
            origin = repo.provenance(second.id)
            assert origin.chapter_version_id == canon.id
            assert origin.source_text == "林深"
            assert repo.list_characters(other.id) == []
            assert repo.query_facts(other.id, subject_id=character.id) == []
    finally:
        engine.dispose()


def test_locked_fact_and_draft_source_do_not_change_revision(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="原文。")
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            repo = MemoryRepository(session)
            character = repo.create_character(novel.id, "林深")
            repo.revise_fact(
                novel_id=novel.id,
                subject_kind="character",
                subject_id=character.id,
                fact_key="location",
                fact_value={"text": "原文"},
                source_chapter=chapter,
                source_version=canon,
                origin=FactOrigin.EXPLICIT,
                confidence=1,
                start_offset=0,
                end_offset=2,
                locked=True,
            )
            revision = repo.memory_revision(novel.id)
            with pytest.raises(MemoryError) as locked:
                repo.revise_fact(
                    novel_id=novel.id,
                    subject_kind="character",
                    subject_id=character.id,
                    fact_key="location",
                    fact_value={"text": "别处"},
                    source_chapter=chapter,
                    source_version=canon,
                    origin=FactOrigin.INFERRED,
                    confidence=0.2,
                )
            assert locked.value.code == "fact_locked"
            draft = add_draft_version(chapter, body="草稿。", parent=canon, created_at=_now())
            session.flush()
            with pytest.raises(MemoryError) as caught:
                repo.revise_fact(
                    novel_id=novel.id,
                    subject_kind="character",
                    subject_id=character.id,
                    fact_key="goal",
                    fact_value={"text": "草稿"},
                    source_chapter=chapter,
                    source_version=draft,
                    origin=FactOrigin.INFERRED,
                    confidence=0.2,
                )
            assert caught.value.code == "draft_cannot_be_memory_source"
            assert repo.memory_revision(novel.id) == revision
            assert repo.character_state(character.id).current["location"]["text"] == "原文"
    finally:
        engine.dispose()


def test_memory_transaction_rolls_back_together(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    novel_id = ""
    try:
        for session in session_scope(factory):
            novel_id = catalog.create_novel(session, "雨巷").id
        for session in session_scope(factory):
            repo = MemoryRepository(session)
            with pytest.raises(RuntimeError):
                with memory_transaction(session):
                    repo.create_character(novel_id, "林深")
                    raise RuntimeError("boom")
            assert repo.list_characters(novel_id) == []
            assert repo.memory_revision(novel_id) == 0
    finally:
        engine.dispose()
