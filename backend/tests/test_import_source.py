from pathlib import Path

import pytest
from alembic import command
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.engine import create_sqlite_engine
from app.adapters.sqlite.import_sources import (
    create_paste_source,
    create_txt_source,
    get_import_source,
    set_parse_status,
    upsert_normalized_text,
)
from app.adapters.sqlite.migrate import alembic_config
from app.domain.importing import (
    ImportSourceImmutableError,
    ParseStatus,
    SourceType,
    relative_import_storage_path,
    sha256_hex,
)
from app.settings import get_settings
from app.storage.paths import ensure_data_layout
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def test_identical_payloads_share_checksum() -> None:
    payload = "第一章\n正文".encode()
    assert sha256_hex(payload) == sha256_hex(payload)
    assert sha256_hex(payload) != sha256_hex("第二章\n正文".encode())
    assert len(sha256_hex(payload)) == 64


def test_paste_checksum_is_stable_across_rows(isolated_data_dir: Path) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            first = create_paste_source(session, "第一章\n林深时见鹿")
            second = create_paste_source(session, "第一章\n林深时见鹿")
            third = create_paste_source(session, "第二章\n别的正文")
            assert first.id != second.id
            assert first.checksum == second.checksum == sha256_hex("第一章\n林深时见鹿".encode())
            assert third.checksum != first.checksum
            assert first.source_type == SourceType.PASTE
            assert first.parse_status == ParseStatus.RECEIVED
            assert first.raw_byte_size == len("第一章\n林深时见鹿".encode())
    finally:
        engine.dispose()


def test_txt_source_checksums_original_bytes(isolated_data_dir: Path) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    raw = "第1章 开场".encode("gbk")
    try:
        for session in session_scope(factory):
            source = create_txt_source(
                session,
                source_id="pending",
                original_filename="novel.txt",
                original_storage_path=relative_import_storage_path("pending", "novel.txt"),
                raw_bytes=raw,
                detected_encoding="gbk",
            )
            assert source.source_type == SourceType.TXT
            assert source.checksum == sha256_hex(raw)
            assert source.raw_text is None
            assert source.original_filename == "novel.txt"
            assert source.original_storage_path == "imports/pending/novel.txt"
            assert source.detected_encoding == "gbk"
            assert source.encoding_uncertain is False
    finally:
        engine.dispose()


def test_normalized_text_does_not_change_raw_snapshot(isolated_data_dir: Path) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    original = "第1章\r\n正文\r\n"
    try:
        for session in session_scope(factory):
            source = create_paste_source(session, original)
            upsert_normalized_text(session, source, "第1章\n正文\n")
            source_id = source.id
            checksum = source.checksum
        with factory() as session:
            stored = get_import_source(session, source_id)
            assert stored is not None
            assert stored.raw_text == original
            assert stored.checksum == checksum
            assert stored.parse_status == ParseStatus.NORMALIZED
            assert stored.normalized is not None
            assert stored.normalized.text == "第1章\n正文\n"
        for session in session_scope(factory):
            stored = get_import_source(session, source_id)
            assert stored is not None
            upsert_normalized_text(session, stored, "edited derived copy")
        with factory() as session:
            stored = get_import_source(session, source_id)
            assert stored is not None
            assert stored.raw_text == original
            assert stored.checksum == checksum
            assert stored.normalized is not None
            assert stored.normalized.text == "edited derived copy"
    finally:
        engine.dispose()


def test_orm_refuses_raw_snapshot_mutation(isolated_data_dir: Path) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            source = create_paste_source(session, "不可变原文")
            source_id = source.id
        with factory() as session:
            stored = get_import_source(session, source_id)
            assert stored is not None
            stored.raw_text = "被覆盖的正文"
            with pytest.raises(ImportSourceImmutableError, match="immutable"):
                session.flush()
            session.rollback()
        with factory() as session:
            stored = get_import_source(session, source_id)
            assert stored is not None
            assert stored.raw_text == "不可变原文"
            set_parse_status(session, stored, ParseStatus.FAILED)
            session.commit()
        with factory() as session:
            stored = get_import_source(session, source_id)
            assert stored is not None
            assert stored.raw_text == "不可变原文"
            assert stored.parse_status == ParseStatus.FAILED
    finally:
        engine.dispose()


def test_sqlite_trigger_blocks_raw_sql_overwrite(isolated_data_dir: Path) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            source = create_paste_source(session, "触发器保护")
            source_id = source.id
        with factory() as session:
            with pytest.raises(IntegrityError, match="immutable"):
                session.execute(
                    text("UPDATE import_sources SET raw_text = :text WHERE id = :id"),
                    {"text": "hacked", "id": source_id},
                )
                session.commit()
            session.rollback()
        with factory() as session:
            stored = get_import_source(session, source_id)
            assert stored is not None
            assert stored.raw_text == "触发器保护"
    finally:
        engine.dispose()


def test_upgrade_from_v0_1_baseline_preserves_settings(isolated_data_dir: Path) -> None:
    settings = get_settings()
    ensure_data_layout(settings)
    config = alembic_config(settings)
    command.upgrade(config, "0001_app_settings")
    engine = create_sqlite_engine(settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO app_settings (key, value, updated_at) "
                    "VALUES ('theme', 'dark', '2026-01-01T00:00:00+00:00')"
                )
            )
        assert "import_sources" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        tables = inspect(engine).get_table_names()
        assert "import_sources" in tables
        assert "import_source_normalized_texts" in tables
        with engine.connect() as connection:
            theme = connection.execute(
                text("SELECT value FROM app_settings WHERE key = 'theme'")
            ).scalar_one()
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert theme == "dark"
        assert version == "0005_chapter_analysis"
    finally:
        engine.dispose()
