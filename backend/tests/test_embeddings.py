import asyncio
import json

import httpx
import pytest
from app.adapters.embedding import (
    EmbeddingDimensionError,
    EmbeddingModelNotFoundError,
    EmbeddingProfileMismatchError,
    EmbeddingTimeoutError,
    FakeEmbeddingProvider,
    OllamaEmbeddingAdapter,
)
from app.adapters.ollama.client import OllamaClient
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.embeddings import ChunkEmbedding
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chunking import ChunkingProfile
from app.domain.embedding_profile import (
    EmbeddingProfileSpec,
    index_version_for,
    profile_fingerprint,
)
from app.services import catalog
from app.services.canon_chunks import build_chapter_chunks
from app.services.embedding_batches import (
    EmbeddingExecutionStrategy,
    embed_canon_chunks,
    embed_query_text,
)
from app.services.embedding_profiles import (
    activate_embedding_profile,
    get_active_embedding_profile,
)
from app.settings import Settings, get_settings
from sqlalchemy import func, select


def _spec(**overrides: object) -> EmbeddingProfileSpec:
    values: dict[str, object] = {
        "embedding_model_id": "qwen3-embedding",
        "embedding_model_tag": "0.6b",
        "embedding_model_version": "0.6b",
        "dimension": 8,
        "normalization": "l2",
        "chunking_version": "chunking.test",
    }
    values.update(overrides)
    return EmbeddingProfileSpec(**values)  # type: ignore[arg-type]


def test_default_embedding_model_is_local_qwen() -> None:
    assert Settings.model_fields["embedding_model"].default == "qwen3-embedding:0.6b"


def test_provider_contract_is_stable_and_mockable() -> None:
    async def _run() -> None:
        provider = FakeEmbeddingProvider()
        documents = await provider.embed_documents(["雨巷", "旧伞"])
        query = await provider.embed_query("雨巷")
        info = await provider.model_info()
        assert info.dimension == 8
        assert len(documents) == 2
        assert documents[0] == query
        assert len({len(vector) for vector in documents}) == 1
        assert await provider.embed_query("雨巷") == query

        with pytest.raises(EmbeddingTimeoutError):
            await FakeEmbeddingProvider(mode="timeout").embed_query("雨巷")
        with pytest.raises(EmbeddingModelNotFoundError):
            await FakeEmbeddingProvider(mode="model_not_found").embed_documents(["雨巷"])
        with pytest.raises(EmbeddingDimensionError):
            await FakeEmbeddingProvider(mode="dimension").model_info()

    asyncio.run(_run())


def test_profile_fingerprint_changes_with_semantic_space() -> None:
    base = _spec()
    first = profile_fingerprint(base)
    assert first == profile_fingerprint(_spec())
    assert first != profile_fingerprint(_spec(embedding_model_tag="4b"))
    assert first != profile_fingerprint(_spec(dimension=16))
    assert first != profile_fingerprint(_spec(normalization="none"))
    assert first != profile_fingerprint(_spec(chunking_version="chunking.v2"))
    assert index_version_for(first) != index_version_for(profile_fingerprint(_spec(dimension=16)))


def test_ollama_adapter_uses_local_embed_and_maps_errors() -> None:
    settings = get_settings()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/api/embed":
            return httpx.Response(404, json={"error": "not found"})
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "qwen3-embedding:0.6b"
        assert not str(request.url).startswith("https://")
        if body["input"] == ["missing"]:
            return httpx.Response(404, json={"error": "model not found"})
        if body["input"] == ["short"]:
            return httpx.Response(200, json={"embeddings": [[0.1]]})
        return httpx.Response(200, json={"embeddings": [[3.0, 0.0], [0.0, 4.0]]})

    client = OllamaClient(
        settings.ollama_base_url,
        timeout=5,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=settings.ollama_base_url,
        ),
    )
    adapter = OllamaEmbeddingAdapter(
        settings,
        client=client,
        model_ref="qwen3-embedding:0.6b",
        expected_dimension=2,
        normalization="l2",
    )

    async def _run() -> None:
        vectors = await adapter.embed_documents(["雨巷", "旧伞"])
        assert len(vectors) == 2
        assert len(vectors[0]) == 2
        assert abs(sum(value * value for value in vectors[0]) - 1) < 1e-6
        with pytest.raises(EmbeddingModelNotFoundError):
            await adapter.embed_query("missing")
        with pytest.raises(EmbeddingDimensionError):
            await adapter.embed_query("short")

    asyncio.run(_run())


def test_ollama_adapter_timeout() -> None:
    settings = get_settings()
    request = httpx.Request("POST", f"{settings.ollama_base_url}/api/embed")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = OllamaClient(
        settings.ollama_base_url,
        timeout=5,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=settings.ollama_base_url,
        ),
    )
    adapter = OllamaEmbeddingAdapter(settings, client=client, expected_dimension=2)

    async def _run() -> None:
        with pytest.raises(EmbeddingTimeoutError) as info:
            await adapter.embed_query("雨巷")
        assert info.value.retryable is True

    asyncio.run(_run())


