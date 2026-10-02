from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.memory import (
    MemoryCharacter,
    MemoryFact,
    MemoryForeshadowing,
    MemoryRelationship,
    MemoryStyleProfile,
)
from app.domain.memory import FORESHADOWING_STATUSES, MemorySubjectKind
from app.services import catalog
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError


def _now() -> datetime:
    return datetime.now(UTC)


def test_migration_creates_memory_tables(isolated_data_dir) -> None:
    _settings, engine, _factory = bootstrap_local_runtime()
    try:
        names = inspect(engine).get_table_names()
        assert "memory_characters" in names
        assert "memory_relationships" in names
        assert "memory_events" in names
        assert "memory_timelines" in names
        assert "memory_foreshadowings" in names
        assert "memory_world_facts" in names
        assert "memory_style_profiles" in names
        assert "memory_facts" in names
        character_columns = {
            column["name"] for column in inspect(engine).get_columns("memory_characters")
        }
        assert "name" in character_columns
        assert "location" not in character_columns
        assert "body" not in {
            column["name"] for column in inspect(engine).get_columns("memory_style_profiles")
        }
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert version == "0018_continuation"
    finally:
        engine.dispose()


def test_memory_rows_stay_inside_their_novel(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            rain = catalog.create_novel(session, "雨巷")
            other = catalog.create_novel(session, "另一本")
            now = _now()
            session.add_all(
                [
                    MemoryCharacter(
                        id=str(uuid4()),
                        novel_id=rain.id,
                        name="林深",
                        aliases=["阿深"],
                        created_at=now,
                        updated_at=now,
                    ),
                    MemoryCharacter(
                        id=str(uuid4()),
                        novel_id=other.id,
                        name="别人",
                        aliases=[],
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            session.flush()
            names = session.scalars(
                select(MemoryCharacter.name).where(MemoryCharacter.novel_id == rain.id)
            ).all()
            assert names == ["林深"]
    finally:
        engine.dispose()


def test_foreshadowing_accepts_full_lifecycle_and_rejects_unknown_status(
    isolated_data_dir,
) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            now = _now()
            for status in FORESHADOWING_STATUSES:
                session.add(
                    MemoryForeshadowing(
                        id=str(uuid4()),
                        novel_id=novel.id,
                        label=f"伏笔-{status}",
                        status=status,
                        created_at=now,
                        updated_at=now,
                    )
                )
            session.flush()
            session.add(
                MemoryForeshadowing(
                    id=str(uuid4()),
                    novel_id=novel.id,
                    label="坏状态",
                    status="open",
                    created_at=now,
                    updated_at=now,
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
    finally:
        engine.dispose()


def test_relationship_links_characters_and_active_fact_is_unique(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            now = _now()
            source = MemoryCharacter(
                id=str(uuid4()),
                novel_id=novel.id,
                name="林深",
                aliases=[],
                created_at=now,
                updated_at=now,
            )
            target = MemoryCharacter(
                id=str(uuid4()),
                novel_id=novel.id,
                name="鹿",
                aliases=[],
                created_at=now,
                updated_at=now,
            )
            session.add_all([source, target])
            link = MemoryRelationship(
                id=str(uuid4()),
                novel_id=novel.id,
                source_character_id=source.id,
                target_character_id=target.id,
                created_at=now,
                updated_at=now,
            )
            session.add(link)
            session.add(
                MemoryStyleProfile(
                    id=str(uuid4()),
                    novel_id=novel.id,
                    features={"sentence": "short"},
                    statistics={"dialogue_ratio": 0.2},
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                MemoryFact(
                    id=str(uuid4()),
                    novel_id=novel.id,
                    subject_kind=MemorySubjectKind.CHARACTER.value,
                    subject_id=source.id,
                    fact_key="location",
                    fact_value={"text": "雨巷"},
                    revision=1,
                    active=True,
                    created_at=now,
                )
            )
            session.add(
                MemoryFact(
                    id=str(uuid4()),
                    novel_id=novel.id,
                    subject_kind=MemorySubjectKind.CHARACTER.value,
                    subject_id=source.id,
                    fact_key="location",
                    fact_value={"text": "旧位置"},
                    revision=2,
                    active=False,
                    status="superseded",
                    created_at=now,
                )
            )
            session.flush()
            stored = session.get(MemoryRelationship, link.id)
            assert stored is not None
            assert stored.source_character_id == source.id
            session.add(
                MemoryFact(
                    id=str(uuid4()),
                    novel_id=novel.id,
                    subject_kind=MemorySubjectKind.CHARACTER.value,
                    subject_id=source.id,
                    fact_key="location",
                    fact_value={"text": "冲突位置"},
                    revision=3,
                    active=True,
                    created_at=now,
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
    finally:
        engine.dispose()
