from datetime import UTC, datetime

import pytest
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chapter_canon import add_draft_version
from app.domain.memory import FactOrigin, MemoryError, MemorySubjectKind
from app.services import catalog
from app.services.memory_facts import read_fact_provenance, record_memory_fact


def _now() -> datetime:
    return datetime.now(UTC)


def test_explicit_fact_points_at_canon_text_and_inferred_does_not_claim_a_span(
    isolated_data_dir,
) -> None:
    body = "林深走进雨巷。"
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body=body)
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            start = body.index("雨巷")
            end = start + len("雨巷")
            explicit = record_memory_fact(
                session,
                novel_id=novel.id,
                subject_kind=MemorySubjectKind.CHARACTER,
                subject_id="char-1",
                fact_key="location",
                fact_value={"text": "雨巷"},
                source_chapter=chapter,
                source_version=canon,
                origin=FactOrigin.EXPLICIT,
                confidence=0.9,
                start_offset=start,
                end_offset=end,
                locked=True,
            )
            found = read_fact_provenance(session, explicit.id)
            assert found.origin == "explicit"
            assert found.chapter_id == chapter.id
            assert found.chapter_version_id == canon.id
            assert found.version_kind == "ORIGINAL"
            assert found.source_text == "雨巷"
            assert found.source_text_hash == explicit.source_text_hash
            assert explicit.locked is True
            assert explicit.superseded_by_id is None

            inferred = record_memory_fact(
                session,
                novel_id=novel.id,
                subject_kind=MemorySubjectKind.CHARACTER,
                subject_id="char-1",
                fact_key="goal",
                fact_value={"text": "寻路"},
                source_chapter=chapter,
                source_version=canon,
                origin=FactOrigin.INFERRED,
                confidence=0.4,
                revision=1,
            )
            inferred_view = read_fact_provenance(session, inferred.id)
            assert inferred_view.origin == "inferred"
            assert inferred_view.source_text is None
            assert inferred_view.chapter_version_id == canon.id
            with pytest.raises(MemoryError) as claimed:
                record_memory_fact(
                    session,
                    novel_id=novel.id,
                    subject_kind=MemorySubjectKind.CHARACTER,
                    subject_id="char-1",
                    fact_key="mood",
                    fact_value={"text": "静"},
                    source_chapter=chapter,
                    source_version=canon,
                    origin=FactOrigin.INFERRED,
                    confidence=0.4,
                    start_offset=start,
                    end_offset=end,
                )
            assert claimed.value.code == "inferred_cannot_claim_explicit_span"
    finally:
        engine.dispose()


def test_draft_cannot_enter_official_memory(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="原文。")
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            draft = add_draft_version(
                chapter, body="草稿里的新事实。", parent=canon, created_at=_now()
            )
            session.flush()
            with pytest.raises(MemoryError) as caught:
                record_memory_fact(
                    session,
                    novel_id=novel.id,
                    subject_kind=MemorySubjectKind.WORLD_FACT,
                    subject_id="world-1",
                    fact_key="rule",
                    fact_value={"text": "草稿"},
                    source_chapter=chapter,
                    source_version=draft,
                    origin=FactOrigin.EXPLICIT,
                    confidence=1,
                    start_offset=0,
                    end_offset=2,
                )
            assert caught.value.code == "draft_cannot_be_memory_source"
    finally:
        engine.dispose()
