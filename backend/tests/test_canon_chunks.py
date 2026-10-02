import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.chunks import CanonChunk
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chapter_canon import add_draft_version
from app.domain.chunking import (
    ChunkingProfile,
    ChunkPiece,
    chunk_identity,
    chunk_text,
    estimate_tokens,
)
from app.schemas.analysis import (
    ChapterAnalysisPayload,
    ChapterSummary,
    CharacterMention,
    EventRecord,
    LocationMention,
    StyleSignals,
)
from app.services import catalog
from app.services.analysis import persist_chapter_analysis
from app.services.canon_chunks import ChunkError, build_chapter_chunks, list_canon_chunks
from app.services.chapter_canon import persist_accepted_canon
from app.services.chunk_report import write_chunk_regression_report
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError


def _now() -> datetime:
    return datetime.now(UTC)


def _profile(**overrides: object) -> ChunkingProfile:
    values = {
        "version": "chunking.test",
        "target_min_tokens": 8,
        "target_max_tokens": 24,
        "overlap_tokens": 4,
    }
    values.update(overrides)
    return ChunkingProfile(**values)  # type: ignore[arg-type]


def _assert_slices(body: str, pieces: list[ChunkPiece], profile: ChunkingProfile) -> None:
    assert pieces
    assert all(piece.text == body[piece.start_offset : piece.end_offset] for piece in pieces)
    assert all(piece.text.strip() for piece in pieces)
    assert all(estimate_tokens(piece.text) <= profile.target_max_tokens for piece in pieces)
    assert [piece.index for piece in pieces] == list(range(len(pieces)))


def test_defaults_cover_the_token_budget() -> None:
    profile = ChunkingProfile()
    assert profile.version == "chunking.v1"
    assert profile.target_min_tokens == 600
    assert profile.target_max_tokens == 900
    assert 80 <= profile.overlap_tokens <= 120


def test_chinese_and_english_chunks_keep_offsets_and_overlap() -> None:
    profile = _profile()
    chinese = "林深走进雨巷，看见一把旧伞。" * 12
    english = "Hello world. " * 40
    for body in (chinese, english):
        pieces = chunk_text(body, profile)
        _assert_slices(body, pieces, profile)
        assert len(pieces) > 1
        assert any(piece.overlap_tokens > 0 for piece in pieces)
        assert pieces[1].start_offset < pieces[0].end_offset
        again = chunk_text(body, profile)
        assert [(item.start_offset, item.end_offset, item.text) for item in again] == [
            (item.start_offset, item.end_offset, item.text) for item in pieces
        ]


def test_scene_boundaries_and_overlong_recursion() -> None:
    profile = _profile()
    scenes = "场景：雨巷\n林深看见旧伞。\n场景：茶馆\n阿婉放下茶杯。"
    pieces = chunk_text(scenes, profile)
    _assert_slices(scenes, pieces, profile)
    assert any("旧伞" in piece.text for piece in pieces)
    assert any("茶杯" in piece.text for piece in pieces)
    assert all("旧伞" not in piece.text or "茶杯" not in piece.text for piece in pieces)

    overlong = "场景：长巷\n" + ("林深继续往前走。" * 20)
    split = chunk_text(overlong, profile)
    _assert_slices(overlong, split, profile)
    assert len(split) > 1

    plain = "第一段很短。\n\n第二段也很短。\n\n第三段仍然很短。"
    merged = chunk_text(plain, _profile(target_min_tokens=30, target_max_tokens=80))
    assert len(merged) == 1
    assert "第一段" in merged[0].text and "第三段" in merged[0].text


def test_stable_identity_changes_with_profile_or_checksum() -> None:
    first = chunk_identity(
        novel_id="n",
        chapter_id="c",
        source_version_id="v",
        chunking_version="chunking.v1",
        index=0,
        text_checksum="abc",
    )
    assert first == chunk_identity(
        novel_id="n",
        chapter_id="c",
        source_version_id="v",
        chunking_version="chunking.v1",
        index=0,
        text_checksum="abc",
    )
    assert first != chunk_identity(
        novel_id="n",
        chapter_id="c",
        source_version_id="v",
        chunking_version="chunking.v2",
        index=0,
        text_checksum="abc",
    )


