import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest
from app.adapters.embedding import FakeEmbeddingProvider
from app.adapters.milvus.collections import MilvusCollectionClient
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.chunks import CanonChunk
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chunking import ChunkingProfile
from app.domain.embedding_profile import EmbeddingProfileSpec
from app.schemas.retrieval import QUERY_BUILDER_VERSION, SCORING_PROFILE_VERSION, QueryBuilderInput
from app.services import catalog
from app.services.canon_chunks import build_chapter_chunks
from app.services.embedding_profiles import activate_embedding_profile
from app.services.index_registry import activate_index, mark_index_validating, open_index_version
from app.services.retrieval import RetrievalServiceError, retrieve_evidence, summarize_latency
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


def _serve(session, profile) -> None:
    row = open_index_version(
        session,
        collection_name="novel_chunks_pipeline",
        embedding_profile_id=profile.id,
        chunking_version=profile.chunking_version,
        index_version=profile.index_version,
        record_count=1,
    )
    mark_index_validating(session, row.id)
    activate_index(session, row.id)


def _chapter_chunk(session, novel_id: str, body: str):
    chapter = catalog.create_chapter(session, novel_id, body=body)
    version = session.get(ChapterVersion, chapter.current_canon_version_id)
    chunk = build_chapter_chunks(
        session,
        novel_id,
        chapter,
        version,
        ChunkingProfile(
            version="chunking.v1",
            target_min_tokens=4,
            target_max_tokens=40,
            overlap_tokens=0,
        ),
    )[0]
    return chapter, chunk


def _hit(chunk: CanonChunk, distance: float) -> dict:
    return {
        "id": chunk.id,
        "chunk_id": chunk.id,
        "novel_id": chunk.novel_id,
        "chapter_id": chunk.chapter_id,
        "text_hash": chunk.text_checksum,
        "canon_status": "active",
        "distance": distance,
    }


def test_latency_summary_is_deterministic() -> None:
    summary = summarize_latency([10, 100, 20, 40, 30])
    assert summary == {"p50": 30, "p95": 100, "n": 5}
    assert summary["p50"] <= summary["p95"]


def test_fixed_query_returns_traceable_top_evidence(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            other = catalog.create_novel(session, "茶馆")
            _rain_chapter, rain = _chapter_chunk(session, novel.id, "林深走进雨巷。")
            _cafe_chapter, cafe = _chapter_chunk(session, novel.id, "周晚放下茶杯。")
            _other_chapter, foreign = _chapter_chunk(session, other.id, "另一本小说。")
            rain.characters = ["林深"]
            rain.locations = ["雨巷"]
            rain.event_ids = ["event-umbrella", "thread-umbrella"]
            rain.importance = "high"
            cafe.characters = ["周晚"]
            cafe.locations = ["茶馆"]
            overlap = CanonChunk(
                id="overlap-fixed",
                novel_id=rain.novel_id,
                chapter_id=rain.chapter_id,
                source_version_id=rain.source_version_id,
                source_version_kind=rain.source_version_kind,
                chunk_index=rain.chunk_index + 1,
                sequence=rain.sequence,
                chunk_type=rain.chunk_type,
                text=rain.text,
                text_checksum="overlap-fixed",
                start_offset=rain.start_offset + 1,
                end_offset=rain.end_offset,
                overlap_tokens=1,
                characters=[],
                locations=[],
                event_ids=[],
                importance="medium",
                canon_status="active",
                chunking_version=rain.chunking_version,
                embedding_profile_id=None,
                created_at=datetime.now(UTC),
            )
            session.add(overlap)
            session.flush()
            profile = activate_embedding_profile(session, _spec())
            _serve(session, profile)
            hits = [
                _hit(cafe, 0.95),
                _hit(foreign, 0.99),
                _hit(overlap, 0.5),
                _hit(rain, 0.55),
            ]
            client, calls, http_client = _client(hits)
            context = QueryBuilderInput(
                novel_id=novel.id,
                chapter_goal="找到雨巷里的旧伞",
                characters=["林深"],
                locations=["雨巷"],
                events=["event-umbrella"],
                foreshadowing=["thread-umbrella"],
            )

            async def _run(session=session, client=client, context=context):
                return await retrieve_evidence(
                    session,
                    client,
                    FakeEmbeddingProvider(dimension=8),
                    context,
                )

            try:
                reports = [asyncio.run(_run()) for _ in range(3)]
            finally:
                asyncio.run(http_client.aclose())
            report = reports[0]
            assert [item.chunk_id for item in report.result.evidence] == [rain.id, cafe.id]
            assert all(
                [item.chunk_id for item in later.result.evidence] == [rain.id, cafe.id]
                for later in reports
            )
            winner = report.result.evidence[0]
            assert winner.provenance.chapter_id == rain.chapter_id
            assert winner.provenance.chunk_id == rain.id
            assert winner.final_score is not None
            assert "character_match" in winner.metadata
            assert report.result.scoring_profile_version == SCORING_PROFILE_VERSION
            assert report.result.embedding_profile_id == profile.id
            assert report.result.index_version == profile.index_version
            assert report.result.collection_name == "novel_chunks_pipeline"
            assert report.query_builder_version == QUERY_BUILDER_VERSION
            assert report.selection_version == "evidence-selection.v1"
            assert report.empty is False
            assert {item.evidence.chunk_id: item.reason for item in report.rejected} == {
                "overlap-fixed": "overlap"
            }
            assert calls[0]["filter"].find(novel.id) >= 0
            assert other.id not in {item.chunk_id for item in report.result.evidence}
            summary = summarize_latency([item.elapsed_ms for item in reports])
            assert summary["n"] == 3
            assert summary["p50"] <= summary["p95"]
    finally:
        engine.dispose()


def test_empty_result_and_unavailable_dependencies_stay_explicit(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    client, calls, http_client = _client([])
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            context = QueryBuilderInput(novel_id=novel.id, chapter_goal="找伞")
            profile = activate_embedding_profile(session, _spec())

            async def _run(session=session, client=client, context=context, provider=None):
                return await retrieve_evidence(
                    session,
                    client,
                    provider or FakeEmbeddingProvider(dimension=8),
                    context,
                )

            with pytest.raises(RetrievalServiceError) as missing:
                asyncio.run(_run())
            assert missing.value.code == "no_active_index"
            _serve(session, profile)
            empty = asyncio.run(_run())
            assert empty.empty is True
            assert empty.result.evidence == []
            assert empty.elapsed_ms >= 0
            assert empty.result.novel_id == novel.id
            unavailable = FakeEmbeddingProvider(dimension=8, mode="unavailable")
            with pytest.raises(RetrievalServiceError) as offline:
                asyncio.run(_run(provider=unavailable))
            assert offline.value.code == "embedding_unavailable"
            activate_embedding_profile(session, _spec(dimension=16, embedding_model_tag="1b"))
            with pytest.raises(RetrievalServiceError) as mismatch:
                asyncio.run(_run())
            assert mismatch.value.code == "index_profile_mismatch"
            assert calls
            with pytest.raises(RetrievalServiceError) as unknown:
                asyncio.run(
                    _run(context=QueryBuilderInput(novel_id="missing-novel", chapter_goal="找伞"))
                )
            assert unknown.value.code == "novel_not_found"
    finally:
        asyncio.run(http_client.aclose())
        engine.dispose()
