import pytest
from app.adapters.sqlite.engine import create_sqlite_engine
from app.adapters.sqlite.models import Chapter, ChapterVersion, Novel
from app.domain.chapter import VersionKind
from app.services import catalog as catalog_service
from app.settings import get_settings
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

CHINESE = """第一章 开场
林深走进雨里。

第二章
鹿鸣从巷口传来。
"""

UNTITLED = """林深把旧剑背好，没有再回头。
巷口的灯灭了一次。
"""


def _chapter_count() -> int:
    engine = create_sqlite_engine(get_settings())
    try:
        with Session(engine) as session:
            return int(session.scalar(select(func.count()).select_from(Chapter)) or 0)
    finally:
        engine.dispose()


def _detection_payload(client: TestClient, text: str) -> tuple[str, dict]:
    created = client.post("/api/imports/paste", json={"text": text})
    assert created.status_code == 201
    source_id = created.json()["id"]
    detection = client.get(f"/api/imports/{source_id}/detection")
    assert detection.status_code == 200
    return source_id, detection.json()


def test_detection_does_not_create_chapters(client: TestClient) -> None:
    _source_id, body = _detection_payload(client, CHINESE)
    assert "chapters" not in body
    assert _chapter_count() == 0


def test_confirm_creates_new_novel_and_is_idempotent(client: TestClient) -> None:
    source_id, detection = _detection_payload(client, CHINESE)
    payload = {
        "checksum": detection["checksum"],
        "destination": "new_novel",
        "novel_title": "雨巷",
        "classification": detection["classification"],
        "candidates": detection["candidates"],
    }
    first = client.post(f"/api/imports/{source_id}/confirm", json=payload)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["idempotent"] is False
    assert body["novel_title"] == "雨巷"
    assert len(body["chapters"]) == 2
    assert [item["sequence"] for item in body["chapters"]] == [1, 2]
    assert body["chapters"][0]["display_title"] == "第一章 开场"
    assert _chapter_count() == 2

    replay = client.post(f"/api/imports/{source_id}/confirm", json=payload)
    assert replay.status_code == 200
    assert replay.json()["idempotent"] is True
    assert replay.json()["novel_id"] == body["novel_id"]
    assert [item["chapter_id"] for item in replay.json()["chapters"]] == [
        item["chapter_id"] for item in body["chapters"]
    ]
    assert _chapter_count() == 2


def test_confirm_append_and_provenance(client: TestClient) -> None:
    first_id, first_detection = _detection_payload(client, "第一章\n只有一章。")
    created = client.post(
        f"/api/imports/{first_id}/confirm",
        json={
            "checksum": first_detection["checksum"],
            "destination": "new_novel",
            "novel_title": "合集",
            "classification": first_detection["classification"],
            "candidates": first_detection["candidates"],
        },
    )
    assert created.status_code == 201
    novel_id = created.json()["novel_id"]

    second_id, second_detection = _detection_payload(client, CHINESE)
    appended = client.post(
        f"/api/imports/{second_id}/confirm",
        json={
            "checksum": second_detection["checksum"],
            "destination": "append",
            "novel_id": novel_id,
            "classification": second_detection["classification"],
            "candidates": second_detection["candidates"],
        },
    )
    assert appended.status_code == 201, appended.text
    sequences = [item["sequence"] for item in appended.json()["chapters"]]
    assert sequences == [2, 3]
    assert _chapter_count() == 3
    chapter_id = appended.json()["chapters"][0]["chapter_id"]
    engine = create_sqlite_engine(get_settings())
    try:
        with Session(engine) as session:
            provenance = catalog_service.chapter_provenance(session, chapter_id)
            assert provenance.import_source_id == second_id
            assert provenance.start_offset == second_detection["candidates"][0]["start_offset"]
            original = session.get(ChapterVersion, provenance.original_version_id)
            assert original is not None
            assert original.version_kind == VersionKind.ORIGINAL.value
    finally:
        engine.dispose()


def test_confirm_rolls_back_partial_chapters(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id, detection = _detection_payload(client, CHINESE)
    calls = {"n": 0}
    original = catalog_service.create_chapter

    def boom(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return original(*args, **kwargs)

    monkeypatch.setattr("app.services.import_confirm.create_chapter", boom)
    with pytest.raises(RuntimeError, match="boom"):
        client.post(
            f"/api/imports/{source_id}/confirm",
            json={
                "checksum": detection["checksum"],
                "destination": "new_novel",
                "novel_title": "失败",
                "classification": detection["classification"],
                "candidates": detection["candidates"],
            },
        )
    assert _chapter_count() == 0
    novels = create_sqlite_engine(get_settings())
    try:
        with Session(novels) as session:
            assert session.scalar(select(func.count()).select_from(Novel)) == 0
    finally:
        novels.dispose()


def test_confirm_unstructured_requires_ack(client: TestClient) -> None:
    source_id, detection = _detection_payload(client, UNTITLED)
    blocked = client.post(
        f"/api/imports/{source_id}/confirm",
        json={
            "checksum": detection["checksum"],
            "destination": "new_novel",
            "classification": "unstructured",
            "candidates": detection["candidates"],
        },
    )
    assert blocked.status_code == 400
    assert blocked.json()["detail"]["code"] == "unstructured_ack_required"
    assert _chapter_count() == 0
    ok = client.post(
        f"/api/imports/{source_id}/confirm",
        json={
            "checksum": detection["checksum"],
            "destination": "new_novel",
            "unstructured_ack": True,
            "classification": "unstructured",
            "candidates": detection["candidates"],
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["chapters"][0]["display_title"] == "第1章"
