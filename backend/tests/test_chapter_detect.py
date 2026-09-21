from app.domain.chapter_detect import (
    ChapterShape,
    RuleChapterDetector,
    chinese_int,
    detect_chapter_structure,
)
from app.services.chapter_detector import detect_import_chapters
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

MULTI = """第一章 开场
林深走进雨里。

第二章 夜访
鹿鸣从巷口传来。

第三章
天亮了。
"""

ENGLISH = """Chapter 1 Arrival
The rain did not stop.

Chapter 2 The Letter
Someone knocked twice.
"""

SINGLE = """第一章 独自上路
林深把旧剑背好，没有再回头。
巷口的灯灭了一次，又亮起来。
"""

UNSTRUCTURED = """林深把旧剑背好，没有再回头。
巷口的灯灭了一次，又亮起来。
他说第一章已经写完了，但这只是一句闲话。
"""


def test_chinese_int_parses_common_numerals() -> None:
    assert chinese_int("1") == 1
    assert chinese_int("12") == 12
    assert chinese_int("一") == 1
    assert chinese_int("十") == 10
    assert chinese_int("十一") == 11
    assert chinese_int("二十") == 20
    assert chinese_int("一百零一") == 101


def test_detect_is_deterministic() -> None:
    first = detect_chapter_structure(MULTI)
    second = detect_chapter_structure(MULTI)
    assert first == second
    assert RuleChapterDetector().detect(MULTI) == first


def test_multi_chinese_and_english_headings() -> None:
    chinese = detect_chapter_structure(MULTI)
    assert chinese.shape is ChapterShape.MULTI
    assert [item.sequence for item in chinese.headings] == [1, 2, 3]
    assert chinese.headings[0].original_label == "第一章"
    assert chinese.headings[0].title_candidate == "开场"
    assert chinese.headings[2].title_candidate == ""

    english = detect_chapter_structure(ENGLISH)
    assert english.shape is ChapterShape.MULTI
    assert [item.sequence for item in english.headings] == [1, 2]
    assert english.headings[0].original_label.lower() == "chapter 1"


def test_single_chapter_is_not_force_split() -> None:
    result = detect_chapter_structure(SINGLE)
    assert result.shape is ChapterShape.SINGLE
    assert len(result.headings) == 1
    assert result.headings[0].title_candidate == "独自上路"


def test_unstructured_prose_is_not_fake_sliced() -> None:
    result = detect_chapter_structure(UNSTRUCTURED)
    assert result.shape is ChapterShape.UNSTRUCTURED
    assert result.headings == ()
    assert "no_chapter_boundary" in result.warnings


def test_inline_chapter_mention_is_not_a_heading() -> None:
    text = "他在信里写道：第一章已经写完了，明天再寄。"
    result = detect_chapter_structure(text)
    assert result.shape is ChapterShape.UNSTRUCTURED
    assert result.headings == ()


def test_section_heading_is_not_a_chapter() -> None:
    text = "第一节 早餐\n林深没有出门。\n第二节 午后"
    result = detect_chapter_structure(text)
    assert result.shape is ChapterShape.UNSTRUCTURED


def test_arabic_and_hui_headings() -> None:
    text = "第1章 雨\n正文\n第2回 晴\n另一段"
    result = detect_chapter_structure(text)
    assert result.shape is ChapterShape.MULTI
    assert [item.sequence for item in result.headings] == [1, 2]
    assert result.headings[1].original_label == "第2回"


def test_detect_import_source_does_not_create_chapters(client: TestClient) -> None:
    created = client.post("/api/imports/paste", json={"text": MULTI})
    assert created.status_code == 201
    source_id = created.json()["id"]
    session: Session = client.app.state.session_factory()
    try:
        result = detect_import_chapters(session, source_id)
        assert result.import_source_id == source_id
        assert result.classification.value == "multi"
        assert len(result.candidates) == 3
        assert inspect(client.app.state.engine).has_table("chapters") is False
        count = session.execute(text("SELECT COUNT(*) FROM import_sources")).scalar_one()
        assert count == 1
    finally:
        session.close()
