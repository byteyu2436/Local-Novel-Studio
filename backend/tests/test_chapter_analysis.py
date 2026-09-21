from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.migrate import alembic_config
from app.adapters.sqlite.models import Chapter, ChapterAnalysis, ChapterVersion, Novel
from app.domain.analysis import (
    CHAPTER_ANALYSIS_SCHEMA_VERSION,
    AnalysisError,
    require_canon_analysis_source,
)
from app.domain.analysis_profile import ANALYZER_PROFILE_VERSION
from app.domain.chapter import TitleSource, VersionKind
from app.domain.chapter_canon import add_draft_version
from app.prompts.chapter_analyzer import CHAPTER_ANALYZER_PROMPT_VERSION
from app.schemas.analysis import parse_chapter_analysis_payload
from app.services import catalog
from app.services.analysis import (
    analysis_result_dto,
    get_chapter_analysis,
    persist_chapter_analysis,
)
from app.services.chapter_canon import persist_accepted_canon
from app.settings import get_settings
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def _now() -> datetime:
    return datetime.now(UTC)


def _trace(**overrides: str) -> dict[str, str]:
    values = {
        "analyzer_version": "analyzer.test",
        "model_profile_id": "analyzer-default",
        "prompt_version": CHAPTER_ANALYZER_PROMPT_VERSION,
        "profile_version": ANALYZER_PROFILE_VERSION,
    }
    values.update(overrides)
    return values


def _valid_payload() -> dict:
    return {
        "summary": {
            "synopsis": "林深在雨巷遇见一只鹿。",
            "core_events": "相遇",
            "mood": "静谧",
        },
        "characters": [
            {
                "name": "林深",
                "aliases": ["阿深"],
                "identity": "旅人",
                "personality": "克制",
                "goal": "寻路",
                "secret": "",
                "current_state": "淋雨",
                "evidence": "林深走进雨里。",
            }
        ],
        "locations": [{"name": "雨巷", "aliases": [], "description": "窄巷"}],
        "events": [
            {
                "summary": "林深遇见鹿",
                "participants": ["林深"],
                "location": "雨巷",
                "time_label": "傍晚",
                "importance": "high",
                "cause": "",
                "effect": "",
            }
        ],
        "relationships": [
            {
                "source": "林深",
                "target": "鹿",
                "relation_type": "初遇",
                "trust_or_conflict": "",
                "current_state": "陌生",
            }
        ],
        "timeline": [
            {
                "order_key": 0,
                "summary": "进入雨巷",
                "explicit_time": None,
                "relative_time": "开篇",
                "uncertainty": "approximate",
            }
        ],
        "foreshadowing": [
            {"clue": "鹿回头", "status": "planted", "evidence": "它停了一下。"}
        ],
        "open_questions": [{"question": "鹿从哪里来？", "urgency": "normal"}],
        "world_facts": [
            {
                "fact": "雨巷在入夜后更暗",
                "category": "location",
                "inferred": False,
                "evidence": "天色压下来。",
            }
        ],
        "style_signals": {
            "pov": "第三人称",
            "sentence_length": "短句",
            "dialogue_ratio": "低",
            "description_bias": "景物",
            "pacing": "缓",
            "chapter_length": "短",
            "transition_style": "直入",
        },
    }


def test_valid_payload_roundtrips_schema_version() -> None:
    parsed = parse_chapter_analysis_payload(_valid_payload())
    dumped = parsed.model_dump(mode="json")
    assert dumped["summary"]["synopsis"].startswith("林深")
    assert parse_chapter_analysis_payload(dumped).summary.mood == "静谧"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.pop("summary"),
        lambda data: data.update({"extra": True}),
        lambda data: data["summary"].update({"synopsis": ""}),
        lambda data: data["foreshadowing"][0].update({"status": "paid_off"}),
        lambda data: data.pop("style_signals"),
    ],
)
def test_invalid_payload_is_rejected(mutate) -> None:
    data = _valid_payload()
    mutate(data)
    with pytest.raises(AnalysisError) as caught:
        parse_chapter_analysis_payload(data)
    assert caught.value.code == "analysis_schema_invalid"


def test_migration_creates_chapter_analysis_table(isolated_data_dir) -> None:
    _settings, engine, _factory = bootstrap_local_runtime()
    try:
        names = inspect(engine).get_table_names()
        assert "chapter_analysis" in names
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert version == "0006_analysis_prompt_trace"
    finally:
        engine.dispose()


