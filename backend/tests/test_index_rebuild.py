import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest
from app.adapters.embedding import FakeEmbeddingProvider
from app.adapters.embedding.errors import EmbeddingProfileMismatchError
from app.adapters.milvus.collections import CollectionDescription, MilvusCollectionClient
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.chunks import CanonChunk
from app.adapters.sqlite.embeddings import ChunkEmbedding
from app.adapters.sqlite.index_registry import IndexVersionRecord
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chapter_canon import add_draft_version
from app.domain.embedding_profile import EmbeddingProfileSpec
from app.domain.index_registry import index_manifest
from app.domain.milvus_collection import IndexParameterProfile
from app.services import catalog
from app.services.canon_chunks import list_canon_chunks
from app.services.embedding_profiles import activate_embedding_profile
from app.services.index_rebuild import (
    RebuildError,
    corpus_checksum,
    rebuild_canon_index,
    validate_rebuild,
)
from app.services.index_registry import serving_index
from app.settings import get_settings
from sqlalchemy import select


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


def _chunk(**overrides: object) -> CanonChunk:
    values: dict[str, object] = {
        "id": "chunk",
        "novel_id": "novel",
        "chapter_id": "chapter",
        "source_version_id": "version",
        "source_version_kind": "ORIGINAL",
        "chunk_index": 0,
        "sequence": 1,
        "chunk_type": "chapter",
        "text": "正文",
        "text_checksum": "abc",
        "start_offset": 0,
        "end_offset": 2,
        "overlap_tokens": 0,
        "characters": [],
        "locations": [],
        "event_ids": [],
        "importance": "medium",
        "canon_status": "active",
        "chunking_version": "chunking.v1",
        "embedding_profile_id": None,
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return CanonChunk(**values)  # type: ignore[arg-type]


def _client() -> tuple[MilvusCollectionClient, dict[str, dict[str, dict]], httpx.AsyncClient]:
    saved: dict[str, dict] = {}
    entities: dict[str, dict[str, dict]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8") or "{}")
        name = body.get("collectionName", "")
        if request.url.path.endswith("/create"):
            saved[name] = body
            entities[name] = {}
            return httpx.Response(200, json={"code": 0, "data": {}})
        if request.url.path.endswith("/alter_properties"):
            saved[name]["properties"] = body.get("properties") or {}
            return httpx.Response(200, json={"code": 0, "data": {}})
        if request.url.path.endswith("/has"):
            return httpx.Response(200, json={"code": 0, "data": {"has": name in saved}})
        if request.url.path.endswith("/describe"):
            if name not in saved:
                return httpx.Response(404, json={"code": 404, "message": "missing"})
            schema = saved[name]["schema"]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "collectionName": name,
                        "description": schema["description"],
                        "fields": schema["fields"],
                        "indexParams": saved[name]["indexParams"],
                        "properties": [
                            {"key": key, "value": value}
                            for key, value in (saved[name].get("properties") or {}).items()
                        ],
                    },
                },
            )
        if request.url.path.endswith("/upsert"):
            bucket = entities.setdefault(name, {})
            for row in body["data"]:
                assert "text" not in row
                bucket[row["id"]] = row
            return httpx.Response(200, json={"code": 0, "data": {}})
        if request.url.path.endswith("/drop"):
            saved.pop(name, None)
            entities.pop(name, None)
            return httpx.Response(200, json={"code": 0, "data": {}})
        return httpx.Response(404, json={"code": 404, "message": "missing"})

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:19530",
    )
    return MilvusCollectionClient(get_settings(), client=http_client), entities, http_client


def test_manifest_rejects_dimension_and_checksum_drift() -> None:
    chunk = _chunk()
    described = CollectionDescription(
        name="novel_chunks_demo",
        dimension=8,
        field_names=("id",),
        metadata={
            "profile_id": "profile",
            "index_version": "index",
            "chunking_version": "chunking.v1",
        },
        index=IndexParameterProfile(),
    )
    _text, checksum = index_manifest(
        collection_name=described.name,
        embedding_profile_id="profile",
        chunking_version="chunking.v1",
        index_version="index",
        record_count=1,
        corpus_checksum=corpus_checksum([chunk]),
    )
    validate_rebuild(
        described=described,
        profile_id="profile",
        index_version="index",
        dimension=8,
        chunks=[chunk],
        vector_count=1,
        manifest_checksum=checksum,
        collection_name=described.name,
    )
    with pytest.raises(RebuildError) as wrong_dim:
        validate_rebuild(
            described=described,
            profile_id="profile",
            index_version="index",
            dimension=4,
            chunks=[chunk],
            vector_count=1,
            manifest_checksum=checksum,
            collection_name=described.name,
        )
    assert wrong_dim.value.code == "rebuild_profile_mismatch"
    with pytest.raises(RebuildError) as wrong_sum:
        validate_rebuild(
            described=described,
            profile_id="profile",
            index_version="index",
            dimension=8,
            chunks=[chunk],
            vector_count=1,
            manifest_checksum="0" * 64,
            collection_name=described.name,
        )
    assert wrong_sum.value.code == "manifest_mismatch"