def test_draft_is_rejected_and_original_is_idempotent(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深走进雨巷。" * 8)
            version = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert version is not None
            draft = add_draft_version(
                chapter, body="草稿不能入库。", parent=version, created_at=_now()
            )
            session.flush()
            with pytest.raises(ChunkError) as rejected:
                build_chapter_chunks(session, novel.id, chapter, draft, _profile())
            assert rejected.value.code == "draft_cannot_be_canon_chunk"
            assert session.scalar(select(func.count()).select_from(CanonChunk)) == 0

            first = build_chapter_chunks(session, novel.id, chapter, version, _profile())
            second = build_chapter_chunks(session, novel.id, chapter, version, _profile())
            assert [row.id for row in second] == [row.id for row in first]
            assert session.scalar(
                select(func.count())
                .select_from(CanonChunk)
                .where(CanonChunk.chapter_id == chapter.id)
            ) == len(first)
            assert all(row.text == version.body[row.start_offset : row.end_offset] for row in first)
            assert all(row.source_version_kind == "ORIGINAL" for row in first)
    finally:
        engine.dispose()


def test_accepted_metadata_and_single_chapter_replace(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            first = catalog.create_chapter(session, novel.id, body="第一章只有旧伞。")
            second = catalog.create_chapter(session, novel.id, body="第二章看见茶馆。" * 6)
            profile = _profile()
            build_chapter_chunks(
                session,
                novel.id,
                first,
                session.get(ChapterVersion, first.current_canon_version_id),
                profile,
            )
            original = session.get(ChapterVersion, second.current_canon_version_id)
            assert original is not None
            build_chapter_chunks(session, novel.id, second, original, profile)
            before = [row.id for row in list_canon_chunks(session, novel.id, chapter_id=first.id)]
            draft = add_draft_version(
                second, body="第二章改成旧伞店。" * 6, parent=original, created_at=_now()
            )
            accepted = persist_accepted_canon(session, second, draft, created_at=_now())
            persist_chapter_analysis(
                session,
                second,
                accepted,
                payload=ChapterAnalysisPayload(
                    summary=ChapterSummary(synopsis="改稿"),
                    characters=[CharacterMention(name="林深")],
                    locations=[LocationMention(name="旧伞店")],
                    events=[EventRecord(summary="换了店面", importance="high")],
                    relationships=[],
                    timeline=[],
                    foreshadowing=[],
                    open_questions=[],
                    world_facts=[],
                    style_signals=StyleSignals(),
                ),
                analyzer_version="test",
                model_profile_id="fake",
                prompt_version="p",
                profile_version="s",
            )
            updated = build_chapter_chunks(session, novel.id, second, accepted, profile)
            assert updated
            assert updated[0].source_version_kind == "ACCEPTED"
            assert updated[0].characters == ["林深"]
            assert updated[0].locations == ["旧伞店"]
            assert updated[0].importance == "high"
            assert updated[0].event_ids
            assert [
                row.id for row in list_canon_chunks(session, novel.id, chapter_id=first.id)
            ] == before
            active_second = list_canon_chunks(session, novel.id, chapter_id=second.id)
            assert {row.source_version_id for row in active_second} == {accepted.id}
            inactive = session.scalars(
                select(CanonChunk).where(
                    CanonChunk.chapter_id == second.id,
                    CanonChunk.canon_status == "inactive",
                )
            )
            assert {row.source_version_id for row in inactive} == {original.id}
    finally:
        engine.dispose()


def test_profile_change_deactivates_the_old_active_set(isolated_data_dir, tmp_path: Path) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深走进雨巷。" * 10)
            version = session.get(ChapterVersion, chapter.current_canon_version_id)
            old = build_chapter_chunks(
                session, novel.id, chapter, version, _profile(version="chunking.v1")
            )
            new = build_chapter_chunks(
                session, novel.id, chapter, version, _profile(version="chunking.v2")
            )
            assert {row.id for row in new}.isdisjoint({row.id for row in old})
            active = list_canon_chunks(session, novel.id, chapter_id=chapter.id)
            assert {row.chunking_version for row in active} == {"chunking.v2"}
            stored_old = session.scalars(
                select(CanonChunk).where(CanonChunk.chunking_version == "chunking.v1")
            )
            assert stored_old and all(row.canon_status == "inactive" for row in stored_old)
            report = write_chunk_regression_report(session, novel.id, tmp_path)
            saved = json.loads((tmp_path / "chunk-regression.json").read_text(encoding="utf-8"))
            assert saved["active_count"] == report["active_count"] == len(new)
            assert "inactive" in (tmp_path / "chunk-regression.md").read_text(encoding="utf-8")
    finally:
        engine.dispose()


def test_failed_rebuild_keeps_the_previous_active_set(isolated_data_dir, monkeypatch) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深走进雨巷。" * 8)
            version = session.get(ChapterVersion, chapter.current_canon_version_id)
            profile = _profile()
            first = build_chapter_chunks(session, novel.id, chapter, version, profile)
            first_ids = [row.id for row in first]

            def _broken(_body: str, _profile: ChunkingProfile) -> list[ChunkPiece]:
                return [
                    ChunkPiece(
                        index=0,
                        text="",
                        start_offset=0,
                        end_offset=0,
                        overlap_tokens=0,
                        chunk_type="chapter",
                    )
                ]

            monkeypatch.setattr("app.services.canon_chunks.chunk_text", _broken)
            with pytest.raises(IntegrityError):
                build_chapter_chunks(session, novel.id, chapter, version, profile)
            session.expire_all()
            active = list_canon_chunks(session, novel.id, chapter_id=chapter.id)
            assert [row.id for row in active] == first_ids
            assert session.scalar(
                select(func.count())
                .select_from(CanonChunk)
                .where(
                    CanonChunk.chapter_id == chapter.id,
                    CanonChunk.canon_status == "active",
                )
            ) == len(first_ids)
    finally:
        engine.dispose()
