from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.migrate import alembic_config
from app.adapters.sqlite.models import Chapter, ChapterVersion, Novel
from app.domain.chapter import TitleSource, VersionKind
from app.settings import get_settings
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def _now() -> datetime:
    return datetime.now(UTC)


def test_migration_creates_novel_chapter_tables(isolated_data_dir) -> None:
    settings, engine, _factory = bootstrap_local_runtime()
    try:
        inspector = inspect(engine)
        names = inspector.get_table_names()
        assert "novels" in names
        assert "chapters" in names
        assert "chapter_versions" in names
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert version == "0004_novels_chapters"
    finally:
        engine.dispose()


def test_orm_roundtrip_separates_original_and_display_title(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = Novel(
                id=str(uuid4()),
                title="雨巷",
                created_at=_now(),
                updated_at=_now(),
            )
            chapter = Chapter(
                id=str(uuid4()),
                novel_id=novel.id,
                sequence=1,
                original_label="第一章",
                original_title="开场",
                display_title="第1章 开场",
                title_source=TitleSource.ORIGINAL.value,
                title_confidence=0.95,
                created_at=_now(),
                updated_at=_now(),
            )
            original = ChapterVersion(
                id=str(uuid4()),
                chapter_id=chapter.id,
                version_kind=VersionKind.ORIGINAL.value,
                body="林深走进雨里。",
                import_source_id=None,
                start_offset=0,
                end_offset=8,
                source_checksum="abc",
                created_at=_now(),
            )
            session.add_all([novel, chapter, original])
            session.flush()
            chapter.current_canon_version_id = original.id
            session.flush()
            stored = session.get(Chapter, chapter.id)
            assert stored is not None
            assert stored.original_title == "开场"
            assert stored.display_title == "第1章 开场"
            assert stored.current_canon_version_id == original.id
            assert stored.versions[0].version_kind == VersionKind.ORIGINAL.value
    finally:
        engine.dispose()


def test_original_version_unique_and_immutable(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            session.add_all(
                [
                    Novel(id="n1", title="x", created_at=_now(), updated_at=_now()),
                    Chapter(
                        id="c1",
                        novel_id="n1",
                        sequence=1,
                        display_title="第1章",
                        title_source=TitleSource.FALLBACK.value,
                        created_at=_now(),
                        updated_at=_now(),
                    ),
                    ChapterVersion(
                        id="v1",
                        chapter_id="c1",
                        version_kind=VersionKind.ORIGINAL.value,
                        body="原文",
                        created_at=_now(),
                    ),
                ]
            )
        for session in session_scope(factory):
            session.add(
                ChapterVersion(
                    id="v2",
                    chapter_id="c1",
                    version_kind=VersionKind.ORIGINAL.value,
                    body="另一份原文",
                    created_at=_now(),
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
        for session in session_scope(factory):
            row = session.get(ChapterVersion, "v1")
            assert row is not None
            row.body = "被覆盖"
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
    finally:
        engine.dispose()


def test_upgrade_from_previous_revision(isolated_data_dir) -> None:
    settings, engine, _factory = bootstrap_local_runtime()
    engine.dispose()
    config = alembic_config(get_settings())
    command.downgrade(config, "0003_import_encoding")
    command.upgrade(config, "head")
    settings, engine, _factory = bootstrap_local_runtime()
    try:
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert version == "0004_novels_chapters"
        assert "chapters" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
