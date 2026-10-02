import asyncio
import json
import time
from datetime import UTC, datetime

import pytest
from app.adapters.embedding import FakeEmbeddingProvider
from app.adapters.embedding.ollama import OllamaEmbeddingAdapter
from app.adapters.milvus.collections import MilvusCollectionClient
from app.adapters.ollama.adapter import OllamaAdapter
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.chunks import CanonChunk
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chapter_canon import add_draft_version
from app.domain.embedding_profile import EmbeddingProfileSpec
from app.eval.benchmark import load_benchmark_dataset
from app.eval.benchmark_report import result_payload, write_benchmark_report
from app.eval.benchmark_runner import run_benchmark
from app.schemas.analysis import ChapterAnalysisPayload, ChapterSummary, StyleSignals
from app.schemas.retrieval import QueryBuilderInput
from app.services import catalog
from app.services.analysis import persist_chapter_analysis
from app.services.canon_chunks import list_canon_chunks
from app.services.embedding_profiles import activate_embedding_profile
from app.services.index_rebuild import rebuild_canon_index
from app.services.index_registry import serving_index
from app.services.initialization import execute_initialization, novel_is_ready, writing_gate
from app.services.milvus_vectors import metadata_filter
from app.services.retrieval import retrieve_evidence
from app.settings import get_settings
from sqlalchemy import select
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
            summary=ChapterSummary(synopsis=f"第{chapter.sequence}章"),
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


def test_eighteen_chapter_cpu_path_rebuilds_and_writes_a_report(tmp_path) -> None:
    """CPU fake embeddings and the Milvus mock. This is not GPU evidence."""

    _settings, engine, factory = bootstrap_local_runtime()
    client, entities, http_client = mock_milvus()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "十八章")
            chapters = [
                catalog.create_chapter(
                    session, novel.id, body=f"第{index}章，林深记得雨巷里的第{index}件事。"
                )
                for index in range(1, 19)
            ]
            other = catalog.create_novel(session, "另一本")
            catalog.create_chapter(session, other.id, body="另一本小说的林深不该被检索到。")
            version = session.get(ChapterVersion, chapters[0].current_canon_version_id)
            add_draft_version(
                chapters[0],
                body="草稿不能进入索引。",
                parent=version,
                created_at=datetime.now(UTC),
            )
            for chapter in chapters:
                _analyze(session, chapter)
            activate_embedding_profile(session, _spec())
            provider = FakeEmbeddingProvider(dimension=8)

            async def _init(session=session, provider=provider, novel_id=novel.id):
                return await execute_initialization(session, client, provider, novel_id)

            ready = asyncio.run(_init())
            assert ready.current_phase == "ready"
            assert novel_is_ready(session, novel.id) is True
            before = [chunk.id for chunk in list_canon_chunks(session, novel.id)]
            assert len(before) == 18
            first_name = ready.index_fingerprint
            serving_name = next(iter(entities))
            asyncio.run(client.drop(serving_name))
            assert serving_name not in entities

            async def _rebuild(session=session, provider=provider):
                return await rebuild_canon_index(session, client, provider)

            rebuilt = asyncio.run(_rebuild())
            after = [chunk.id for chunk in list_canon_chunks(session, novel.id)]
            assert after == before
            assert rebuilt.collection_name != serving_name
            stored = " ".join(str(row) for row in entities[rebuilt.collection_name].values())
            assert "草稿不能进入索引" not in stored
            other_ids = set(
                session.scalars(select(CanonChunk.id).where(CanonChunk.novel_id == other.id))
            )
            assert other_ids
            assert other_ids <= set(entities[rebuilt.collection_name])

            async def _debug(session=session, provider=provider, novel_id=novel.id):
                return await retrieve_evidence(
                    session,
                    client,
                    provider,
                    QueryBuilderInput(novel_id=novel_id, chapter_goal="林深记得雨巷"),
                    debug=True,
                )

            traced = asyncio.run(_debug())
            assert traced.trace is not None
            assert traced.trace.final_evidence_ids
            assert all(item.novel_id == novel.id for item in traced.result.evidence)
            selected = next(item for item in traced.trace.candidates if item.status == "selected")
            assert selected.excerpt
            assert selected.reason == "selected"

            async def _bench(session=session, provider=provider, novel_id=novel.id):
                return await run_benchmark(session, client, provider, novel_id)

            result = asyncio.run(_bench())
            json_path, md_path = write_benchmark_report(result, tmp_path)
            assert json_path.exists() and md_path.exists()
            assert "林深住在城南" not in json_path.read_text(encoding="utf-8")
            assert first_name
    finally:
        engine.dispose()
        asyncio.run(http_client.aclose())


def _windows_gpu() -> bool:
    get_settings.cache_clear()
    return get_settings().lns_execution_profile.value == "windows-gpu"


def _gpu_profile() -> EmbeddingProfileSpec:
    return EmbeddingProfileSpec(
        embedding_model_id="qwen3-embedding",
        embedding_model_tag="0.6b",
        embedding_model_version="0.6b",
        dimension=1024,
        normalization="l2",
        chunking_version="chunking.v1",
    )


def _eighteen_bodies() -> list[str]:
    """Benchmark chapters 1–6, plus twelve filler chapters so the corpus is 18."""

    bodies = [chapter.body for chapter in load_benchmark_dataset().chapters]
    fillers = [
        f"第{index}章记下与主线无关的杂事，市集灯笼亮了一次。"
        for index in range(7, 19)
    ]
    return bodies + fillers