def test_upgrade_from_chapter_schema_revision(isolated_data_dir) -> None:
    settings, engine, _factory = bootstrap_local_runtime()
    engine.dispose()
    config = alembic_config(get_settings())
    command.downgrade(config, "0004_novels_chapters")
    command.upgrade(config, "head")
    settings, engine, _factory = bootstrap_local_runtime()
    try:
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert version == "0006_analysis_prompt_trace"
        assert "chapter_analysis" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_persists_validated_result_with_versions(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(
                session, novel.id, body="林深走进雨里。", original_title="开场"
            )
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            row = persist_chapter_analysis(
                session,
                chapter,
                canon,
                payload=_valid_payload(),
                model_ref="qwen3.5:9b",
                **_trace(),
            )
            dto = analysis_result_dto(row)
            assert dto.schema_version == CHAPTER_ANALYSIS_SCHEMA_VERSION
            assert dto.analyzer_version == "analyzer.test"
            assert dto.prompt_version == CHAPTER_ANALYZER_PROMPT_VERSION
            assert dto.profile_version == ANALYZER_PROFILE_VERSION
            assert dto.model_profile_id == "analyzer-default"
            assert dto.model_ref == "qwen3.5:9b"
            assert dto.source_version_kind == VersionKind.ORIGINAL.value
            assert dto.payload.characters[0].name == "林深"
            stored = get_chapter_analysis(session, chapter.id, canon.id)
            assert stored is not None
            assert stored.id == row.id
    finally:
        engine.dispose()


def test_invalid_payload_does_not_persist(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深走进雨里。")
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            broken = _valid_payload()
            broken.pop("events")
            with pytest.raises(AnalysisError) as caught:
                persist_chapter_analysis(
                    session,
                    chapter,
                    canon,
                    payload=broken,
                    **_trace(),
                )
            assert caught.value.code == "analysis_schema_invalid"
            assert session.scalar(text("SELECT COUNT(*) FROM chapter_analysis")) == 0
    finally:
        engine.dispose()


def test_unsupported_schema_version_is_rejected(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深走进雨里。")
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            with pytest.raises(AnalysisError) as caught:
                persist_chapter_analysis(
                    session,
                    chapter,
                    canon,
                    payload=_valid_payload(),
                    schema_version="chapter-analysis.v2",
                    **_trace(),
                )
            assert caught.value.code == "unsupported_schema_version"
    finally:
        engine.dispose()


def test_draft_cannot_be_official_analysis_source(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深走进雨里。")
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            draft = add_draft_version(
                chapter, body="林深停住了。", parent=canon, created_at=_now()
            )
            session.add(draft)
            session.flush()
            with pytest.raises(AnalysisError) as caught:
                persist_chapter_analysis(
                    session,
                    chapter,
                    draft,
                    payload=_valid_payload(),
                    **_trace(),
                )
            assert caught.value.code == "draft_cannot_be_analysis_source"
            require_canon_analysis_source(chapter, canon)
            with pytest.raises(AnalysisError):
                require_canon_analysis_source(chapter, draft)
            assert get_chapter_analysis(session, chapter.id, draft.id) is None
    finally:
        engine.dispose()


def test_superseded_original_cannot_be_official_source(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深走进雨里。")
            original = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert original is not None
            draft = add_draft_version(
                chapter, body="林深停住了。", parent=original, created_at=_now()
            )
            session.add(draft)
            session.flush()
            accepted = persist_accepted_canon(session, chapter, draft, created_at=_now())
            with pytest.raises(AnalysisError) as caught:
                persist_chapter_analysis(
                    session,
                    chapter,
                    original,
                    payload=_valid_payload(),
                    **_trace(),
                )
            assert caught.value.code == "analysis_requires_current_canon"
            row = persist_chapter_analysis(
                session,
                chapter,
                accepted,
                payload=_valid_payload(),
                **_trace(),
            )
            assert row.source_version_kind == VersionKind.ACCEPTED.value
    finally:
        engine.dispose()


def test_check_constraint_rejects_draft_kind_row(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            now = _now()
            novel_id = str(uuid4())
            chapter_id = str(uuid4())
            draft_id = str(uuid4())
            session.add_all(
                [
                    Novel(id=novel_id, title="x", created_at=now, updated_at=now),
                    Chapter(
                        id=chapter_id,
                        novel_id=novel_id,
                        sequence=1,
                        display_title="第1章",
                        title_source=TitleSource.FALLBACK.value,
                        created_at=now,
                        updated_at=now,
                    ),
                    ChapterVersion(
                        id=draft_id,
                        chapter_id=chapter_id,
                        version_kind=VersionKind.DRAFT.value,
                        body="草稿",
                        created_at=now,
                    ),
                ]
            )
            session.flush()
            session.add(
                ChapterAnalysis(
                    id=str(uuid4()),
                    chapter_id=chapter_id,
                    source_version_id=draft_id,
                    source_version_kind=VersionKind.DRAFT.value,
                    schema_version=CHAPTER_ANALYSIS_SCHEMA_VERSION,
                    analyzer_version="x",
                    prompt_version=CHAPTER_ANALYZER_PROMPT_VERSION,
                    profile_version=ANALYZER_PROFILE_VERSION,
                    model_profile_id="analyzer-default",
                    payload=_valid_payload(),
                    created_at=now,
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
    finally:
        engine.dispose()
