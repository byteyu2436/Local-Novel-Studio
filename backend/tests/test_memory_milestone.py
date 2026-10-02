import json
from datetime import UTC, datetime

import pytest
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.memory import (
    MemoryCharacter,
    MemoryConflict,
    MemoryFact,
    MemorySnapshot,
    MemoryWorldFact,
)
from app.adapters.sqlite.models import ChapterVersion
from app.domain.analysis import AnalysisError
from app.domain.chapter import TitleSource
from app.domain.chapter_canon import add_draft_version
from app.domain.memory import FactStatus, MemoryError, MemorySubjectKind
from app.domain.memory_conflict import ConflictResolution
from app.domain.titles import choose_display_title, set_user_title
from app.main import app
from app.schemas.analysis import (
    ChapterAnalysisPayload,
    CharacterMention,
    LocationMention,
    WorldFactItem,
)
from app.schemas.title import TitleCandidate, TitleCandidateList
from app.services import catalog
from app.services.memory_adjudication import resolve_memory_conflict
from app.services.memory_audit import list_operations
from app.services.memory_conflicts import list_open_conflicts
from app.services.memory_incremental import commit_canon_memory, rebuild_memory_after_snapshot
from app.services.memory_reduce import reduce_chapter_analysis, reduce_novel_memory
from app.services.memory_repository import MemoryRepository
from app.services.memory_snapshot import create_memory_snapshot, latest_memory_snapshot
from app.services.title_generator import generate_title_candidates
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.test_memory_reduce import _payload, _store


class _Calls:
    def __init__(self, raw: str | None = None, fail: bool = False) -> None:
        self.calls = 0
        self.raw = raw
        self.fail = fail

    async def chat(self, messages, profile, *, response_format=None) -> str:  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail:
            raise AnalysisError("llm_unavailable", "down")
        assert self.raw is not None
        assert "本章正文" in messages[-1].content
        return self.raw


def _with(identity: str, *, description: str, rule: str) -> ChapterAnalysisPayload:
    data = _payload(1).model_dump()
    data["characters"] = [CharacterMention(name="林深", identity=identity).model_dump()]
    data["locations"] = [LocationMention(name="雨巷", description=description).model_dump()]
    data["world_facts"] = [WorldFactItem(fact=rule, category="rule").model_dump()]
    return ChapterAnalysisPayload.model_validate(data)


