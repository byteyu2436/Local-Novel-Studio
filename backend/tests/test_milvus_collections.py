import json

import httpx
import pytest
from app.adapters.milvus.collections import MilvusCollectionClient
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.chunks import CanonChunk
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chunking import ChunkingProfile
from app.domain.embedding_profile import (
    EmbeddingProfileSpec,
    index_version_for,
    profile_fingerprint,
)
from app.domain.milvus_collection import (
    COLLECTION_FIELDS,
    MilvusCollectionError,
    build_collection_spec,
    collection_name,
)
from app.services import catalog
from app.services.canon_chunks import build_chapter_chunks, list_canon_chunks
from app.services.embedding_profiles import activate_embedding_profile
from app.services.milvus_collections import (
    drop_profile_collection,
    ensure_profile_collection,
    spec_for_profile,
)
from app.settings import get_settings
from sqlalchemy import func, select


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


def _named(spec: EmbeddingProfileSpec) -> tuple[str, str]:
    fingerprint = profile_fingerprint(spec)
    version = index_version_for(fingerprint)
    return fingerprint, version


def test_collection_names_follow_profile_versions() -> None:
    left_id, left_version = _named(_spec())
    right_id, right_version = _named(_spec(dimension=16))
    left = collection_name(model_id="qwen3-embedding", model_tag="0.6b", index_version=left_version)
    right = collection_name(
        model_id="qwen3-embedding", model_tag="0.6b", index_version=right_version
    )
    assert left.startswith("novel_chunks_qwen3_embedding_0_6b_")
    assert left != right
    assert "-" not in left
    again = build_collection_spec(
        profile_id=left_id,
        embedding_model_id="qwen3-embedding",
        embedding_model_tag="0.6b",
        embedding_model_version="0.6b",
        dimension=8,
        chunking_version="chunking.v1",
        index_version=left_version,
    )
    assert again.name == left
    assert again.dimension == 8
    assert again.index.metric_type == "COSINE"
    assert again.index.index_type == "HNSW"
    assert again.metadata["profile_id"] == left_id
    assert again.metadata["chunking_version"] == "chunking.v1"
    with pytest.raises(MilvusCollectionError) as mismatch:
        build_collection_spec(
            profile_id=left_id,
            embedding_model_id="qwen3-embedding",
            embedding_model_tag="0.6b",
            embedding_model_version="0.6b",
            dimension=8,
            chunking_version="chunking.v1",
            index_version=left_version,
            requested_dimension=4,
        )
    assert mismatch.value.code == "dimension_mismatch"


def _store_client() -> tuple[MilvusCollectionClient, dict[str, dict], httpx.AsyncClient]:
    saved: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8") or "{}")
        name = body.get("collectionName", "")
        if request.url.path.endswith("/create"):
            saved[name] = body
            return httpx.Response(200, json={"code": 0, "data": {}})
        if request.url.path.endswith("/alter_properties"):
            saved[name]["properties"] = body.get("properties") or {}
            return httpx.Response(200, json={"code": 0, "data": {}})
        if request.url.path.endswith("/has"):
            return httpx.Response(200, json={"code": 0, "data": {"has": name in saved}})
        if request.url.path.endswith("/describe"):
            created = saved[name]
            schema = created["schema"]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "collectionName": name,
                        "description": schema["description"],
                        "fields": schema["fields"],
                        "indexParams": created["indexParams"],
                        "properties": [
                            {"key": key, "value": value}
                            for key, value in (created.get("properties") or {}).items()
                        ],
                    },
                },
            )
        if request.url.path.endswith("/drop"):
            saved.pop(name, None)
            return httpx.Response(200, json={"code": 0, "data": {}})
        return httpx.Response(404, json={"code": 404, "message": "missing"})

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:19530",
    )
    return MilvusCollectionClient(get_settings(), client=http_client), saved, http_client


def test_ensure_collection_is_idempotent_and_checks_dimension(isolated_data_dir) -> None:
    import asyncio

    _settings, engine, factory = bootstrap_local_runtime()
    client, saved, http_client = _store_client()
    try:
        for session in session_scope(factory):
            profile = activate_embedding_profile(session, _spec())
            other = spec_for_profile(profile)

            async def _run(profile=profile, other=other) -> None:
                created = await ensure_profile_collection(client, profile)
                again = await ensure_profile_collection(client, profile)
                assert created.name == again.name == other.name
                assert created.dimension == 8
                assert created.field_names == COLLECTION_FIELDS
                assert created.metadata["profile_id"] == profile.id
                assert created.metadata["chunking_version"] == "chunking.v1"
                assert created.index.metric_type == "COSINE"
                assert len(saved) == 1
                with pytest.raises(MilvusCollectionError) as mismatch:
                    await ensure_profile_collection(client, profile, requested_dimension=1024)
                assert mismatch.value.code == "dimension_mismatch"
                assert len(saved) == 1

            asyncio.run(_run())
    finally:
        asyncio_close(http_client)
        engine.dispose()


