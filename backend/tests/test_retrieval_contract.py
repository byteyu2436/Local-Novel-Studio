from datetime import UTC, datetime

import pytest
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chapter_canon import add_draft_version
from app.domain.chunking import ChunkingProfile
from app.domain.retrieval import RetrievalContractError, evidence_from_chunk
from app.schemas.retrieval import (
    FILTER_PROFILE_VERSION,
    QUERY_PROFILE_VERSION,
    SCORING_PROFILE_VERSION,
    EvidenceProvenance,
    RetrievalEvidence,
    RetrievalQuery,
    result_for_query,
)
from app.services import catalog
from app.services.canon_chunks import ChunkError, build_chapter_chunks, list_canon_chunks
from pydantic import ValidationError


def _provenance(**overrides: object) -> EvidenceProvenance:
    values: dict[str, object] = {
        "novel_id": "novel",
        "chapter_id": "chapter",
        "chunk_id": "chunk",
        "source_version_id": "version",
        "source_version_kind": "ORIGINAL",
        "chunking_version": "chunking.v1",
        "text_checksum": "abc",
        "start_offset": 0,
        "end_offset": 2,
        "sequence": 1,
    }
    values.update(overrides)
    return EvidenceProvenance(**values)  # type: ignore[arg-type]


def _evidence(**overrides: object) -> RetrievalEvidence:
    provenance = overrides.pop("provenance", None)
    values: dict[str, object] = {
        "chunk_id": "chunk",
        "chapter_id": "chapter",
        "novel_id": "novel",
        "evidence_text": "正文",
        "provenance": provenance or _provenance(),
        "scoring_profile_version": SCORING_PROFILE_VERSION,
    }
    values.update(overrides)
    return RetrievalEvidence(**values)  # type: ignore[arg-type]


def test_query_roundtrip_keeps_profile_versions_and_excludes_draft() -> None:
    query = RetrievalQuery(
        novel_id="novel",
        chapter_goal="找到雨巷",
        characters=["林深"],
        locations=["雨巷"],
        previous_chapter_state="她还拿着伞。",
    )
    payload = query.model_dump(mode="json")
    restored = RetrievalQuery.model_validate(payload)
    assert restored == query
    assert payload["include_draft"] is False
    assert payload["corpus"] == "canon"
    assert payload["query_profile_version"] == QUERY_PROFILE_VERSION
    assert payload["filter_profile_version"] == FILTER_PROFILE_VERSION
    assert payload["scoring_profile_version"] == SCORING_PROFILE_VERSION
    assert payload["query_builder_version"] == "query-builder.v1"
    assert payload["semantic_query_text"] == ""
    assert payload["metadata_hints"]["characters"] == []
    assert payload["filters"]["canon_status"] == "active"
    assert "DRAFT" not in payload["filters"]["source_version_kinds"]
    with pytest.raises(ValidationError):
        RetrievalQuery(novel_id="novel", top_n=0)
    with pytest.raises(ValidationError):
        RetrievalQuery.model_validate({**payload, "milvus_expr": "novel_id == 1"})


def test_draft_query_must_be_marked_on_both_fields() -> None:
    with pytest.raises(ValidationError):
        RetrievalQuery(novel_id="novel", corpus="draft")
    with pytest.raises(ValidationError):
        RetrievalQuery(novel_id="novel", include_draft=True)
    draft = RetrievalQuery(novel_id="novel", corpus="draft", include_draft=True)
    assert draft.model_dump(mode="json")["include_draft"] is True
    assert draft.corpus == "draft"


def test_evidence_provenance_must_match_chunk_and_chapter() -> None:
    with pytest.raises(ValidationError):
        _evidence(chapter_id="other")
    with pytest.raises(ValidationError):
        _evidence(provenance=_provenance(chunk_id="other"))
    query = RetrievalQuery(novel_id="novel")
    result = result_for_query(query, [_evidence()])
    assert result.evidence[0].provenance.chapter_id == "chapter"
    assert result.scoring_profile_version == query.scoring_profile_version
    foreign = _provenance(novel_id="other")
    with pytest.raises(ValidationError):
        result_for_query(query, [_evidence(novel_id="other", provenance=foreign)])


def test_chunk_evidence_points_at_the_reader_chapter(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深走进雨里。")
            original = session.get(ChapterVersion, chapter.current_canon_version_id)
            draft = add_draft_version(
                chapter,
                body="草稿不能入库。",
                parent=original,
                created_at=datetime.now(UTC),
            )
            version = session.get(ChapterVersion, chapter.current_canon_version_id)
            build_chapter_chunks(
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
            chunk = list_canon_chunks(session, novel.id)[0]
            evidence = evidence_from_chunk(chunk, scoring_profile_version=SCORING_PROFILE_VERSION)
            assert evidence.chunk_id == chunk.id
            assert evidence.chapter_id == chapter.id
            assert evidence.provenance.chapter_id == chapter.id
            assert evidence.provenance.source_version_id == version.id
            assert evidence.provenance.source_version_kind == "ORIGINAL"
            assert evidence.evidence_text == chunk.text
            assert evidence.provenance.start_offset == chunk.start_offset
            assert evidence.provenance.end_offset == chunk.end_offset
            assert "草稿" not in evidence.evidence_text
            chunk.canon_status = "inactive"
            with pytest.raises(RetrievalContractError) as inactive:
                evidence_from_chunk(chunk, scoring_profile_version=SCORING_PROFILE_VERSION)
            assert inactive.value.code == "chunk_not_active"
            with pytest.raises(ChunkError) as draft_error:
                build_chapter_chunks(
                    session,
                    novel.id,
                    chapter,
                    draft,
                    ChunkingProfile(version="chunking.v1"),
                )
            assert draft_error.value.code == "draft_cannot_be_canon_chunk"
    finally:
        engine.dispose()
