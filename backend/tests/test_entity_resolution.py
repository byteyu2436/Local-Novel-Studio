from datetime import UTC, datetime

import pytest
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.memory import MemoryCharacter, MemoryNamedEntity
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chapter_canon import add_draft_version
from app.domain.entity_resolution import EntityKind, ResolutionAction
from app.domain.memory import MemoryError
from app.services import catalog
from app.services.entity_resolution import list_resolution_candidates, resolve_mention
from sqlalchemy import func, select


def _now() -> datetime:
    return datetime.now(UTC)


def test_explicit_alias_merges_and_same_name_stays_separate(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深又名阿深。")
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            created = resolve_mention(
                session,
                novel_id=novel.id,
                kind=EntityKind.CHARACTER,
                name="林深",
                aliases=["阿深"],
                source_chapter=chapter,
                source_version=canon,
            )
            assert created.decision == ResolutionAction.CREATED.value
            assert created.reason == "no_match"
            nickname = resolve_mention(
                session,
                novel_id=novel.id,
                kind=EntityKind.CHARACTER,
                name="阿深",
                source_chapter=chapter,
                source_version=canon,
            )
            assert nickname.decision == ResolutionAction.MERGED.value
            assert nickname.reason == "exact_alias"
            assert nickname.entity_id == created.entity_id
            assert nickname.source_chapter_version_id == canon.id
            phrase = resolve_mention(
                session,
                novel_id=novel.id,
                kind=EntityKind.CHARACTER,
                name="林深",
                phrase="林深，称作小深",
                source_chapter=chapter,
                source_version=canon,
            )
            assert phrase.decision == ResolutionAction.MERGED.value
            assert phrase.reason == "explicit_alias"
            stored = session.get(MemoryCharacter, created.entity_id)
            assert stored is not None
            assert stored.aliases == ["阿深", "小深"]
            count = session.scalar(
                select(func.count())
                .select_from(MemoryCharacter)
                .where(MemoryCharacter.novel_id == novel.id)
            )
            assert count == 1

            from app.services.memory_repository import MemoryRepository

            repo = MemoryRepository(session)
            twin = repo.create_character(novel.id, "林深")
            same = resolve_mention(
                session,
                novel_id=novel.id,
                kind=EntityKind.CHARACTER,
                name="林深",
                source_chapter=chapter,
                source_version=canon,
            )
            assert same.decision == ResolutionAction.CANDIDATE.value
            assert same.reason == "same_name"
            assert set(same.candidate_entity_ids) == {created.entity_id, twin.id}
            assert list_resolution_candidates(session, novel.id)[0].id == same.id
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(MemoryCharacter)
                    .where(MemoryCharacter.novel_id == novel.id)
                )
                == 2
            )
    finally:
        engine.dispose()


def test_low_confidence_partial_name_does_not_merge(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="雨巷很窄。")
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            created = resolve_mention(
                session,
                novel_id=novel.id,
                kind=EntityKind.LOCATION,
                name="雨巷",
                source_chapter=chapter,
                source_version=canon,
            )
            partial = resolve_mention(
                session,
                novel_id=novel.id,
                kind=EntityKind.LOCATION,
                name="雨",
                source_chapter=chapter,
                source_version=canon,
            )
            assert partial.decision == ResolutionAction.CANDIDATE.value
            assert partial.reason == "low_confidence"
            assert partial.candidate_entity_ids == [created.entity_id]
            places = session.scalars(
                select(MemoryNamedEntity).where(MemoryNamedEntity.novel_id == novel.id)
            ).all()
            assert [item.name for item in places] == ["雨巷"]
    finally:
        engine.dispose()


def test_draft_cannot_resolve_into_memory(isolated_data_dir) -> None:
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
                resolve_mention(
                    session,
                    novel_id=novel.id,
                    kind=EntityKind.ORGANIZATION,
                    name="雨会",
                    source_chapter=chapter,
                    source_version=draft,
                )
            assert caught.value.code == "draft_cannot_be_memory_source"
    finally:
        engine.dispose()
