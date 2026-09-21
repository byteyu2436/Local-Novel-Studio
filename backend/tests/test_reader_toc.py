from uuid import uuid4

from app.adapters.sqlite import session_scope
from app.domain.chapter import TitleSource, VersionKind
from app.domain.chapter_canon import add_draft_version
from app.main import app
from app.services import catalog
from app.services.chapter_canon import persist_accepted_canon
from fastapi.testclient import TestClient


def _seed_eighteen(client: TestClient) -> tuple[str, list[str]]:
    from datetime import UTC, datetime

    factory = app.state.session_factory
    now = datetime.now(UTC)
    chapter_ids: list[str] = []
    novel_id = ""
    for session in session_scope(factory):
        novel = catalog.create_novel(session, "十八章样例")
        novel_id = novel.id
        for index in range(1, 19):
            original_title = "开场" if index == 1 else ""
            chapter = catalog.create_chapter(
                session,
                novel.id,
                body=f"第{index}章正文",
                original_label=f"第{index}章" if index != 5 else "",
                original_title=original_title,
            )
            chapter_ids.append(chapter.id)
            if index == 2:
                original = next(
                    item
                    for item in chapter.versions
                    if item.version_kind == VersionKind.ORIGINAL.value
                )
                add_draft_version(chapter, body="未接受草稿", parent=original, created_at=now)
            if index == 3:
                original = next(
                    item
                    for item in chapter.versions
                    if item.version_kind == VersionKind.ORIGINAL.value
                )
                draft = add_draft_version(chapter, body="已接受稿", parent=original, created_at=now)
                persist_accepted_canon(session, chapter, draft, created_at=now)
    return novel_id, chapter_ids


def test_reader_toc_orders_eighteen_chapters_and_states(client: TestClient) -> None:
    novel_id, chapter_ids = _seed_eighteen(client)
    missing = client.get(f"/api/novels/{uuid4()}/chapters")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "novel_not_found"

    empty_id = ""
    for session in session_scope(app.state.session_factory):
        empty_id = catalog.create_novel(session, "空小说").id
    empty_toc = client.get(f"/api/novels/{empty_id}/chapters")
    assert empty_toc.status_code == 200
    assert empty_toc.json()["chapters"] == []

    toc = client.get(f"/api/novels/{novel_id}/chapters")
    assert toc.status_code == 200, toc.text
    body = toc.json()
    assert body["novel_title"] == "十八章样例"
    assert len(body["chapters"]) == 18
    assert [item["sequence"] for item in body["chapters"]] == list(range(1, 19))
    assert [item["chapter_id"] for item in body["chapters"]] == chapter_ids
    assert all("body" not in item for item in body["chapters"])
    first, second, third, fifth = (
        body["chapters"][0],
        body["chapters"][1],
        body["chapters"][2],
        body["chapters"][4],
    )
    assert first["canon_kind"] == VersionKind.ORIGINAL.value
    assert first["has_draft"] is False
    assert first["display_title"] == "第1章 开场"
    assert second["has_draft"] is True
    assert second["canon_kind"] == VersionKind.ORIGINAL.value
    assert third["canon_kind"] == VersionKind.ACCEPTED.value
    assert third["has_draft"] is True
    assert fifth["original_label"] == ""
    assert fifth["display_title"] == "第5章"
    assert fifth["title_source"] == TitleSource.FALLBACK.value

    for session in session_scope(app.state.session_factory):
        catalog.reorder_chapters(session, novel_id, list(reversed(chapter_ids)))
    reordered = client.get(f"/api/novels/{novel_id}/chapters")
    assert [item["chapter_id"] for item in reordered.json()["chapters"]] == list(
        reversed(chapter_ids)
    )
    assert [item["sequence"] for item in reordered.json()["chapters"]] == list(range(1, 19))
