"""v0.2.0 DoD: Paste/TXT → detect → confirm → Reader TOC/body/prev-next."""

from datetime import UTC, datetime

from app.adapters.sqlite import session_scope
from app.domain.chapter import VersionKind
from app.domain.chapter_canon import add_draft_version
from app.main import app
from app.services import catalog
from app.services.chapter_canon import persist_accepted_canon
from fastapi.testclient import TestClient

EIGHTEEN = "\n\n".join(f"第{index}章 标题{index}\n正文{index}。" for index in range(1, 19))
SINGLE = "第一章 开场\n只有一章。"
UNTITLED = "林深把旧剑背好，没有再回头。巷口的灯灭了一次。"


def _confirm(client: TestClient, text: str, **extra) -> dict:
    created = client.post("/api/imports/paste", json={"text": text})
    assert created.status_code == 201
    source_id = created.json()["id"]
    assert "chapters" not in created.json()
    detection = client.get(f"/api/imports/{source_id}/detection")
    assert detection.status_code == 200
    payload = {
        "checksum": detection.json()["checksum"],
        "destination": extra.get("destination", "new_novel"),
        "novel_title": extra.get("novel_title", "十八章样例"),
        "classification": detection.json()["classification"],
        "candidates": detection.json()["candidates"],
        "unstructured_ack": extra.get("unstructured_ack", False),
    }
    if "novel_id" in extra:
        payload["novel_id"] = extra["novel_id"]
    confirm = client.post(f"/api/imports/{source_id}/confirm", json=payload)
    return {
        "source_id": source_id,
        "detection": detection.json(),
        "confirm": confirm,
        "before_confirm_toc": client.get("/api/novels/missing/chapters").status_code,
    }


def test_v02_paste_txt_single_multi_unstructured_and_reader_nav(client: TestClient) -> None:
    """DoD: confirm-before-chapters, Paste/TXT, 18-chapter Reader, Draft vs Canon."""

    pasted = _confirm(client, EIGHTEEN)
    first = pasted["confirm"]
    assert first.status_code == 201, first.text
    novel_id = first.json()["novel_id"]
    chapters = first.json()["chapters"]
    assert len(chapters) == 18
    assert chapters[0]["sequence"] == 1

    toc = client.get(f"/api/novels/{novel_id}/chapters")
    assert toc.status_code == 200
    assert [item["sequence"] for item in toc.json()["chapters"]] == list(range(1, 19))
    first_id = toc.json()["chapters"][0]["chapter_id"]
    last_id = toc.json()["chapters"][-1]["chapter_id"]
    body = client.get(f"/api/chapters/{first_id}")
    assert body.status_code == 200
    assert body.json()["is_canon"] is True
    assert body.json()["version_kind"] == VersionKind.ORIGINAL.value
    assert body.json()["previous"] is None
    assert body.json()["next"]["chapter_id"] == toc.json()["chapters"][1]["chapter_id"]
    last = client.get(f"/api/chapters/{last_id}")
    assert last.json()["next"] is None
    assert "正文18" in last.json()["body"]

    now = datetime.now(UTC)
    draft_id = ""
    for session in session_scope(app.state.session_factory):
        chapter = catalog.require_chapter(session, first_id)
        original = next(
            item
            for item in chapter.versions
            if item.version_kind == VersionKind.ORIGINAL.value
        )
        draft = add_draft_version(chapter, body="草稿预览", parent=original, created_at=now)
        session.flush()
        draft_id = draft.id
        persist_accepted_canon(session, chapter, draft, created_at=now)
        later = add_draft_version(chapter, body="未接受草稿", parent=None, created_at=now)
        session.flush()
        draft_id = later.id
    canon = client.get(f"/api/chapters/{first_id}")
    assert canon.json()["body"] == "草稿预览"
    assert canon.json()["is_canon"] is True
    preview = client.get(f"/api/chapters/{first_id}/versions/{draft_id}")
    assert preview.json()["is_canon"] is False
    assert preview.json()["body"] == "未接受草稿"

    single = _confirm(client, SINGLE, novel_title="单章")
    assert single["confirm"].status_code == 201
    assert len(single["confirm"].json()["chapters"]) == 1

    unstructured = _confirm(client, UNTITLED, unstructured_ack=True, novel_title="无结构")
    assert unstructured["detection"]["classification"] == "unstructured"
    assert unstructured["confirm"].status_code == 201

    payload = EIGHTEEN.encode("gbk")
    txt = client.post(
        "/api/imports/txt",
        files={"file": ("eighteen.txt", payload, "text/plain")},
    )
    assert txt.status_code == 201
    assert txt.json()["detected_encoding"] == "gbk"
    detection = client.get(f"/api/imports/{txt.json()['id']}/detection")
    assert detection.status_code == 200
    assert len(detection.json()["candidates"]) == 18
    confirmed = client.post(
        f"/api/imports/{txt.json()['id']}/confirm",
        json={
            "checksum": detection.json()["checksum"],
            "destination": "new_novel",
            "novel_title": "GBK十八章",
            "classification": detection.json()["classification"],
            "candidates": detection.json()["candidates"],
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    toc = client.get(f"/api/novels/{confirmed.json()['novel_id']}/chapters")
    assert len(toc.json()["chapters"]) == 18
    utf8 = client.post(
        "/api/imports/txt",
        files={"file": ("eighteen-utf8.txt", EIGHTEEN.encode("utf-8"), "text/plain")},
    )
    assert utf8.status_code == 201
    utf8_detection = client.get(f"/api/imports/{utf8.json()['id']}/detection")
    utf8_confirm = client.post(
        f"/api/imports/{utf8.json()['id']}/confirm",
        json={
            "checksum": utf8_detection.json()["checksum"],
            "destination": "new_novel",
            "novel_title": "UTF8十八章",
            "classification": utf8_detection.json()["classification"],
            "candidates": utf8_detection.json()["candidates"],
        },
    )
    assert utf8_confirm.status_code == 201
    gb18030 = client.post(
        "/api/imports/txt",
        files={"file": ("single-gb18030.txt", SINGLE.encode("gb18030"), "text/plain")},
    )
    assert gb18030.status_code == 201
    gb_detection = client.get(f"/api/imports/{gb18030.json()['id']}/detection")
    gb_confirm = client.post(
        f"/api/imports/{gb18030.json()['id']}/confirm",
        json={
            "checksum": gb_detection.json()["checksum"],
            "destination": "new_novel",
            "novel_title": "GB18030单章",
            "classification": gb_detection.json()["classification"],
            "candidates": gb_detection.json()["candidates"],
        },
    )
    assert gb_confirm.status_code == 201
    assert len(gb_confirm.json()["chapters"]) == 1