def test_drop_removes_the_index_and_keeps_sqlite_chunks(isolated_data_dir) -> None:
    import asyncio

    _settings, engine, factory = bootstrap_local_runtime()
    client, saved, http_client = _store_client()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深看见旧伞。")
            version = session.get(ChapterVersion, chapter.current_canon_version_id)
            chunking = ChunkingProfile(
                version="chunking.v1",
                target_min_tokens=4,
                target_max_tokens=40,
                overlap_tokens=2,
            )
            build_chapter_chunks(session, novel.id, chapter, version, chunking)
            profile = activate_embedding_profile(session, _spec(chunking_version="chunking.v1"))
            before = [row.id for row in list_canon_chunks(session, novel.id)]

            async def _run(profile=profile) -> None:
                created = await ensure_profile_collection(client, profile)
                await drop_profile_collection(client, created.name)
                assert created.name not in saved
                assert await client.exists(created.name) is False

            asyncio.run(_run())
            assert [row.id for row in list_canon_chunks(session, novel.id)] == before
            assert session.scalar(select(func.count()).select_from(CanonChunk)) == len(before)
    finally:
        asyncio_close(http_client)
        engine.dispose()


def test_unreachable_milvus_does_not_pretend_success() -> None:
    import asyncio

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:19530"
    )
    client = MilvusCollectionClient(get_settings(), client=http_client)

    async def _run() -> None:
        with pytest.raises(MilvusCollectionError) as down:
            await client.exists("novel_chunks_qwen3_embedding_0_6b_abc")
        assert down.value.code == "milvus_unavailable"

    try:
        asyncio.run(_run())
    finally:
        asyncio_close(http_client)


def asyncio_close(http_client: httpx.AsyncClient) -> None:
    import asyncio

    asyncio.run(http_client.aclose())


def test_live_milvus_collection_roundtrip() -> None:
    import asyncio

    settings = get_settings()
    health_url = f"http://{settings.milvus_host}:{settings.milvus_health_port}/healthz"
    try:
        health = httpx.get(health_url, timeout=2)
    except httpx.HTTPError:
        pytest.skip("Milvus is not running.")
    if health.status_code >= 400:
        pytest.skip("Milvus healthz is not OK.")
    spec = _spec(dimension=8, chunking_version="chunking.live")
    fingerprint, version = _named(spec)
    built = build_collection_spec(
        profile_id=fingerprint,
        embedding_model_id=spec.embedding_model_id,
        embedding_model_tag=spec.embedding_model_tag,
        embedding_model_version=spec.embedding_model_version,
        dimension=spec.dimension,
        chunking_version=spec.chunking_version,
        index_version=version,
    )
    client = MilvusCollectionClient(settings)

    async def _run() -> None:
        try:
            if await client.exists(built.name):
                await client.drop(built.name)
            await client.create(built)
            described = await client.describe(built.name)
            assert described.dimension == 8
            assert described.metadata["profile_id"] == fingerprint
            assert described.metadata["chunking_version"] == "chunking.live"
            assert described.index.metric_type == "COSINE"
            await client.upsert(
                built.name,
                [
                    {
                        "id": "chunk-live",
                        "novel_id": "novel-live",
                        "chapter_id": "chapter-live",
                        "chunk_id": "chunk-live",
                        "sequence": 1,
                        "text_hash": "abc",
                        "characters": ["林深"],
                        "locations": ["雨巷"],
                        "canon_status": "active",
                        "embedding_model": "qwen3-embedding:0.6b",
                        "embedding_version": "0.6b",
                        "embedding": [0.1] * 8,
                        "created_at": 1,
                    }
                ],
            )
            await client.delete_where(built.name, 'chunk_id == "chunk-live"')
        finally:
            if await client.exists(built.name):
                await client.drop(built.name)
            assert await client.exists(built.name) is False
            await client.aclose()

    asyncio.run(_run())