def test_explicit_conflicts_keep_both_sources_and_stay_unique(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapters = [
                catalog.create_chapter(session, novel.id, body=f"第{index}章。")
                for index in range(1, 4)
            ]
            _store(
                session, chapters[0], _with("18岁", description="林深的家", rule="天规：不许夜出")
            )
            changed = _with("30岁", description="已经荒废", rule="天规：允许夜出")
            _store(session, chapters[1], changed)
            _store(session, chapters[2], changed)
            reduce_novel_memory(session, novel.id)
            reduce_novel_memory(session, novel.id)
            repo = MemoryRepository(session)
            identity = repo.query_facts(
                novel.id,
                subject_kind=MemorySubjectKind.CHARACTER,
                fact_key="identity",
                status=FactStatus.ACTIVE,
            )
            assert identity[0].fact_value == {"value": "18岁"}
            place = session.scalar(select(MemoryWorldFact).where(MemoryWorldFact.topic == "雨巷"))
            assert place is not None
            description = repo.query_facts(
                novel.id,
                subject_kind=MemorySubjectKind.WORLD_FACT,
                subject_id=place.id,
                fact_key="description",
                status=FactStatus.ACTIVE,
            )
            assert description[0].fact_value == {"value": "林深的家"}
            rule = session.scalar(select(MemoryWorldFact).where(MemoryWorldFact.topic == "天规"))
            assert rule is not None
            statement = repo.query_facts(
                novel.id,
                subject_kind=MemorySubjectKind.WORLD_FACT,
                subject_id=rule.id,
                fact_key="statement",
                status=FactStatus.ACTIVE,
            )
            assert statement[0].fact_value == {"value": "不许夜出"}
            conflicts = list_open_conflicts(session, novel.id)
            assert sorted(item.category for item in conflicts) == ["age", "location", "world_rule"]
            age = next(item for item in conflicts if item.category == "age")
            assert age.existing_source_chapter_id == chapters[0].id
            assert age.incoming_source_chapter_id == chapters[1].id
            assert age.existing_revision == identity[0].revision
            assert age.existing_source_chapter_version_id
            assert age.incoming_source_chapter_version_id
    finally:
        engine.dispose()


def test_personality_change_stays_a_candidate(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            first = catalog.create_chapter(session, novel.id, body="第一章。")
            second = catalog.create_chapter(session, novel.id, body="第二章。")
            opening = _payload(1).model_dump()
            opening["characters"] = [CharacterMention(name="林深", personality="沉静").model_dump()]
            later = _payload(2).model_dump()
            later["characters"] = [CharacterMention(name="林深", personality="开朗").model_dump()]
            _store(session, first, ChapterAnalysisPayload.model_validate(opening))
            _store(session, second, ChapterAnalysisPayload.model_validate(later))
            report = reduce_novel_memory(session, novel.id)
            assert list_open_conflicts(session, novel.id) == []
            assert any(item.reason == "supersede_candidate" for item in report.conflicts)
    finally:
        engine.dispose()


def test_locked_fact_survives_reduce_until_unlock(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            first = catalog.create_chapter(session, novel.id, body="第一章。")
            second = catalog.create_chapter(session, novel.id, body="第二章。")
            _store(session, first, _with("18岁", description="林深的家", rule="天规：不许夜出"))
            reduce_chapter_analysis(
                session,
                novel_id=novel.id,
                chapter=first,
                source_version=session.get(ChapterVersion, first.current_canon_version_id),
                payload=_with("18岁", description="林深的家", rule="天规：不许夜出"),
            )
            repo = MemoryRepository(session)
            fact = repo.query_facts(novel.id, fact_key="identity", status=FactStatus.ACTIVE)[0]
            repo.lock_fact(fact.id, novel.id)
            version = session.get(ChapterVersion, second.current_canon_version_id)
            assert version is not None
            reduce_chapter_analysis(
                session,
                novel_id=novel.id,
                chapter=second,
                source_version=version,
                payload=_with("30岁", description="林深的家", rule="天规：不许夜出"),
            )
            assert fact.fact_value == {"value": "18岁"}
            assert fact.locked is True
            with pytest.raises(MemoryError) as locked:
                repo.supersede_fact(
                    fact_id=fact.id,
                    novel_id=novel.id,
                    fact_value={"value": "30岁"},
                    source_chapter=second,
                    source_version=version,
                    origin="inferred",
                    confidence=0.7,
                )
            assert locked.value.code == "fact_locked"
            repo.unlock_fact(fact.id, novel.id)
            created = repo.supersede_fact(
                fact_id=fact.id,
                novel_id=novel.id,
                fact_value={"value": "30岁"},
                source_chapter=second,
                source_version=version,
                origin="inferred",
                confidence=0.7,
            )
            history = repo.query_facts(novel.id, fact_key="identity")
            assert [item.fact_value["value"] for item in history] == ["18岁", "30岁"]
            assert created.source_chapter_id == second.id
            assert any(item.action == "lock_fact" for item in list_operations(session, novel.id))
            assert any(
                item.action == "supersede_fact" for item in list_operations(session, novel.id)
            )
    finally:
        engine.dispose()


def test_supersede_rejects_cycles_and_cross_novel_links(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            other = catalog.create_novel(session, "别册")
            chapter = catalog.create_chapter(session, novel.id, body="第一章。")
            other_chapter = catalog.create_chapter(session, other.id, body="另一章。")
            version = session.get(ChapterVersion, chapter.current_canon_version_id)
            other_version = session.get(ChapterVersion, other_chapter.current_canon_version_id)
            assert version is not None and other_version is not None
            repo = MemoryRepository(session)
            character = repo.create_character(novel.id, "林深")
            other_character = repo.create_character(other.id, "别人")
            first = repo.revise_fact(
                novel_id=novel.id,
                subject_kind=MemorySubjectKind.CHARACTER,
                subject_id=character.id,
                fact_key="identity",
                fact_value={"value": "18岁"},
                source_chapter=chapter,
                source_version=version,
                origin="inferred",
                confidence=0.7,
            )
            second = repo.revise_fact(
                novel_id=novel.id,
                subject_kind=MemorySubjectKind.CHARACTER,
                subject_id=character.id,
                fact_key="goal",
                fact_value={"value": "找伞"},
                source_chapter=chapter,
                source_version=version,
                origin="inferred",
                confidence=0.7,
            )
            second.superseded_by_id = first.id
            session.flush()
            with pytest.raises(MemoryError) as cycle:
                repo.guard_supersede_link(first, second)
            assert cycle.value.code == "supersede_cycle"
            foreign = repo.revise_fact(
                novel_id=other.id,
                subject_kind=MemorySubjectKind.CHARACTER,
                subject_id=other_character.id,
                fact_key="identity",
                fact_value={"value": "20岁"},
                source_chapter=other_chapter,
                source_version=other_version,
                origin="inferred",
                confidence=0.7,
            )
            with pytest.raises(MemoryError) as crossed:
                repo.guard_supersede_link(first, foreign)
            assert crossed.value.code == "cross_novel_supersede"
    finally:
        engine.dispose()


def test_locked_resolution_rolls_back_the_conflict(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            first = catalog.create_chapter(session, novel.id, body="第一章。")
            second = catalog.create_chapter(session, novel.id, body="第二章。")
            _store(session, first, _with("18岁", description="林深的家", rule="天规：不许夜出"))
            _store(session, second, _with("30岁", description="林深的家", rule="天规：不许夜出"))
            reduce_novel_memory(session, novel.id)
            conflict = list_open_conflicts(session, novel.id)[0]
            repo = MemoryRepository(session)
            repo.lock_fact(conflict.existing_fact_id, novel.id)
            with pytest.raises(MemoryError):
                resolve_memory_conflict(
                    session,
                    novel_id=novel.id,
                    conflict_id=conflict.id,
                    action=ConflictResolution.ACCEPT_INCOMING,
                )
            session.expire_all()
            reloaded = session.get(MemoryConflict, conflict.id)
            fact = session.get(MemoryFact, conflict.existing_fact_id)
            assert reloaded is not None and reloaded.status == "open"
            assert fact is not None and fact.fact_value == {"value": "18岁"}
            resolve_memory_conflict(
                session,
                novel_id=novel.id,
                conflict_id=conflict.id,
                action=ConflictResolution.KEEP_EXISTING,
            )
            assert session.get(MemoryConflict, conflict.id).status == "resolved"
            assert any(
                item.action.startswith("resolve_conflict")
                for item in list_operations(session, novel.id)
            )
    finally:
        engine.dispose()


def test_snapshot_anchors_revision_without_duplicates(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="第一章。")
            body = session.get(ChapterVersion, chapter.current_canon_version_id).body
            first = create_memory_snapshot(session, novel.id, chapter.id)
            second = create_memory_snapshot(session, novel.id, chapter.id)
            assert first.id == second.id
            assert latest_memory_snapshot(session, novel.id).id == first.id
            assert session.get(ChapterVersion, chapter.current_canon_version_id).body == body
            count = session.scalar(
                select(func.count())
                .select_from(MemorySnapshot)
                .where(MemorySnapshot.novel_id == novel.id)
            )
            assert count == 1
    finally:
        engine.dispose()


def test_incremental_updates_only_the_new_chapter(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapters = [
                catalog.create_chapter(session, novel.id, body=f"第{index}章。")
                for index in range(1, 20)
            ]
            for index, chapter in enumerate(chapters[:18], start=1):
                _store(session, chapter, _payload(index))
            reduce_novel_memory(session, novel.id)
            latest = chapters[18]
            _store(session, latest, _payload(19))
            provider = _Calls(fail=True)
            snapshot_id = awaitable(
                commit_canon_memory(
                    session,
                    novel.id,
                    latest.id,
                    latest.current_canon_version_id,
                    provider,
                )
            )
            assert provider.calls == 0
            snapshot = session.get(MemorySnapshot, snapshot_id)
            assert snapshot is not None
            assert snapshot.accepted_chapter_id == latest.id
            draft_parent = session.get(ChapterVersion, chapters[0].current_canon_version_id)
            draft = add_draft_version(
                chapters[0], body="草稿。", parent=draft_parent, created_at=datetime.now(UTC)
            )
            session.flush()
            with pytest.raises(MemoryError) as draft_error:
                awaitable(
                    commit_canon_memory(session, novel.id, chapters[0].id, draft.id, provider)
                )
            assert draft_error.value.code == "draft_cannot_be_memory_source"
            untouched = catalog.create_chapter(session, novel.id, body="尚未分析。")
            before = session.get(ChapterVersion, untouched.current_canon_version_id).body
            with pytest.raises(AnalysisError):
                awaitable(
                    commit_canon_memory(
                        session,
                        novel.id,
                        untouched.id,
                        untouched.current_canon_version_id,
                        _Calls(fail=True),
                    )
                )
            assert session.get(ChapterVersion, untouched.current_canon_version_id).body == before
    finally:
        engine.dispose()


def test_rebuild_keeps_the_original_snapshot(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            other = catalog.create_novel(session, "别册")
            chapters = [
                catalog.create_chapter(session, novel.id, body=f"第{index}章。")
                for index in range(1, 4)
            ]
            for index, chapter in enumerate(chapters, start=1):
                _store(session, chapter, _payload(index))
            reduce_novel_memory(session, novel.id)
            anchor = create_memory_snapshot(session, novel.id, chapters[0].id)
            other_chapter = catalog.create_chapter(session, other.id, body="别处。")
            foreign = create_memory_snapshot(session, other.id, other_chapter.id)
            with pytest.raises(MemoryError) as mismatch:
                awaitable(
                    rebuild_memory_after_snapshot(session, novel.id, foreign.id, _Calls(fail=True))
                )
            assert mismatch.value.code == "snapshot_novel_mismatch"
            with pytest.raises(MemoryError):
                awaitable(
                    rebuild_memory_after_snapshot(session, novel.id, "missing", _Calls(fail=True))
                )
            rebuilt = awaitable(
                rebuild_memory_after_snapshot(session, novel.id, anchor.id, _Calls(fail=True))
            )
            assert session.get(MemorySnapshot, anchor.id) is not None
            assert rebuilt != anchor.id
            assert session.get(MemorySnapshot, rebuilt).memory_revision > anchor.memory_revision
    finally:
        engine.dispose()


def test_title_priority_and_generator(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            titled = catalog.create_chapter(
                session, novel.id, body="有标题。", original_title="雨夜"
            )
            blank = catalog.create_chapter(session, novel.id, body="林深撑着旧伞。")
            version = session.get(ChapterVersion, blank.current_canon_version_id)
            payload = _payload(1)
            skipped = awaitable(
                generate_title_candidates(
                    session,
                    _Calls(raw="{}"),
                    titled,
                    session.get(ChapterVersion, titled.current_canon_version_id),
                    payload,
                )
            )
            assert skipped == []
            raw = TitleCandidateList(
                candidates=[
                    TitleCandidate(
                        text="旧伞", confidence=0.8, reason="本章出现旧伞", keywords=["旧伞"]
                    )
                ]
            ).model_dump_json()
            provider = _Calls(raw=raw)
            created = awaitable(
                generate_title_candidates(session, provider, blank, version, payload)
            )
            assert provider.calls == 1
            assert created[0].text == "旧伞"
            assert blank.title_source == TitleSource.GENERATED.value
            assert blank.display_title == "旧伞"
            set_user_title(blank, "我的标题")
            failed = _Calls(fail=True)
            assert (
                awaitable(generate_title_candidates(session, failed, blank, version, payload)) == []
            )
            assert blank.display_title == "我的标题"
            assert blank.title_source == TitleSource.USER.value
            novel.auto_title_enabled = False
            fallback, source, _confidence = choose_display_title(blank, created, auto_title=False)
            assert source is TitleSource.USER
            untitled = catalog.create_chapter(session, novel.id, body="没有标题。")
            text, kind, _confidence = choose_display_title(untitled, created, auto_title=False)
            assert kind is TitleSource.FALLBACK
            assert text.startswith("第")
            assert titled.original_title == "雨夜"
            assert session.get(ChapterVersion, titled.current_canon_version_id).body == "有标题。"
    finally:
        engine.dispose()


def test_memory_api_isolation_resolution_and_merge(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            other = catalog.create_novel(session, "别册")
            first = catalog.create_chapter(session, novel.id, body="第一章。")
            second = catalog.create_chapter(session, novel.id, body="第二章。")
            _store(session, first, _with("18岁", description="林深的家", rule="天规：不许夜出"))
            _store(session, second, _with("30岁", description="林深的家", rule="天规：不许夜出"))
            reduce_novel_memory(session, novel.id)
            source = MemoryRepository(session).create_character(novel.id, "阿深")
            target = session.scalar(
                select(MemoryCharacter).where(
                    MemoryCharacter.novel_id == novel.id, MemoryCharacter.name == "林深"
                )
            )
            novel_id = novel.id
            other_id = other.id
            source_id = source.id
            target_id = target.id
        with TestClient(app) as client:
            own = client.get(f"/api/novels/{novel_id}/memory?kind=character")
            assert own.status_code == 200
            assert any(item["fact_key"] == "identity" for item in own.json()["facts"])
            foreign = client.get(f"/api/novels/{other_id}/memory?kind=character")
            assert foreign.status_code == 200
            assert foreign.json()["facts"] == []
            conflicts = client.get(f"/api/novels/{novel_id}/memory/conflicts")
            conflict_id = conflicts.json()["conflicts"][0]["id"]
            fact_id = conflicts.json()["conflicts"][0]["existing_fact_id"]
            detail = client.get(f"/api/novels/{novel_id}/memory/facts/{fact_id}")
            assert detail.status_code == 200
            assert detail.json()["provenance"]["chapter_id"]
            kept = client.post(
                f"/api/novels/{novel_id}/memory/conflicts/{conflict_id}/resolve",
                json={"action": "dismiss"},
            )
            assert kept.status_code == 200
            assert kept.json()["status"] == "dismissed"
            merged = client.post(
                f"/api/novels/{novel_id}/memory/aliases/merge",
                json={"source_id": source_id, "target_id": target_id},
            )
            assert merged.status_code == 200
            assert "阿深" in merged.json()["aliases"]
            missing = client.get(f"/api/novels/{other_id}/memory/facts/{fact_id}")
            assert missing.status_code == 404
        for session in session_scope(factory):
            assert session.get(MemoryCharacter, source_id) is None
            survivor = session.get(MemoryCharacter, target_id)
            assert survivor is not None
            assert "阿深" in survivor.aliases
            dangling = session.scalar(
                select(func.count())
                .select_from(MemoryFact)
                .where(MemoryFact.subject_id == source_id)
            )
            assert dangling == 0
    finally:
        engine.dispose()


def awaitable(value):  # type: ignore[no-untyped-def]
    import asyncio

    return asyncio.run(value)


def test_title_schema_limits_candidates() -> None:
    parsed = TitleCandidateList.model_validate(
        json.loads(
            '{"candidates":[{"text":"旧伞","confidence":0.4,"reason":"本章","keywords":["伞"]}]}'
        )
    )
    assert parsed.candidates[0].text == "旧伞"
    with pytest.raises(ValueError):
        TitleCandidateList.model_validate({"candidates": []})
