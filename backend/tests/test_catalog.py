from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.import_sources import create_paste_source
from app.adapters.sqlite.models import Chapter, ChapterVersion, ImportSource, Novel
from app.domain.catalog import CatalogError
from app.domain.chapter import (
    TitleSource,
    VersionKind,
    fallback_chapter_title,
    resolve_chapter_title,
)
from app.domain.chapter_canon import add_draft_version
from app.services import catalog
from app.services.chapter_canon import persist_accepted_canon
from sqlalchemy import func, select


def _now() -> datetime:
    return datetime.now(UTC)


def test_fallback_title_uses_sequence_when_source_has_no_name() -> None:
    assert fallback_chapter_title(3) == "第3章"
    title, source = resolve_chapter_title(
        sequence=1, original_label="第一章", original_title="开场"
    )
    assert title == "第一章 开场"
    assert source is TitleSource.ORIGINAL
    user_title, user_source = resolve_chapter_title(
        sequence=1,
        original_title="开场",
        display_title="雨夜",
        title_source=TitleSource.USER,
    )
    assert user_title == "雨夜"
    assert user_source is TitleSource.USER


def test_novel_chapter_crud_and_provenance(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            source = create_paste_source(session, "第一章\n林深见鹿。")
            novel = catalog.create_novel(session, " 雨巷 ")
            first = catalog.create_chapter(
                session,
                novel.id,
                body="林深见鹿。",
                original_label="第一章",
                original_title="开场",
                import_source_id=source.id,
                start_offset=0,
                end_offset=8,
                source_checksum=source.checksum,
            )
            second = catalog.create_chapter(session, novel.id, body="夜雨不停。")
            assert novel.title == "雨巷"
            assert first.sequence == 1
            assert second.sequence == 2
            assert first.display_title == "第一章 开场"
            assert second.display_title == "第2章"
            assert second.title_source == TitleSource.FALLBACK.value
            listed = catalog.list_chapters(session, novel.id)
            assert [item.id for item in listed] == [first.id, second.id]
            provenance = catalog.chapter_provenance(session, first.id)
            assert provenance.import_source_id == source.id
            assert provenance.start_offset == 0
            assert provenance.end_offset == 8
            assert provenance.source_checksum == source.checksum
            original = session.get(ChapterVersion, provenance.original_version_id)
            assert original is not None
            assert original.version_kind == VersionKind.ORIGINAL.value
            catalog.update_chapter(
                session, first.id, display_title="用户标题", title_source=TitleSource.USER
            )
            assert session.get(Chapter, first.id).display_title == "用户标题"
            assert original.body == "林深见鹿。"
    finally:
        engine.dispose()


def test_reorder_keeps_versions_and_provenance(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            source = create_paste_source(session, "原文")
            novel = catalog.create_novel(session, "目录")
            first = catalog.create_chapter(
                session,
                novel.id,
                body="甲",
                import_source_id=source.id,
                start_offset=0,
                end_offset=1,
                source_checksum=source.checksum,
            )
            second = catalog.create_chapter(
                session,
                novel.id,
                body="乙",
                import_source_id=source.id,
                start_offset=1,
                end_offset=2,
                source_checksum=source.checksum,
            )
            third = catalog.create_chapter(session, novel.id, body="丙")
            reordered = catalog.reorder_chapters(
                session, novel.id, [third.id, first.id, second.id]
            )
            assert [item.sequence for item in reordered] == [1, 2, 3]
            assert [item.id for item in reordered] == [third.id, first.id, second.id]
            first_again = session.get(Chapter, first.id)
            assert first_again is not None
            assert first_again.current_canon_version_id is not None
            assert catalog.chapter_provenance(session, first.id).import_source_id == source.id
            assert session.get(ChapterVersion, first_again.current_canon_version_id).body == "甲"
            with pytest.raises(CatalogError) as mismatch:
                catalog.reorder_chapters(session, novel.id, [first.id, second.id])
            assert mismatch.value.code == "chapter_reorder_mismatch"
    finally:
        engine.dispose()


def test_copy_and_delete_leave_import_source_intact(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        source_id = None
        original_novel_id = None
        copied_id = None
        for session in session_scope(factory):
            source = create_paste_source(session, "不可变原文")
            source_id = source.id
            novel = catalog.create_novel(session, "原作")
            original_novel_id = novel.id
            chapter = catalog.create_chapter(
                session,
                novel.id,
                body="林深走进雨里。",
                import_source_id=source.id,
                start_offset=0,
                end_offset=8,
                source_checksum=source.checksum,
            )
            session.flush()
            original = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert original is not None
            draft = add_draft_version(chapter, body="草稿", parent=original, created_at=_now())
            session.flush()
            persist_accepted_canon(session, chapter, draft, created_at=_now())
            copied = catalog.copy_novel(session, novel.id)
            copied_id = copied.id
            assert copied.id != novel.id
            copies = catalog.list_chapters(session, copied.id)
            assert len(copies) == 1
            replica = copies[0]
            assert replica.id != chapter.id
            assert replica.import_source_id == source.id
            replica_original = catalog.chapter_provenance(session, replica.id)
            assert replica_original.import_source_id == source.id
            kinds = {item.version_kind for item in replica.versions}
            assert VersionKind.ORIGINAL.value in kinds
            assert VersionKind.DRAFT.value in kinds
            assert VersionKind.ACCEPTED.value in kinds
            assert replica.current_canon_version_id is not None
            canon = session.get(ChapterVersion, replica.current_canon_version_id)
            assert canon is not None
            assert canon.version_kind == VersionKind.ACCEPTED.value
            catalog.delete_chapter(session, chapter.id)
            assert session.get(ImportSource, source.id) is not None
            assert session.get(Chapter, chapter.id) is None
        for session in session_scope(factory):
            catalog.delete_novel(session, original_novel_id)
            catalog.delete_novel(session, copied_id)
            leftover = session.get(ImportSource, source_id)
            assert leftover is not None
            assert leftover.raw_text == "不可变原文"
            remaining_chapters = session.scalar(select(func.count()).select_from(Chapter))
            remaining_novels = session.scalar(select(func.count()).select_from(Novel))
            assert remaining_chapters == 0
            assert remaining_novels == 0
    finally:
        engine.dispose()


def test_copy_does_not_point_canon_at_draft(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "约束")
            chapter = catalog.create_chapter(session, novel.id, body="原文")
            original = session.get(ChapterVersion, chapter.current_canon_version_id)
            add_draft_version(chapter, body="未接受草稿", parent=original, created_at=_now())
            session.flush()
            copied = catalog.copy_novel(session, novel.id)
            replica = catalog.list_chapters(session, copied.id)[0]
            canon = session.get(ChapterVersion, replica.current_canon_version_id)
            assert canon is not None
            assert canon.version_kind != VersionKind.DRAFT.value
            assert canon.body == "原文"
    finally:
        engine.dispose()


def test_catalog_errors_for_missing_and_conflicts(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            with pytest.raises(CatalogError) as empty:
                catalog.create_novel(session, "  ")
            assert empty.value.code == "novel_title_empty"
            novel = catalog.create_novel(session, "冲突")
            catalog.create_chapter(session, novel.id, body="一", sequence=1)
            with pytest.raises(CatalogError) as conflict:
                catalog.create_chapter(session, novel.id, body="二", sequence=1)
            assert conflict.value.code == "chapter_sequence_conflict"
            with pytest.raises(CatalogError) as missing_novel:
                catalog.get_novel(session, str(uuid4()))
            assert missing_novel.value.code == "novel_not_found"
            with pytest.raises(CatalogError) as missing_source:
                catalog.create_chapter(
                    session, novel.id, body="三", import_source_id=str(uuid4())
                )
            assert missing_source.value.code == "import_source_not_found"
    finally:
        engine.dispose()
