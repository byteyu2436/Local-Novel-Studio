from datetime import UTC, datetime
from uuid import uuid4

from app.adapters.sqlite import session_scope
from app.domain.chapter import VersionKind
from app.domain.chapter_canon import add_draft_version
from app.main import app
from app.services import catalog
from app.services.chapter_canon import persist_accepted_canon
from fastapi.testclient import TestClient


def _now():
    return datetime.now(UTC)


def test_canon_read_navigation_and_draft_isolation(client: TestClient) -> None:
    ids: list[str] = []
    for session in session_scope(app.state.session_factory):
        novel = catalog.create_novel(session, "导航")
        first = catalog.create_chapter(
            session, novel.id, body="第一章正文", original_label="第一章"
        )
        middle = catalog.create_chapter(session, novel.id, body="第二章原文")
        last = catalog.create_chapter(session, novel.id, body="第三章正文")
        original = next(
            item for item in middle.versions if item.version_kind == VersionKind.ORIGINAL.value
        )
        draft = add_draft_version(middle, body="已接受正文", parent=original, created_at=_now())
        persist_accepted_canon(session, middle, draft, created_at=_now())
        later = add_draft_version(middle, body="未接受草稿", parent=None, created_at=_now())
        session.flush()
        ids.extend([first.id, middle.id, last.id, later.id])

    first_id, middle_id, last_id, draft_id = ids
    missing = client.get(f"/api/chapters/{uuid4()}")
    assert missing.status_code == 404

    first = client.get(f"/api/chapters/{first_id}")
    assert first.status_code == 200
    assert first.json()["body"] == "第一章正文"
    assert first.json()["version_kind"] == VersionKind.ORIGINAL.value
    assert first.json()["is_canon"] is True
    assert first.json()["previous"] is None
    assert first.json()["next"]["chapter_id"] == middle_id
    assert first.json()["display_title"] == "第一章"

    middle = client.get(f"/api/chapters/{middle_id}")
    assert middle.status_code == 200
    assert middle.json()["body"] == "已接受正文"
    assert middle.json()["version_kind"] == VersionKind.ACCEPTED.value
    assert middle.json()["has_draft"] is True
    assert middle.json()["body"] != "未接受草稿"
    assert middle.json()["previous"]["chapter_id"] == first_id
    assert middle.json()["next"]["chapter_id"] == last_id
    assert draft_id not in {middle.json()["version_id"]}

    last = client.get(f"/api/chapters/{last_id}")
    assert last.json()["next"] is None
    assert last.json()["previous"]["chapter_id"] == middle_id
    untitled = last.json()["display_title"]
    assert untitled == "第3章"