def test_profile_switch_blocks_mixed_writes_and_marks_rebuild(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深看见旧伞。")
            version = session.get(ChapterVersion, chapter.current_canon_version_id)
            profile = ChunkingProfile(
                version="chunking.test",
                target_min_tokens=4,
                target_max_tokens=40,
                overlap_tokens=2,
            )
            build_chapter_chunks(session, novel.id, chapter, version, profile)
            first = activate_embedding_profile(session, _spec())
            assert first.rebuild_required is True
            provider = FakeEmbeddingProvider(dimension=8)
            ready = asyncio.run(embed_canon_chunks(session, novel.id, provider))
            assert ready.embedded >= 1 and ready.failed == 0
            old_ready = session.scalar(
                select(func.count())
                .select_from(ChunkEmbedding)
                .where(
                    ChunkEmbedding.profile_id == first.id,
                    ChunkEmbedding.status == "ready",
                )
            )
            second = activate_embedding_profile(session, _spec(dimension=16))
            assert second.id != first.id
            assert second.is_active is True
            assert second.rebuild_required is True
            assert second.index_version != first.index_version
            assert get_active_embedding_profile(session).id == second.id
            with pytest.raises(EmbeddingProfileMismatchError):
                asyncio.run(embed_canon_chunks(session, novel.id, provider, profile_id=first.id))
            with pytest.raises(EmbeddingProfileMismatchError):
                asyncio.run(embed_query_text(session, provider, "旧伞", profile_id=first.id))
            still = session.scalar(
                select(func.count())
                .select_from(ChunkEmbedding)
                .where(
                    ChunkEmbedding.profile_id == first.id,
                    ChunkEmbedding.status == "ready",
                )
            )
            assert still == old_ready
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ChunkEmbedding)
                    .where(ChunkEmbedding.profile_id == second.id)
                )
                == 0
            )
    finally:
        engine.dispose()


def test_failed_batch_retries_without_reembedding_ready_chunks(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chunking = ChunkingProfile(
                version="chunking.test",
                target_min_tokens=4,
                target_max_tokens=80,
                overlap_tokens=2,
            )
            for index in range(1, 19):
                chapter = catalog.create_chapter(
                    session, novel.id, body=f"第{index}章 林深把旧伞放在雨巷。"
                )
                version = session.get(ChapterVersion, chapter.current_canon_version_id)
                build_chapter_chunks(session, novel.id, chapter, version, chunking)
            activate_embedding_profile(session, _spec())
            provider = FakeEmbeddingProvider(dimension=8, fail_on_calls={2})
            strategy = EmbeddingExecutionStrategy(batch_size=4)
            first = asyncio.run(embed_canon_chunks(session, novel.id, provider, strategy=strategy))
            assert first.failed == 4
            assert first.embedded == 14
            assert "text" not in first.__dataclass_fields__
            failed_ids = set(first.failed_chunk_ids)
            retry = asyncio.run(embed_canon_chunks(session, novel.id, provider, strategy=strategy))
            assert retry.skipped_ready == 14
            assert retry.embedded == 4
            assert retry.failed == 0
            retried_texts = [text for call in provider.calls[5:] for text in call]
            first_ready_texts = [text for call in provider.calls[:1] for text in call]
            assert set(retried_texts).isdisjoint(first_ready_texts)
            ready = session.scalar(
                select(func.count())
                .select_from(ChunkEmbedding)
                .where(ChunkEmbedding.status == "ready")
            )
            assert ready == 18
            assert failed_ids
            query = asyncio.run(embed_query_text(session, provider, "旧伞"))
            assert len(query) == 8
    finally:
        engine.dispose()


def _is_windows_gpu() -> bool:
    get_settings.cache_clear()
    return get_settings().lns_execution_profile.value == "windows-gpu"


@pytest.mark.skipif(
    not _is_windows_gpu(),
    reason="Real qwen3-embedding:0.6b smoke is deferred to WINDOWS_GPU.",
)
def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def test_real_qwen_embedding_smoke() -> None:
    """Resident GPU vectors are stable. The load-time vector can differ slightly."""

    settings = get_settings()
    adapter = OllamaEmbeddingAdapter(settings, normalization="l2")
    text = "林深走进雨巷"

    async def _run() -> None:
        health = await adapter.health()
        assert health.default_model_installed is True
        warmup = await adapter.embed_query(text)
        first = await adapter.embed_query(text)
        second = await adapter.embed_query(text)
        info = await adapter.model_info()
        assert info.model_ref == "qwen3-embedding:0.6b"
        assert info.dimension == 1024
        assert len(warmup) == len(first) == len(second) == 1024
        assert first == second
        assert _cosine(warmup, first) >= 0.999
        await adapter.aclose()

    asyncio.run(_run())
