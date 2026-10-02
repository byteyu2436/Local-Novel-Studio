from datetime import UTC, datetime

import pytest
from app.adapters.sqlite.chunks import CanonChunk
from app.domain.evidence_selection import EvidenceSelectionProfile, select_top_evidence
from app.domain.retrieval import evidence_from_chunk
from app.schemas.retrieval import SCORING_PROFILE_VERSION, RetrievalQuery, result_for_query


def _chunk(chunk_id: str, **overrides: object) -> CanonChunk:
    text = str(overrides.pop("text", chunk_id))
    values: dict[str, object] = {
        "id": chunk_id,
        "novel_id": "novel",
        "chapter_id": "chapter",
        "source_version_id": "version",
        "source_version_kind": "ORIGINAL",
        "chunk_index": 0,
        "sequence": 1,
        "chunk_type": "chapter",
        "text": text,
        "text_checksum": chunk_id,
        "start_offset": 0,
        "end_offset": max(len(text), 1),
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


def _ranked(chunks: list[CanonChunk], scores: list[float]):
    query = RetrievalQuery(novel_id="novel", chapter_goal="找伞")
    evidence = [
        evidence_from_chunk(
            chunk,
            scoring_profile_version=SCORING_PROFILE_VERSION,
            dense_score=score,
            business_score=0.1,
            final_score=score,
        )
        for chunk, score in zip(chunks, scores, strict=True)
    ]
    for item in evidence:
        item.metadata["dense"] = f"{item.dense_score:.6f}"
    return result_for_query(query, evidence, collection_name="novel_chunks")


def test_adjacent_overlap_keeps_one_span_and_its_scores() -> None:
    first = _chunk(
        "first",
        text="林深走进雨里。",
        chunk_index=0,
        start_offset=0,
        end_offset=100,
        text_checksum="aaa",
    )
    second = _chunk(
        "second",
        text="走进雨里看见伞。",
        chunk_index=1,
        start_offset=80,
        end_offset=160,
        text_checksum="bbb",
    )
    covered = _chunk(
        "covered",
        text="林深走进雨里看见伞。",
        chunk_index=4,
        start_offset=10,
        end_offset=90,
        text_checksum="ccc",
    )
    apart = _chunk(
        "apart",
        text="她放下旧伞。",
        chunk_index=6,
        start_offset=400,
        end_offset=480,
        text_checksum="ddd",
    )
    clone = _chunk(
        "clone",
        text="另一处相同。",
        chunk_index=8,
        start_offset=900,
        end_offset=980,
        text_checksum="aaa",
    )
    chunks = [second, covered, apart, clone, first]
    result = _ranked(chunks, [0.8, 0.7, 0.4, 0.3, 0.9])
    selected = select_top_evidence(result, chunks)
    assert [item.chunk_id for item in selected.result.evidence] == ["first", "apart"]
    kept = selected.result.evidence[0]
    assert kept.provenance.start_offset == 0
    assert kept.provenance.end_offset == 100
    assert kept.final_score == 0.9
    assert kept.metadata["dense"] == "0.900000"
    reasons = {item.evidence.chunk_id: item.reason for item in selected.rejected}
    assert reasons["second"] == "adjacent_overlap"
    assert reasons["covered"] == "overlap"
    assert reasons["clone"] == "duplicate_checksum"
    assert selected.rejected[0].kept_chunk_id == "first"
    assert selected.version == "evidence-selection.v1"


def test_same_text_in_another_chapter_is_kept() -> None:
    here = _chunk("here", chapter_id="chapter-a", text_checksum="same", text="同一句。")
    there = _chunk(
        "there",
        chapter_id="chapter-b",
        text_checksum="same",
        text="同一句。",
        start_offset=0,
        end_offset=20,
    )
    chunks = [here, there]
    selected = select_top_evidence(_ranked(chunks, [0.6, 0.5]), chunks)
    assert [item.chunk_id for item in selected.result.evidence] == ["here", "there"]
    assert selected.rejected == []


def test_top_candidates_trim_to_the_configured_evidence_count() -> None:
    chunks = [
        _chunk(
            f"c{index}",
            chapter_id=f"chapter-{index}",
            text_checksum=f"sum-{index}",
            text=f"正文{index}",
        )
        for index in range(10)
    ]
    scores = [1 - (index / 100) for index in range(10)]
    result = _ranked(chunks, scores)
    profile = EvidenceSelectionProfile(candidate_limit=8, evidence_limit=5)
    selected = select_top_evidence(result, chunks, profile)
    again = select_top_evidence(result, chunks, profile)
    assert [item.chunk_id for item in selected.result.evidence] == [
        f"c{index}" for index in range(5)
    ]
    assert [item.evidence.chunk_id for item in again.rejected] == [
        item.evidence.chunk_id for item in selected.rejected
    ]
    assert [item.reason for item in selected.rejected] == [
        "evidence_limit",
        "evidence_limit",
        "evidence_limit",
        "candidate_limit",
        "candidate_limit",
    ]
    assert selected.result.evidence[0].provenance.chapter_id == "chapter-0"
    tighter = select_top_evidence(
        result,
        chunks,
        EvidenceSelectionProfile(candidate_limit=8, evidence_limit=6),
    )
    assert len(tighter.result.evidence) == 6
    with pytest.raises(ValueError):
        EvidenceSelectionProfile(candidate_limit=4, evidence_limit=5)
