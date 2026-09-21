from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.models import Chapter, ChapterVersion, Novel
from app.domain.chapter import TitleSource, VersionKind
from app.domain.chapter_canon import (
    ChapterCanonError,
    add_draft_version,
    make_accepted_from_draft,
    set_canon_pointer,
)
from app.services.chapter_canon import persist_accepted_canon


def _now() -> datetime:
    return datetime.now(UTC)


def _seed(session) -> tuple[Chapter, ChapterVersion]:
    novel = Novel(id=str(uuid4()), title="雨巷", created_at=_now(), updated_at=_now())
    chapter = Chapter(
        id=str(uuid4()),
        novel_id=novel.id,
        sequence=1,
        display_title="第1章",
        title_source=TitleSource.FALLBACK.value,
        created_at=_now(),
        updated_at=_now(),
    )
    original = ChapterVersion(
        id=str(uuid4()),
        chapter_id=chapter.id,
        version_kind=VersionKind.ORIGINAL.value,
        body="林深走进雨里。",
        created_at=_now(),
    )
    session.add_all([novel, chapter, original])
    session.flush()
    set_canon_pointer(chapter, original)
    session.flush()
    return chapter, original


def test_multiple_drafts_do_not_move_canon(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            chapter, original = _seed(session)
            first = add_draft_version(chapter, body="草稿甲", parent=original, created_at=_now())
            second = add_draft_version(chapter, body="草稿乙", parent=first, created_at=_now())
            session.flush()
            assert chapter.current_canon_version_id == original.id
            kinds = {item.version_kind for item in chapter.versions}
            assert kinds == {VersionKind.ORIGINAL.value, VersionKind.DRAFT.value}
            assert {first.id, second.id}.issubset({item.id for item in chapter.versions})
            assert session.get(ChapterVersion, original.id).body == "林深走进雨里。"
    finally:
        engine.dispose()


def test_accept_supersedes_previous_accepted_and_keeps_original(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            chapter, original = _seed(session)
            draft = add_draft_version(chapter, body="第一稿", parent=original, created_at=_now())
            first_accepted = persist_accepted_canon(
                session, chapter, draft, created_at=_now()
            )
            later_draft = add_draft_version(
                chapter, body="第二稿", parent=first_accepted, created_at=_now()
            )
            session.flush()
            second_accepted = persist_accepted_canon(
                session, chapter, later_draft, created_at=_now()
            )
            assert chapter.current_canon_version_id == second_accepted.id
            assert first_accepted.superseded_by_id == second_accepted.id
            assert session.get(ChapterVersion, original.id).body == "林深走进雨里。"
            assert original.superseded_by_id is None
    finally:
        engine.dispose()


def test_illegal_transitions_are_rejected(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            chapter, original = _seed(session)
            draft = add_draft_version(chapter, body="草稿", parent=original, created_at=_now())
            session.flush()
            with pytest.raises(ChapterCanonError) as draft_canon:
                set_canon_pointer(chapter, draft)
            assert draft_canon.value.code == "draft_cannot_be_canon"
            with pytest.raises(ChapterCanonError) as not_draft:
                make_accepted_from_draft(chapter, original, created_at=_now())
            assert not_draft.value.code == "accept_requires_draft"
            other = Chapter(
                id=str(uuid4()),
                novel_id=chapter.novel_id,
                sequence=2,
                display_title="第2章",
                title_source=TitleSource.FALLBACK.value,
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(other)
            session.flush()
            with pytest.raises(ChapterCanonError) as mismatch:
                set_canon_pointer(other, original)
            assert mismatch.value.code == "version_chapter_mismatch"
            assert chapter.current_canon_version_id == original.id
    finally:
        engine.dispose()
