import asyncio
import json

import httpx
import pytest
from app.adapters.embedding import FakeEmbeddingProvider
from app.adapters.embedding.errors import EmbeddingUnavailableError
from app.adapters.milvus.collections import MilvusCollectionClient
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chunking import ChunkingProfile
from app.domain.embedding_profile import EmbeddingProfileSpec
from app.domain.milvus_collection import MilvusCollectionError, build_collection_spec
from app.schemas.retrieval import QueryBuilderInput, RetrievalQuery
from app.services import catalog
from app.services.canon_chunks import build_chapter_chunks
from app.services.dense_retrieval import (
    DENSE_CANDIDATE_LIMIT,
    DenseRetrievalError,
    dense_retrieve,
)
from app.services.embedding_profiles import activate_embedding_profile
from app.services.index_registry import (
    IndexRegistryError,
    activate_index,
    mark_index_validating,
    open_index_version,
)
from app.services.milvus_vectors import retrieval_filter
from app.services.query_builder import build_retrieval_query
from app.settings import get_settings


def _spec(**overrides: object) -> EmbeddingProfileSpec:
    values: dict[str, object] = {
        "embedding_model_id": "qwen3-embedding",
        "embedding_model_tag": "0.6b",
        "embedding_model_version": "0.6b",
        "dimension": 8,
        "normalization": "l2",
        "chunking_version": "chunking.v1",
    }
    values.update(overrides)
    return EmbeddingProfileSpec(**values)  # type: ignore[arg-type]


def test_retrieval_filter_scopes_novel_canon_and_entity_hints() -> None:
    expr = retrieval_filter(
        novel_id="novel-a",
        characters=["林深", "周晚"],
        locations=["雨巷"],
    )
    assert 'novel_id == "novel-a"' in expr
    assert 'canon_status == "active"' in expr
    assert 'json_contains(characters, "林深")' in expr
    assert 'json_contains(characters, "周晚")' in expr
    assert 'json_contains(locations, "雨巷")' in expr
    assert " or " in expr
    with pytest.raises(MilvusCollectionError) as invalid:
        retrieval_filter(novel_id='say "no"')
    assert invalid.value.code == "filter_value_invalid"


def _client(hits: list[dict]) -> tuple[MilvusCollectionClient, list[dict], httpx.AsyncClient]:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8") or "{}")
        if request.url.path.endswith("/load"):
            return httpx.Response(200, json={"code": 0, "data": {}})
        if request.url.path.endswith("/search"):
            calls.append(body)
            return httpx.Response(200, json={"code": 0, "data": hits})
        return httpx.Response(404, json={"code": 404, "message": "missing"})

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:19530",
    )
    return MilvusCollectionClient(get_settings(), client=http_client), calls, http_client


def _serve(session, profile, name: str) -> None:
    row = open_index_version(
        session,
        collection_name=name,
        embedding_profile_id=profile.id,
        chunking_version=profile.chunking_version,
        index_version=profile.index_version,
        record_count=1,
    )
    mark_index_validating(session, row.id)
    activate_index(session, row.id)


def _chunk_novel(session, title: str, body: str):
    novel = catalog.create_novel(session, title)
    chapter = catalog.create_chapter(session, novel.id, body=body)
    version = session.get(ChapterVersion, chapter.current_canon_version_id)
    chunks = build_chapter_chunks(
        session,
        novel.id,
        chapter,
        version,
        ChunkingProfile(
            version="chunking.v1",
            target_min_tokens=4,
            target_max_tokens=40,
            overlap_tokens=0,
        ),
    )
    return novel, chapter, chunks[0]