@pytest.mark.skipif(
    not _windows_gpu(), reason="Real 18-chapter GPU baseline is a separate windows-gpu run."
)
def test_eighteen_chapter_windows_gpu_baseline(tmp_path) -> None:
    """Real qwen3.5:9b analysis, qwen3-embedding:0.6b, and Milvus. This is GPU evidence."""

    settings = get_settings()
    provider = OllamaEmbeddingAdapter(settings, expected_dimension=1024, normalization="l2")
    llm = OllamaAdapter(settings)
    client = MilvusCollectionClient(settings)
    created: list[str] = []
    _settings, engine, factory = bootstrap_local_runtime()
    started = time.perf_counter()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "十八章")
            chapters = [
                catalog.create_chapter(session, novel.id, body=body) for body in _eighteen_bodies()
            ]
            other = catalog.create_novel(session, "另一本")
            catalog.create_chapter(session, other.id, body="另一本小说里的海港灯塔不该被检索到。")
            version = session.get(ChapterVersion, chapters[0].current_canon_version_id)
            add_draft_version(
                chapters[0],
                body="草稿不能进入索引。",
                parent=version,
                created_at=datetime.now(UTC),
            )
            activate_embedding_profile(session, _gpu_profile())

            async def _run(session=session, novel_id=novel.id, other_id=other.id) -> None:
                try:
                    ready = await execute_initialization(
                        session, client, provider, novel_id, llm=llm
                    )
                    assert ready.state == "completed", (ready.error_code, ready.error_message)
                    assert ready.current_phase == "ready"
                    assert novel_is_ready(session, novel_id) is True
                    gate = writing_gate(session, novel_id)
                    assert gate["ready"] is True
                    assert gate["message"] == "初始化已完成，可以阅读，也可以进入续写。"
                    before = [chunk.id for chunk in list_canon_chunks(session, novel_id)]
                    assert len(before) == 18
                    stored_text = " ".join(
                        chunk.text for chunk in session.scalars(select(CanonChunk))
                    )
                    assert "草稿不能进入索引" not in stored_text
                    serving = serving_index(session)
                    assert serving is not None
                    created.append(serving.collection_name)
                    await client.drop(serving.collection_name)
                    rebuilt = await rebuild_canon_index(session, client, provider)
                    created.append(rebuilt.collection_name)
                    after = [chunk.id for chunk in list_canon_chunks(session, novel_id)]
                    assert after == before
                    assert rebuilt.collection_name != serving.collection_name
                    chunk_total = len(list(session.scalars(select(CanonChunk.id))))
                    assert rebuilt.vector_count == chunk_total
                    described = await client.describe(rebuilt.collection_name)
                    assert described.dimension == 1024
                    vector = await provider.embed_query("海港灯塔")
                    other_hits = await client.search(
                        rebuilt.collection_name,
                        vector,
                        filter_expr=metadata_filter(novel_id=other_id),
                        limit=4,
                        output_fields=["novel_id", "chunk_id"],
                    )
                    assert other_hits
                    assert {hit.novel_id for hit in other_hits} == {other_id}
                    traced = await retrieve_evidence(
                        session,
                        client,
                        provider,
                        QueryBuilderInput(novel_id=novel_id, chapter_goal="林深住在哪里"),
                        debug=True,
                    )
                    assert traced.trace is not None
                    assert traced.trace.final_evidence_ids
                    assert all(item.novel_id == novel_id for item in traced.result.evidence)
                    selected = next(
                        item for item in traced.trace.candidates if item.status == "selected"
                    )
                    assert selected.excerpt
                    assert selected.reason == "selected"
                    other_chunk_ids = {hit.chunk_id for hit in other_hits}
                    assert other_chunk_ids.isdisjoint(traced.trace.final_evidence_ids)
                    boundary = await retrieve_evidence(
                        session,
                        client,
                        provider,
                        QueryBuilderInput(novel_id=novel_id, chapter_goal="海底龙宫的钥匙在哪"),
                        debug=True,
                    )
                    assert boundary.trace is not None
                    assert boundary.trace.candidates
                    assert all(item.novel_id == novel_id for item in boundary.result.evidence)
                    assert {item.status for item in boundary.trace.candidates}
                    result = await run_benchmark(session, client, provider, novel_id)
                    json_path, md_path = write_benchmark_report(result, tmp_path)
                    payload = result_payload(result)
                    assert json_path.exists() and md_path.exists()
                    assert set(payload["by_category"]) == {
                        "character",
                        "relationship",
                        "event",
                        "location",
                        "foreshadowing",
                        "timeline",
                    }
                    manifest = {
                        "chunk_count": len(before),
                        "vector_count": rebuilt.vector_count,
                        "dimension": described.dimension,
                        "collection_name": rebuilt.collection_name,
                        "embedding_profile_id": payload["embedding_profile_id"],
                        "index_version": payload["index_version"],
                        "scoring_profile_version": payload["scoring_profile_version"],
                        "recall_at_5": payload["recall_at_5"],
                        "recall_at_10": payload["recall_at_10"],
                        "source_hit_rate": payload["source_hit_rate"],
                        "by_category": payload["by_category"],
                        "failures": payload["failures"],
                        "selected_excerpt": selected.excerpt,
                        "init_elapsed_s": round(time.perf_counter() - started, 1),
                    }
                    (tmp_path / "manifest.json").write_text(
                        json.dumps(manifest, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print("GPU_BASELINE " + json.dumps(manifest, ensure_ascii=False))
                finally:
                    for name in created:
                        try:
                            await client.drop(name)
                        except Exception:
                            pass
                    await client.aclose()
                    await provider.aclose()
                    await llm.aclose()

            asyncio.run(_run())
    finally:
        engine.dispose()
