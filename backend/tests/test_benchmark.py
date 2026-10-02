import json

import pytest
from app.eval.benchmark import (
    BenchmarkQuery,
    GoldSource,
    load_benchmark_dataset,
    recall_at_k,
    score_query,
    source_hit,
)
from app.eval.benchmark_report import compare_reports, result_payload, write_benchmark_report
from pydantic import ValidationError


def test_dataset_loads_six_categories_and_rejects_broken_gold(tmp_path) -> None:
    dataset = load_benchmark_dataset()
    assert dataset.version == "retrieval-benchmark.v1"
    assert {item.category for item in dataset.queries} == {
        "character",
        "relationship",
        "event",
        "location",
        "foreshadowing",
        "timeline",
    }
    broken = {
        **dataset.model_dump(),
        "queries": [
            {
                **dataset.queries[0].model_dump(),
                "gold": [
                    {
                        "chapter_sequence": 1,
                        "start_offset": 0,
                        "end_offset": 2,
                        "excerpt": "不在正文里",
                    }
                ],
            }
        ],
    }
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="gold excerpt"):
        load_benchmark_dataset(path)
    with pytest.raises(ValidationError):
        BenchmarkQuery.model_validate({**dataset.queries[0].model_dump(), "category": "invented"})


def test_recall_and_source_hit_cover_empty_and_partial_gold() -> None:
    assert recall_at_k([1, 2], [], 10) == 0
    assert recall_at_k([1, 2], [1], 10) == 0.5
    assert recall_at_k([1], [1, 2], 5) == 1
    gold = [GoldSource(chapter_sequence=3, start_offset=0, end_offset=4, excerpt="旧伞")]
    assert source_hit(gold, [{"chapter_sequence": 3, "start_offset": 2, "end_offset": 8}])
    assert not source_hit(gold, [{"chapter_sequence": 4, "start_offset": 0, "end_offset": 8}])
    dataset = load_benchmark_dataset()
    missed = score_query(dataset.queries[0], [])
    assert missed.recall_at_10 == 0
    assert missed.missing_chapters == [1]
    assert not missed.source_hit


def test_report_omits_chapter_text_and_warns_on_profile_mismatch(tmp_path) -> None:
    dataset = load_benchmark_dataset()
    from app.eval.benchmark import summarize

    result = summarize(
        dataset,
        [score_query(query, []) for query in dataset.queries],
        chunking_version="chunking.v1",
        embedding_profile_id="profile-a",
        index_version="index-a",
        scoring_profile_version="retrieval-scoring.v1",
        collection_name="novel_chunks_a",
    )
    payload = result_payload(result)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "林深住在城南" not in encoded
    json_path, md_path = write_benchmark_report(result, tmp_path)
    assert "林深住在城南" not in json_path.read_text(encoding="utf-8")
    assert "Recall@5" in md_path.read_text(encoding="utf-8")
    same = compare_reports(payload, payload)
    assert same["comparable"] is True
    drifted = compare_reports(payload, {**payload, "index_version": "index-b", "recall_at_5": 0.2})
    assert drifted["comparable"] is False
    assert drifted["warning"] == "profile_mismatch"
    assert drifted["deltas"]["recall_at_5"] == pytest.approx(0.2)
