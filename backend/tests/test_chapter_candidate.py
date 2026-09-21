import pytest
from app.domain.chapter_candidate import (
    ChapterCandidate,
    candidates_from_detection,
    validate_candidates,
    validate_span,
)
from app.domain.chapter_detect import ChapterShape, detect_chapter_structure
from app.domain.importing import ImportValidationError
from fastapi.testclient import TestClient

CHINESE = """第一章 开场
林深走进雨里。

第二章
鹿鸣从巷口传来。
"""

ENGLISH = """Chapter 1 Arrival
Rain.

Chapter 2 The Letter
A knock.
"""

UNTITLED = """林深把旧剑背好，没有再回头。
巷口的灯灭了一次。
"""


def test_validate_span_rejects_out_of_range_and_overlap() -> None:
    text = "abcdef"
    validate_span(text, 0, 3)
    with pytest.raises(ImportValidationError) as invalid:
        validate_span(text, 4, 4)
    assert invalid.value.code == "candidate_offset_invalid"
    with pytest.raises(ImportValidationError) as overflow:
        validate_span(text, 0, 9)
    assert overflow.value.code == "candidate_offset_invalid"

    first = ChapterCandidate(
        candidate_id="c1",
        sequence=1,
        original_label="第一章",
        title_candidate="",
        start_offset=0,
        end_offset=4,
        confidence=0.9,
        classification=ChapterShape.MULTI,
    )
    second = ChapterCandidate(
        candidate_id="c2",
        sequence=2,
        original_label="第二章",
        title_candidate="",
        start_offset=3,
        end_offset=6,
        confidence=0.9,
        classification=ChapterShape.MULTI,
    )
    with pytest.raises(ImportValidationError) as overlap:
        validate_candidates(text, (first, second))
    assert overlap.value.code == "candidate_offset_overlap"


def test_candidates_cover_normalized_offsets_for_chinese_english_untitled() -> None:
    chinese = detect_chapter_structure(CHINESE)
    chinese_candidates, _warnings = candidates_from_detection(CHINESE, chinese)
    assert chinese.classification == "multi"
    assert [item.sequence for item in chinese_candidates] == [1, 2]
    assert CHINESE[
        chinese_candidates[0].start_offset : chinese_candidates[0].end_offset
    ].startswith("第一章")
    assert "鹿鸣" in CHINESE[chinese_candidates[1].start_offset : chinese_candidates[1].end_offset]

    english = detect_chapter_structure(ENGLISH)
    english_candidates, _ = candidates_from_detection(ENGLISH, english)
    assert english_candidates[0].original_label.lower() == "chapter 1"
    assert english_candidates[0].title_candidate == "Arrival"

    untitled = detect_chapter_structure(UNTITLED)
    untitled_candidates, warnings = candidates_from_detection(UNTITLED, untitled)
    assert untitled.classification == "unstructured"
    assert untitled_candidates[0].start_offset == 0
    assert untitled_candidates[0].end_offset == len(UNTITLED)
    assert untitled_candidates[0].title_candidate == ""
    assert "no_chapter_boundary" in warnings


def test_detection_api_returns_typed_result_and_span(client: TestClient) -> None:
    created = client.post("/api/imports/paste", json={"text": CHINESE})
    assert created.status_code == 201
    source_id = created.json()["id"]
    checksum = created.json()["checksum"]

    detection = client.get(f"/api/imports/{source_id}/detection")
    assert detection.status_code == 200, detection.text
    body = detection.json()
    assert body["import_source_id"] == source_id
    assert body["checksum"] == checksum
    assert body["classification"] == "multi"
    assert len(body["candidates"]) == 2
    first = body["candidates"][0]
    assert first["candidate_id"] == "c1"
    assert first["original_label"] == "第一章"
    assert "林深" in first["preview_text"]
    assert "chapters" not in body

    span = client.get(
        f"/api/imports/{source_id}/span",
        params={"start": first["start_offset"], "end": first["end_offset"]},
    )
    assert span.status_code == 200
    assert span.json()["text"].startswith("第一章")

    bad = client.get(f"/api/imports/{source_id}/span", params={"start": 0, "end": 0})
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "candidate_offset_invalid"