def test_dense_recall_stays_in_one_novel_and_keeps_milvus_order(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            left_novel, left_chapter, left = _chunk_novel(session, "雨巷", "林深走进雨里。")
            later = catalog.create_chapter(session, left_novel.id, body="她认出旧伞。")
            later_version = session.get(ChapterVersion, later.current_canon_version_id)
            later_chunk = build_chapter_chunks(
                session,
                left_novel.id,
                later,
                later_version,
                ChunkingProfile(
                    version="chunking.v1",
                    target_min_tokens=4,
                    target_max_tokens=40,
                    overlap_tokens=0,
                ),
            )[0]
            _other, _other_chapter, right = _chunk_novel(session, "茶馆", "周晚放下茶杯。")
            profile = activate_embedding_profile(session, _spec())
            _serve(session, profile, "novel_chunks_dense")
            hits = [
                {
                    "id": right.id,
                    "chunk_id": right.id,
                    "novel_id": right.novel_id,
                    "chapter_id": right.chapter_id,
                    "text_hash": right.text_checksum,
                    "canon_status": "active",
                    "distance": 0.2,
                },
                {
                    "id": later_chunk.id,
                    "chunk_id": later_chunk.id,
                    "novel_id": left.novel_id,
                    "chapter_id": later.id,
                    "text_hash": later_chunk.text_checksum,
                    "canon_status": "active",
                    "distance": 0.2,
                },
                {
                    "id": left.id,
                    "chunk_id": left.id,
                    "novel_id": left.novel_id,
                    "chapter_id": left.chapter_id,
                    "text_hash": left.text_checksum,
                    "canon_status": "active",
                    "distance": 0.9,
                },
                {
                    "id": "missing-draft",
                    "chunk_id": "missing-draft",
                    "novel_id": left.novel_id,
                    "chapter_id": left.chapter_id,
                    "text_hash": "nope",
                    "canon_status": "active",
                    "distance": 0.99,
                },
            ]
            client, calls, http_client = _client(hits)
            query = build_retrieval_query(
                QueryBuilderInput(
                    novel_id=left.novel_id,
                    chapter_goal="找到雨巷",
                    characters=["林深"],
                    locations=["雨巷"],
                    top_n=1,
                )
            )

            async def _run(session=session, query=query, client=client):
                return await dense_retrieve(
                    session,
                    client,
                    FakeEmbeddingProvider(dimension=8),
                    query,
                )

            try:
                result = asyncio.run(_run())
            finally:
                asyncio.run(http_client.aclose())
            assert calls[0]["limit"] == DENSE_CANDIDATE_LIMIT
            assert calls[0]["collectionName"] == "novel_chunks_dense"
            assert f'novel_id == "{left.novel_id}"' in calls[0]["filter"]
            assert 'canon_status == "active"' in calls[0]["filter"]
            assert 'json_contains(characters, "林深")' in calls[0]["filter"]
            assert [item.chunk_id for item in result.evidence] == [later_chunk.id, left.id]
            assert [item.dense_score for item in result.evidence] == [0.2, 0.9]
            assert result.evidence[0].business_score is None
            assert result.evidence[0].final_score is None
            assert result.evidence[0].provenance.chapter_id == later.id
            assert result.evidence[1].chapter_id == left_chapter.id
            assert result.collection_name == "novel_chunks_dense"
            assert len(result.evidence) == 2
            assert query.top_n == 1
    finally:
        engine.dispose()


def test_profile_or_index_failure_does_not_search_another_version(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    client, calls, http_client = _client([])
    try:
        for session in session_scope(factory):
            catalog.create_novel(session, "雨巷")
            first = activate_embedding_profile(session, _spec())
            query = RetrievalQuery(novel_id="novel", chapter_goal="找伞")

            async def _run(session=session, query=query, provider=None):
                return await dense_retrieve(
                    session,
                    client,
                    provider or FakeEmbeddingProvider(dimension=8),
                    query,
                )

            with pytest.raises(IndexRegistryError) as missing:
                asyncio.run(_run())
            assert missing.value.code == "no_active_index"
            assert calls == []
            _serve(session, first, "novel_chunks_first")
            draft = RetrievalQuery(novel_id="novel", corpus="draft", include_draft=True)
            with pytest.raises(DenseRetrievalError) as draft_error:
                asyncio.run(_run(query=draft))
            assert draft_error.value.code == "draft_retrieval_unsupported"
            with pytest.raises(DenseRetrievalError) as empty:
                asyncio.run(_run(query=RetrievalQuery(novel_id="novel")))
            assert empty.value.code == "query_text_empty"
            unavailable = FakeEmbeddingProvider(dimension=8, mode="unavailable")
            with pytest.raises(EmbeddingUnavailableError):
                asyncio.run(_run(provider=unavailable))
            assert calls == []
            activate_embedding_profile(session, _spec(dimension=16, embedding_model_tag="1b"))
            with pytest.raises(DenseRetrievalError) as mismatch:
                asyncio.run(_run())
            assert mismatch.value.code == "index_profile_mismatch"
            assert calls == []
    finally:
        asyncio.run(http_client.aclose())
        engine.dispose()


def test_live_dense_search_smoke() -> None:
    settings = get_settings()
    health_url = f"http://{settings.milvus_host}:{settings.milvus_health_port}/healthz"
    try:
        health = httpx.get(health_url, timeout=2)
    except httpx.HTTPError:
        pytest.skip("Milvus is not running.")
    if health.status_code >= 400:
        pytest.skip("Milvus healthz is not OK.")
    spec = _spec(chunking_version="chunking.dense")
    built = build_collection_spec(
        profile_id="dense-live",
        embedding_model_id=spec.embedding_model_id,
        embedding_model_tag=spec.embedding_model_tag,
        embedding_model_version=spec.embedding_model_version,
        dimension=spec.dimension,
        chunking_version=spec.chunking_version,
        index_version="dense-live",
        name_suffix="densesmoke",
    )
    client = MilvusCollectionClient(settings)

    def _row(chunk_id: str, novel_id: str, characters: list[str], vector: list[float]) -> dict:
        return {
            "id": chunk_id,
            "novel_id": novel_id,
            "chapter_id": f"chapter-{chunk_id}",
            "chunk_id": chunk_id,
            "sequence": 1,
            "text_hash": "abc",
            "characters": characters,
            "locations": ["雨巷"],
            "canon_status": "active",
            "embedding_model": "qwen3-embedding:0.6b",
            "embedding_version": "0.6b",
            "embedding": vector,
            "created_at": 1,
        }

    async def _run() -> None:
        try:
            if await client.exists(built.name):
                await client.drop(built.name)
            await client.create(built)
            await client.upsert(
                built.name,
                [
                    _row("near", "novel-a", ["林深"], [1, 0, 0, 0, 0, 0, 0, 0]),
                    _row("far", "novel-a", ["周晚"], [0, 1, 0, 0, 0, 0, 0, 0]),
                    _row("other", "novel-b", ["林深"], [1, 0, 0, 0, 0, 0, 0, 0]),
                ],
            )
            expr = retrieval_filter(novel_id="novel-a", characters=["林深"])
            hits = await client.search(
                built.name,
                [1, 0, 0, 0, 0, 0, 0, 0],
                filter_expr=expr,
                limit=DENSE_CANDIDATE_LIMIT,
                output_fields=["chunk_id", "novel_id", "chapter_id", "text_hash", "canon_status"],
            )
            assert [hit.chunk_id for hit in hits] == ["near"]
            assert hits[0].novel_id == "novel-a"
            assert hits[0].score == 1
        finally:
            if await client.exists(built.name):
                await client.drop(built.name)
            await client.aclose()

    asyncio.run(_run())
