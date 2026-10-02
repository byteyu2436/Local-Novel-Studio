import asyncio

from app.adapters.embedding import FakeEmbeddingProvider
from app.adapters.sqlite import session_scope
from app.adapters.sqlite.models import ChapterVersion
from app.domain.embedding_profile import EmbeddingProfileSpec
from app.schemas.analysis import ChapterAnalysisPayload, ChapterSummary, StyleSignals
from app.services import catalog
from app.services.analysis import persist_chapter_analysis
from app.services.embedding_profiles import activate_embedding_profile
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


def test_initialization_and_debug_api(client) -> None:
    milvus, _entities, http_client = mock_milvus()
    provider = FakeEmbeddingProvider(dimension=8)
    client.app.state.embedding_provider = provider
    client.app.state.milvus_client = milvus
    factory = client.app.state.session_factory
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深住在城南。")
            version = session.get(ChapterVersion, chapter.current_canon_version_id)
            persist_chapter_analysis(
                session,
                chapter,
                version,
                payload=ChapterAnalysisPayload(
                    summary=ChapterSummary(synopsis="城南"),
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
            activate_embedding_profile(session, _spec())
            novel_id = novel.id
        missing = client.get("/api/novels/missing/initialization")
        assert missing.status_code == 404
        started = client.post(f"/api/novels/{novel_id}/initialize")
        assert started.status_code == 200
        body = started.json()
        assert body["ready"] is True
        assert body["state"] == "completed"
        gate = client.get(f"/api/novels/{novel_id}/writing-gate")
        assert gate.json()["ready"] is True
        quiet = client.post(
            f"/api/novels/{novel_id}/retrieval",
            json={"chapter_goal": "林深住在哪里"},
        )
        traced = client.post(
            f"/api/novels/{novel_id}/retrieval?debug=true",
            json={"chapter_goal": "林深住在哪里"},
        )
        assert quiet.status_code == 200
        assert traced.status_code == 200
        assert "trace" not in quiet.json()
        assert traced.json()["trace"]["final_evidence_ids"] == [
            item["chunk_id"] for item in quiet.json()["evidence"]
        ]
        paused = client.post(f"/api/novels/{novel_id}/initialization/pause")
        assert paused.status_code == 409
    finally:
        asyncio.run(http_client.aclose())
