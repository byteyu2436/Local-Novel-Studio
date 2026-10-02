import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from app.adapters.embedding import FakeEmbeddingProvider
from app.adapters.milvus.collections import MilvusCollectionClient
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.chunks import CanonChunk
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chunking import ChunkingProfile
from app.domain.embedding_profile import EmbeddingProfileSpec
from app.domain.milvus_collection import MilvusCollectionError
from app.services import catalog
from app.services.canon_chunks import build_chapter_chunks, list_canon_chunks
from app.services.embedding_batches import embed_canon_chunks
from app.services.embedding_profiles import activate_embedding_profile
from app.services.milvus_vectors import (
    canon_vector_row,
    delete_canon_embeddings,
    deletion_filter,
    metadata_filter,
    upsert_canon_embeddings,
)
from app.settings import get_settings


def _spec() -> EmbeddingProfileSpec:
    return EmbeddingProfileSpec(
        embedding_model_id="qwen3-embedding",
        embedding_model_tag="0.6b",
        embedding_model_version="0.6b",
        dimension=8,
        normalization="l2",
        chunking_version="chunking.v1",
    )


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
        "characters": ["林深"],
        "locations": ["雨巷"],
        "event_ids": [],
        "importance": "medium",
        "canon_status": "active",
        "chunking_version": "chunking.v1",
        "embedding_profile_id": None,
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return CanonChunk(**values)  # type: ignore[arg-type]


def _profile() -> SimpleNamespace:
    return SimpleNamespace(
        dimension=8,
        embedding_model_id="qwen3-embedding",
        embedding_model_tag="0.6b",
        embedding_model_version="0.6b",
        index_version="index",
        id="profile",
    )


def test_metadata_filter_limits_novel_and_canon_status() -> None:
    assert metadata_filter(novel_id="novel-1") == (
        'novel_id == "novel-1" and canon_status == "active"'
    )
    assert deletion_filter(chapter_id="chapter-2") == 'chapter_id == "chapter-2"'
    with pytest.raises(MilvusCollectionError) as empty:
        deletion_filter()
    assert empty.value.code == "filter_empty"


def test_draft_and_inactive_chunks_stay_out_of_the_index() -> None:
    profile = _profile()
    with pytest.raises(MilvusCollectionError) as draft:
        canon_vector_row(_chunk(source_version_kind="DRAFT"), [0.1] * 8, profile)  # type: ignore[arg-type]
    assert draft.value.code == "draft_cannot_enter_index"
    with pytest.raises(MilvusCollectionError) as inactive:
        canon_vector_row(_chunk(canon_status="inactive"), [0.1] * 8, profile)  # type: ignore[arg-type]
    assert inactive.value.code == "chunk_not_active"
    with pytest.raises(MilvusCollectionError) as mismatch:
        canon_vector_row(_chunk(), [0.1] * 4, profile)  # type: ignore[arg-type]
    assert mismatch.value.code == "dimension_mismatch"


def _index_client() -> tuple[MilvusCollectionClient, dict[str, dict[str, dict]], httpx.AsyncClient]:
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
        if request.url.path.endswith("/delete"):
            clauses = [part.strip() for part in body["filter"].split(" and ")]
            bucket = entities.setdefault(name, {})
            for key, row in list(bucket.items()):
                if all(_clause_matches(row, clause) for clause in clauses):
                    del bucket[key]
            return httpx.Response(200, json={"code": 0, "data": {}})
        return httpx.Response(404, json={"code": 404, "message": "missing"})

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:19530",
    )
    return MilvusCollectionClient(get_settings(), client=http_client), entities, http_client


def _clause_matches(row: dict, clause: str) -> bool:
    field, raw = clause.split("==")
    return str(row.get(field.strip())) == raw.strip().strip('"')


def test_upsert_is_idempotent_and_chapter_delete_is_scoped(isolated_data_dir) -> None:
    import asyncio

    _settings, engine, factory = bootstrap_local_runtime()
    client, entities, http_client = _index_client()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            first = catalog.create_chapter(session, novel.id, body="第一章看见旧伞。")
            second = catalog.create_chapter(session, novel.id, body="第二章放下茶杯。")
            chunking = ChunkingProfile(
                version="chunking.v1",
                target_min_tokens=4,
                target_max_tokens=40,
                overlap_tokens=2,
            )
            for chapter in (first, second):
                version = session.get(ChapterVersion, chapter.current_canon_version_id)
                build_chapter_chunks(session, novel.id, chapter, version, chunking)
            profile = activate_embedding_profile(session, _spec())
            asyncio.run(embed_canon_chunks(session, novel.id, FakeEmbeddingProvider(dimension=8)))
            kept = [row.id for row in list_canon_chunks(session, novel.id)]

            async def _run(
                session=session,
                novel=novel,
                profile=profile,
                first=first,
                second=second,
                kept=kept,
            ) -> None:
                written = await upsert_canon_embeddings(session, client, novel.id, profile)
                again = await upsert_canon_embeddings(session, client, novel.id, profile)
                bucket = next(iter(entities.values()))
                assert written == again == len(bucket) == len(kept)
                await delete_canon_embeddings(client, profile, chapter_id=second.id)
                assert {row["chapter_id"] for row in bucket.values()} == {first.id}

            asyncio.run(_run())
            assert [row.id for row in list_canon_chunks(session, novel.id)] == kept
    finally:
        asyncio.run(http_client.aclose())
        engine.dispose()
