import asyncio

from app.adapters.embedding import FakeEmbeddingProvider
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.models import ChapterVersion
from app.domain.embedding_profile import EmbeddingProfileSpec
from app.domain.jobs import JobState
from app.schemas.analysis import ChapterAnalysisPayload, ChapterSummary, StyleSignals
from app.services import catalog
from app.services.analysis import persist_chapter_analysis
from app.services.canon_chunks import build_novel_chunks
from app.services.embedding_profiles import activate_embedding_profile
from app.services.initialization import (
    cancel_initialization,
    execute_initialization,
    initialization_fingerprint,
    novel_is_ready,
    open_initialization,
    resume_initialization,
    retry_initialization,
    writing_gate,
)
from tests.milvus_mock import mock_milvus


def _spec() -> EmbeddingProfileSpec:
    return EmbeddingProfileSpec(
        embedding_model_id="fake-embedding",
        embedding_model_tag="test",
        embedding_model_version="1",
        dimension=8,
        normalization="l2",
        chunking_version="chunking.v1",
    )


def _analyze(session, chapter) -> None:
    version = session.get(ChapterVersion, chapter.current_canon_version_id)
    persist_chapter_analysis(
        session,
        chapter,
        version,
        payload=ChapterAnalysisPayload(
            summary=ChapterSummary(synopsis=chapter.display_title or "章节"),
            characters=[],
            locations=[],
            events=[],
            relationships=[],
            timeline=[],
            foreshadowing=[],
            open_questions=[],
            world_facts=[],
            style_signals=StyleSignals(),
        ),
        analyzer_version="test",
        model_profile_id="test",
        prompt_version="test",
        profile_version="test",
    )


def test_initialization_is_idempotent_and_gates_writing(monkeypatch) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    client, _entities, http_client = mock_milvus()
    chunk_calls = {"n": 0}
    real_chunks = build_novel_chunks

    def _count(session, novel_id, profile=None):
        chunk_calls["n"] += 1
        return real_chunks(session, novel_id, profile)

    monkeypatch.setattr("app.services.initialization.build_novel_chunks", _count)
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深住在城南。")
            _analyze(session, chapter)
            activate_embedding_profile(session, _spec())
            provider = FakeEmbeddingProvider(dimension=8)
            before = writing_gate(session, novel.id)
            assert before["ready"] is False
            assert "不能续写" in before["message"]

            async def _run(
                session=session, provider=provider, pause_before=None, novel_id=novel.id
            ):
                return await execute_initialization(
                    session,
                    client,
                    provider,
                    novel_id,
                    pause_before=pause_before,
                )

            paused = asyncio.run(_run(pause_before="embedding"))
            assert paused.state == JobState.PAUSED.value
            assert paused.current_phase == "embedding"
            assert "chunk" in paused.checkpoint["completed"]
            assert novel_is_ready(session, novel.id) is False
            resumed = asyncio.run(resume_initialization(session, client, provider, novel.id))
            assert resumed.state == JobState.COMPLETED.value
            assert resumed.current_phase == "ready"
            assert novel_is_ready(session, novel.id) is True
            assert writing_gate(session, novel.id)["ready"] is True
            again = asyncio.run(_run())
            assert again.id == resumed.id
            assert chunk_calls["n"] == 1
            fingerprint = initialization_fingerprint(session, novel.id)
            assert open_initialization(session, novel.id).input_fingerprint == fingerprint
    finally:
        engine.dispose()
        asyncio.run(http_client.aclose())


def test_failed_initialization_retries_without_rechunking(monkeypatch) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    client, _entities, http_client = mock_milvus()
    chunk_calls = {"n": 0}

    def _count(session, novel_id, profile=None):
        chunk_calls["n"] += 1
        return build_novel_chunks(session, novel_id, profile)

    monkeypatch.setattr("app.services.initialization.build_novel_chunks", _count)
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="旧伞在雨夜遗失。")
            _analyze(session, chapter)
            activate_embedding_profile(session, _spec())
            broken = FakeEmbeddingProvider(dimension=8, mode="unavailable")

            async def _fail(session=session, broken=broken, novel_id=novel.id):
                return await execute_initialization(session, client, broken, novel_id)

            failed = asyncio.run(_fail())
            assert failed.state == JobState.FAILED.value
            assert failed.error_code == "embedding_unavailable"
            assert "chunk" in failed.checkpoint["completed"]
            provider = FakeEmbeddingProvider(dimension=8)

            async def _retry(session=session, provider=provider, novel_id=novel.id):
                return await retry_initialization(session, client, provider, novel_id)

            done = asyncio.run(_retry())
            assert done.state == JobState.COMPLETED.value
            assert chunk_calls["n"] == 1
            assert novel_is_ready(session, novel.id) is True
    finally:
        engine.dispose()
        asyncio.run(http_client.aclose())


def test_cancel_resets_and_empty_novel_fails() -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "空")
            activate_embedding_profile(session, _spec())
            row = open_initialization(session, novel.id)
            cancelled = cancel_initialization(session, novel.id)
            assert cancelled.state == JobState.CANCELLED.value
            reopened = open_initialization(session, novel.id)
            assert reopened.id == row.id
            assert reopened.state == JobState.QUEUED.value
            empty = catalog.create_novel(session, "没有章节")

            async def _empty(session=session, empty=empty):
                return await execute_initialization(
                    session,
                    None,  # type: ignore[arg-type]
                    FakeEmbeddingProvider(dimension=8),
                    empty.id,
                )

            failed = asyncio.run(_empty())
            assert failed.state == JobState.FAILED.value
            assert failed.error_code == "chapters_empty"
            assert writing_gate(session, empty.id)["ready"] is False
    finally:
        engine.dispose()