def test_rebuild_switches_after_validation_and_keeps_chunk_ids(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    client, entities, http_client = _client()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            first = catalog.create_chapter(session, novel.id, body="林深走进雨里。")
            catalog.create_chapter(session, novel.id, body="她放下旧伞。")
            original = session.get(ChapterVersion, first.current_canon_version_id)
            add_draft_version(
                first,
                body="草稿不能入库。",
                parent=original,
                created_at=datetime.now(UTC),
            )
            activate_embedding_profile(session, _spec())
            provider = FakeEmbeddingProvider(dimension=8)

            async def _rebuild(session=session, provider=provider):
                return await rebuild_canon_index(session, client, provider)

            report = asyncio.run(_rebuild())
            serving = serving_index(session)
            assert serving is not None
            assert report.status == "active"
            assert report.switched is True
            assert serving.collection_name == report.collection_name
            assert report.vector_count == report.chunk_count > 0
            assert len(entities[report.collection_name]) == report.chunk_count
            texts = [row.text for row in list_canon_chunks(session, novel.id)]
            assert texts
            assert all("草稿" not in text for text in texts)
            chunk_ids = [row.id for row in list_canon_chunks(session, novel.id)]

            second = asyncio.run(_rebuild())
            session.expire_all()
            previous = session.get(IndexVersionRecord, report.index_id)
            assert previous is not None
            assert previous.status == "superseded"
            assert second.collection_name != report.collection_name
            assert serving_index(session).id == second.index_id
            assert [row.id for row in list_canon_chunks(session, novel.id)] == chunk_ids
            assert len(entities[second.collection_name]) == len(chunk_ids)
    finally:
        asyncio.run(http_client.aclose())
        engine.dispose()


def test_embedding_failure_keeps_the_serving_index(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    client, entities, http_client = _client()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            catalog.create_chapter(session, novel.id, body="林深走进雨里。")
            activate_embedding_profile(session, _spec())
            provider = FakeEmbeddingProvider(dimension=8)

            async def _rebuild(session=session, provider=provider):
                return await rebuild_canon_index(session, client, provider)

            first = asyncio.run(_rebuild())
            for row in session.scalars(select(ChunkEmbedding)):
                row.status = "failed"
                row.vector = None
            session.flush()
            broken = FakeEmbeddingProvider(dimension=8, mode="unavailable")

            async def _fail(session=session, broken=broken):
                return await rebuild_canon_index(session, client, broken)

            with pytest.raises(RebuildError) as failed:
                asyncio.run(_fail())
            session.expire_all()
            assert failed.value.code == "rebuild_embedding_failed"
            assert serving_index(session).collection_name == first.collection_name
            failed_row = session.get(IndexVersionRecord, failed.value.index_id)
            assert failed_row is not None
            assert failed_row.status == "failed"
            assert first.collection_name in entities
            assert failed_row.collection_name not in entities
    finally:
        asyncio.run(http_client.aclose())
        engine.dispose()


def test_dropped_collection_rebuilds_from_sqlite_canon(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    client, entities, http_client = _client()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            catalog.create_chapter(session, novel.id, body="林深走进雨里。")
            activate_embedding_profile(session, _spec())
            provider = FakeEmbeddingProvider(dimension=8)

            async def _rebuild(session=session, provider=provider):
                return await rebuild_canon_index(session, client, provider)

            first = asyncio.run(_rebuild())
            chunk_ids = [row.id for row in list_canon_chunks(session, novel.id)]
            asyncio.run(client.drop(first.collection_name))
            assert first.collection_name not in entities
            restored = asyncio.run(_rebuild())
            assert restored.collection_name != first.collection_name
            assert set(entities[restored.collection_name]) == set(chunk_ids)
            assert [row.id for row in list_canon_chunks(session, novel.id)] == chunk_ids
            assert serving_index(session).collection_name == restored.collection_name
    finally:
        asyncio.run(http_client.aclose())
        engine.dispose()


def test_rebuild_refuses_a_different_embedding_profile(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    client, entities, http_client = _client()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            catalog.create_chapter(session, novel.id, body="林深走进雨里。")
            first = activate_embedding_profile(session, _spec())
            provider = FakeEmbeddingProvider(dimension=8)

            async def _rebuild(session=session, profile_id=None, provider=provider):
                return await rebuild_canon_index(session, client, provider, profile_id=profile_id)

            report = asyncio.run(_rebuild())
            before = dict(entities[report.collection_name])
            activate_embedding_profile(session, _spec(dimension=16, embedding_model_tag="1b"))

            async def _wrong(session=session, profile_id=first.id, provider=provider):
                return await rebuild_canon_index(session, client, provider, profile_id=profile_id)

            with pytest.raises(EmbeddingProfileMismatchError):
                asyncio.run(_wrong())
            assert serving_index(session).collection_name == report.collection_name
            assert entities[report.collection_name] == before
    finally:
        asyncio.run(http_client.aclose())
        engine.dispose()


def test_dimension_validation_failure_does_not_switch(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    client, _entities, http_client = _client()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            catalog.create_chapter(session, novel.id, body="林深走进雨里。")
            activate_embedding_profile(session, _spec())
            provider = FakeEmbeddingProvider(dimension=8)

            async def _rebuild(session=session, provider=provider):
                return await rebuild_canon_index(session, client, provider)

            first = asyncio.run(_rebuild())
            real_describe = client.describe

            async def _lie(name: str, real=real_describe, keep=first.collection_name):
                described = await real(name)
                if name == keep:
                    return described
                return CollectionDescription(
                    name=described.name,
                    dimension=1,
                    field_names=described.field_names,
                    metadata=described.metadata,
                    index=described.index,
                )

            client.describe = _lie  # type: ignore[method-assign]
            with pytest.raises(RebuildError) as failed:
                asyncio.run(_rebuild())
            session.expire_all()
            assert failed.value.code == "rebuild_profile_mismatch"
            assert serving_index(session).collection_name == first.collection_name
            failed_row = session.get(IndexVersionRecord, failed.value.index_id)
            assert failed_row is not None
            assert failed_row.status == "failed"
            assert asyncio.run(client.exists(failed_row.collection_name)) is False
    finally:
        asyncio.run(http_client.aclose())
        engine.dispose()
