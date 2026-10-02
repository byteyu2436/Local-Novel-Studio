from datetime import UTC, datetime

import pytest
from app.adapters.sqlite.chunks import CanonChunk
from app.domain.retrieval import evidence_from_chunk
from app.domain.scoring import RetrievalScoringProfile, apply_scoring, default_scoring_profile
from app.schemas.retrieval import SCORING_PROFILE_VERSION, RetrievalQuery, result_for_query


def _chunk(chunk_id: str, **overrides: object) -> CanonChunk:
    values: dict[str, object] = {
        "id": chunk_id,
        "novel_id": "novel",
        "chapter_id": f"chapter-{chunk_id}",
        "source_version_id": "version",
        "source_version_kind": "ORIGINAL",
        "chunk_index": 0,
        "sequence": 1,
        "chunk_type": "chapter",
        "text": chunk_id,
        "text_checksum": "abc",
        "start_offset": 0,
        "end_offset": len(chunk_id),
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


def _result(chunks: list[CanonChunk], query: RetrievalQuery, dense: list[float]):
    evidence = [
        evidence_from_chunk(
            chunk, scoring_profile_version=query.scoring_profile_version, dense_score=score
        )
        for chunk, score in zip(chunks, dense, strict=True)
    ]
    return result_for_query(query, evidence, embedding_profile_id="profile", index_version="index")


def test_fixed_candidates_rank_stably_and_explain_each_term() -> None:
    query = RetrievalQuery(
        novel_id="novel",
        characters=["林深"],
        locations=["雨巷"],
        events=["event-umbrella"],
        foreshadowing=["thread-umbrella"],
    )
    early = _chunk(
        "early",
        sequence=1,
        characters=["林深"],
        locations=["雨巷"],
        event_ids=["event-umbrella", "thread-umbrella"],
        importance="high",
    )
    late = _chunk("late", sequence=4, characters=["周晚"], importance="low")
    chunks = [late, early]
    result = _result(chunks, query, [0.5, 0.5])
    first = apply_scoring(result, query, chunks)
    second = apply_scoring(result, query, chunks)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [item.chunk_id for item in first.evidence] == ["early", "late"]
    assert first.scoring_profile_version == SCORING_PROFILE_VERSION
    winner = first.evidence[0]
    assert winner.final_score is not None
    assert winner.business_score is not None
    assert winner.scoring_profile_version == first.scoring_profile_version
    for code in (
        "dense",
        "character_match",
        "location_match",
        "event_match",
        "foreshadowing_match",
        "recency",
        "importance",
    ):
        assert code in winner.metadata
    assert any(reason.code == "character_match" for reason in winner.match_reasons)
    assert first.collection_name is None
    assert first.embedding_profile_id == "profile"


def test_character_event_recency_and_importance_each_move_rank() -> None:
    query = RetrievalQuery(
        novel_id="novel",
        characters=["林深"],
        events=["event-umbrella"],
    )
    matched = _chunk(
        "matched", sequence=1, characters=["林深"], event_ids=["event-umbrella"], importance="low"
    )
    recent = _chunk("recent", sequence=5, importance="low")
    important = _chunk("important", sequence=1, importance="high")
    chunks = [recent, important, matched]
    result = _result(chunks, query, [0.0, 0.0, 0.0])
    by_character = apply_scoring(
        result,
        query,
        chunks,
        RetrievalScoringProfile(
            character_match=1,
            location_match=0,
            event_match=0,
            foreshadowing_match=0,
            recency=0,
            importance=0,
            dense=0,
        ),
    )
    assert by_character.evidence[0].chunk_id == "matched"
    by_event = apply_scoring(
        result,
        query,
        chunks,
        RetrievalScoringProfile(
            event_match=1,
            character_match=0,
            location_match=0,
            foreshadowing_match=0,
            recency=0,
            importance=0,
            dense=0,
        ),
    )
    assert by_event.evidence[0].chunk_id == "matched"
    by_recency = apply_scoring(
        result,
        query,
        chunks,
        RetrievalScoringProfile(
            recency=1,
            character_match=0,
            location_match=0,
            event_match=0,
            foreshadowing_match=0,
            importance=0,
            dense=0,
        ),
    )
    assert [item.chunk_id for item in by_recency.evidence] == ["recent", "important", "matched"]
    assert by_recency.evidence[0].metadata["recency"] == "1.000000"
    by_importance = apply_scoring(
        result,
        query,
        chunks,
        RetrievalScoringProfile(
            importance=1,
            character_match=0,
            location_match=0,
            event_match=0,
            foreshadowing_match=0,
            recency=0,
            dense=0,
        ),
    )
    assert by_importance.evidence[0].chunk_id == "important"
    assert float(by_importance.evidence[0].metadata["importance"]) == 1


def test_weight_change_reorders_without_a_code_change() -> None:
    query = RetrievalQuery(novel_id="novel", characters=["林深"])
    named = _chunk("named", sequence=1, characters=["林深"], importance="low")
    recent = _chunk("recent", sequence=9, importance="low")
    chunks = [named, recent]
    result = _result(chunks, query, [0.0, 0.0])
    prefer_name = RetrievalScoringProfile(
        version="retrieval-scoring.names",
        character_match=1,
        recency=0,
        dense=0,
        location_match=0,
        event_match=0,
        foreshadowing_match=0,
        importance=0,
    )
    prefer_recent = RetrievalScoringProfile(
        version="retrieval-scoring.recent",
        character_match=0,
        recency=1,
        dense=0,
        location_match=0,
        event_match=0,
        foreshadowing_match=0,
        importance=0,
    )
    named_first = apply_scoring(result, query, chunks, prefer_name)
    recent_first = apply_scoring(result, query, chunks, prefer_recent)
    assert named_first.evidence[0].chunk_id == "named"
    assert named_first.scoring_profile_version == "retrieval-scoring.names"
    assert recent_first.evidence[0].chunk_id == "recent"
    assert recent_first.scoring_profile_version == "retrieval-scoring.recent"
    assert default_scoring_profile().version == SCORING_PROFILE_VERSION
    with pytest.raises(ValueError):
        RetrievalScoringProfile(dense=-1)
