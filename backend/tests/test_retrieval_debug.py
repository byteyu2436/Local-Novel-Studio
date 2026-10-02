import asyncio
import logging
from datetime import UTC, datetime

from app.adapters.embedding import FakeEmbeddingProvider
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chapter_canon import add_draft_version
from app.domain.embedding_profile import EmbeddingProfileSpec
from app.schemas.retrieval import QueryBuilderInput
from app.services import catalog
from app.services.embedding_profiles import activate_embedding_profile
from app.services.index_rebuild import rebuild_canon_index
from app.services.retrieval import retrieve_evidence
from app.services.retrieval_debug import retrieval_log_payload
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


def _ids(report) -> list[str]:
    return [item.chunk_id for item in report.result.evidence]


def test_debug_does_not_change_evidence_and_hides_prose_from_logs(caplog) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    client, entities, http_client = mock_milvus()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            other = catalog.create_novel(session, "别的故事")
            rain = catalog.create_chapter(session, novel.id, body="林深走进雨巷，旧伞还在。")
            catalog.create_chapter(session, novel.id, body="咖啡馆里没有人提起那把伞。")
            catalog.create_chapter(session, other.id, body="另一本书的林深。")
            version = session.get(ChapterVersion, rain.current_canon_version_id)
            add_draft_version(
                rain,
                body="草稿里的秘密句子不能被检索。",
                parent=version,
                created_at=datetime.now(UTC),
            )
            activate_embedding_profile(session, _spec())
            provider = FakeEmbeddingProvider(dimension=8)

            async def _rebuild(session=session, provider=provider):
                return await rebuild_canon_index(session, client, provider)

            asyncio.run(_rebuild())
            context = QueryBuilderInput(novel_id=novel.id, chapter_goal="林深的旧伞")

            async def _once(debug: bool, session=session, provider=provider, context=context):
                return await retrieve_evidence(session, client, provider, context, debug=debug)

            plain = asyncio.run(_once(False))
            traced = asyncio.run(_once(True))
            assert _ids(plain) == _ids(traced)
            assert [item.final_score for item in plain.result.evidence] == [
                item.final_score for item in traced.result.evidence
            ]
            assert plain.trace is None
            assert traced.trace is not None
            assert traced.trace.final_evidence_ids == _ids(traced)
            assert traced.trace.query.novel_id == novel.id
            assert "另一本书" not in {item.novel_id for item in traced.result.evidence}
            joined = " ".join(entities[traced.result.collection_name].keys())
            assert "草稿里的秘密句子" not in str(entities)
            assert joined
            with caplog.at_level(logging.INFO, logger="app.retrieval"):
                payload = retrieval_log_payload(traced.result, elapsed_ms=traced.elapsed_ms)
            assert "林深走进雨巷" not in caplog.text
            assert "embedding" not in payload
            assert "林深走进雨巷" not in str(payload)
    finally:
        engine.dispose()
        asyncio.run(http_client.aclose())


def test_stale_checksum_is_filtered_in_the_trace() -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    client, entities, http_client = mock_milvus()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            catalog.create_chapter(session, novel.id, body="林深把旧伞留在雨巷。")
            activate_embedding_profile(session, _spec())
            provider = FakeEmbeddingProvider(dimension=8)

            async def _rebuild(session=session, provider=provider):
                return await rebuild_canon_index(session, client, provider)

            report = asyncio.run(_rebuild())
            stored = next(iter(entities[report.collection_name].values()))
            stored["text_hash"] = "stale"

            async def _debug(session=session, provider=provider, novel_id=novel.id):
                return await retrieve_evidence(
                    session,
                    client,
                    provider,
                    QueryBuilderInput(novel_id=novel_id, chapter_goal="旧伞"),
                    debug=True,
                )

            traced = asyncio.run(_debug())
            filtered = [item for item in traced.trace.candidates if item.status == "filtered"]
            assert filtered
            assert filtered[0].reason == "stale_chunk"
            assert traced.result.evidence == []
    finally:
        engine.dispose()
        asyncio.run(http_client.aclose())
