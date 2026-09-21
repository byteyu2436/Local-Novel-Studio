from datetime import UTC, datetime

from app.adapters.sqlite import session_scope
from app.api.reader import router as reader_router
from app.domain.chapter import VersionKind
from app.domain.chapter_canon import add_draft_version
from app.main import app
from app.services import catalog
from app.services.chapter_canon import persist_accepted_canon
from fastapi.testclient import TestClient


def _now():
    return datetime.now(UTC)


def test_reader_version_preview_is_read_only_and_owned(client: TestClient) -> None:
    assert all(
        getattr(route, "methods", None) == {"GET"}
        for route in reader_router.routes
        if hasattr(route, "methods")
    )

    ids: dict[str, str] = {}
    for session in session_scope(app.state.session_factory):
        novel = catalog.create_novel(session, "预览")
        chapter = catalog.create_chapter(session, novel.id, body="原文")
        other = catalog.create_chapter(session, novel.id, body="另一章")
        original = next(
            item for item in chapter.versions if item.version_kind == VersionKind.ORIGINAL.value
        )
        draft = add_draft_version(chapter, body="草稿正文", parent=original, created_at=_now())
        accepted = persist_accepted_canon(session, chapter, draft, created_at=_now())
        later = add_draft_version(chapter, body="新草稿", parent=accepted, created_at=_now())
        session.flush()
        ids.update(
            {
                "chapter": chapter.id,
                "other": other.id,
                "original": original.id,
                "accepted": accepted.id,
                "draft": later.id,
            }
        )

    original = client.get(
        f"/api/chapters/{ids['chapter']}/versions/{ids['original']}"
    )
    assert original.status_code == 200
    assert original.json()["version_kind"] == VersionKind.ORIGINAL.value
    assert original.json()["is_canon"] is False
    assert original.json()["body"] == "原文"

    accepted = client.get(
        f"/api/chapters/{ids['chapter']}/versions/{ids['accepted']}"
    )
    assert accepted.json()["version_kind"] == VersionKind.ACCEPTED.value
    assert accepted.json()["is_canon"] is True
    assert accepted.json()["body"] == "草稿正文"

    draft = client.get(f"/api/chapters/{ids['chapter']}/versions/{ids['draft']}")
    assert draft.json()["version_kind"] == VersionKind.DRAFT.value
    assert draft.json()["is_canon"] is False
    assert draft.json()["body"] == "新草稿"

    canon = client.get(f"/api/chapters/{ids['chapter']}")
    assert canon.json()["body"] == "草稿正文"
    assert canon.json()["is_canon"] is True

    crossed = client.get(f"/api/chapters/{ids['other']}/versions/{ids['draft']}")
    assert crossed.status_code == 404
    assert crossed.json()["detail"]["code"] == "version_chapter_mismatch"

    forbidden = client.post(f"/api/chapters/{ids['chapter']}", json={"body": "改写"})
    assert forbidden.status_code == 405
