import pytest
from app.domain import importing as importing_domain
from app.domain.importing import (
    ImportValidationError,
    normalize_imported_text,
    sha256_hex,
    validate_paste_text,
)
from app.services import importer as importer_service
from fastapi.testclient import TestClient
from sqlalchemy import text

MULTI_CHAPTER = "第一章 开场\n林深见鹿。\n\n第二章 转折\n夜雨不停。\n"
SINGLE_CHAPTER = "第一章\n只有一章的正文。"


def test_normalize_strips_bom_newlines_and_controls_without_rewriting_words() -> None:
    raw = "\ufeff第一章\r\n林深\x01见鹿。\r尾声"
    assert normalize_imported_text(raw) == "第一章\n林深见鹿。\n尾声"
    assert raw.startswith("\ufeff")
    assert "\r\n" in raw


def test_validate_paste_rejects_empty_too_large_and_nul() -> None:
    with pytest.raises(ImportValidationError, match="empty") as empty:
        validate_paste_text("   \n")
    assert empty.value.code == "import_empty"
    with pytest.raises(ImportValidationError) as large:
        validate_paste_text("字" * 10, max_chars=3)
    assert large.value.code == "import_too_large"
    with pytest.raises(ImportValidationError) as nul:
        validate_paste_text("ok\x00bad")
    assert nul.value.code == "import_invalid_characters"


def test_paste_import_creates_readable_raw_and_normalized(client: TestClient) -> None:
    raw = "\ufeff第一章\r\n林深见鹿。"
    created = client.post("/api/imports/paste", json={"text": raw})
    assert created.status_code == 201
    body = created.json()
    assert body["source_type"] == "paste"
    assert body["parse_status"] == "normalized"
    assert body["raw_text"] == raw
    assert body["normalized_text"] == "第一章\n林深见鹿。"
    assert body["checksum"] == sha256_hex(raw.encode())
    source_id = body["id"]

    listed = client.get(f"/api/imports/{source_id}")
    assert listed.status_code == 200
    assert listed.json()["raw_text"] == raw
    assert listed.json()["normalized_text"] == "第一章\n林深见鹿。"

    raw_body = client.get(f"/api/imports/{source_id}/raw")
    normalized_body = client.get(f"/api/imports/{source_id}/normalized")
    assert raw_body.json() == {"import_source_id": source_id, "kind": "raw", "text": raw}
    assert normalized_body.json() == {
        "import_source_id": source_id,
        "kind": "normalized",
        "text": "第一章\n林深见鹿。",
    }


@pytest.mark.parametrize("text", [SINGLE_CHAPTER, MULTI_CHAPTER])
def test_paste_import_accepts_single_and_multi_chapter_text(client: TestClient, text: str) -> None:
    response = client.post("/api/imports/paste", json={"text": text})
    assert response.status_code == 201
    payload = response.json()
    assert payload["source_type"] == "paste"
    assert payload["raw_text"] == text
    assert "chapters" not in payload


def test_paste_import_validation_errors_have_stable_codes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = client.post("/api/imports/paste", json={"text": "  "})
    assert empty.status_code == 400
    assert empty.json()["detail"]["code"] == "import_empty"

    nul = client.post("/api/imports/paste", json={"text": "有\x00零"})
    assert nul.status_code == 400
    assert nul.json()["detail"]["code"] == "import_invalid_characters"

    monkeypatch.setattr(importing_domain, "PASTE_MAX_CHARS", 8)
    too_large = client.post("/api/imports/paste", json={"text": "十二个汉字的内容啊"})
    assert too_large.status_code == 400
    assert too_large.json()["detail"]["code"] == "import_too_large"


def test_paste_import_does_not_create_chapter_tables(client: TestClient) -> None:
    response = client.post("/api/imports/paste", json={"text": SINGLE_CHAPTER})
    assert response.status_code == 201
    with client.app.state.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM chapters")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM novels")).scalar_one() == 0


def test_normalize_failure_keeps_original_snapshot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("normalize write failed")

    monkeypatch.setattr(importer_service, "upsert_normalized_text", boom)
    response = client.post("/api/imports/paste", json={"text": "第一章\n保留原文"})
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "import_normalize_failed"
    source_id = detail["import_source_id"]
    assert source_id

    raw = client.get(f"/api/imports/{source_id}/raw")
    assert raw.status_code == 200
    assert raw.json()["text"] == "第一章\n保留原文"
    meta = client.get(f"/api/imports/{source_id}")
    assert meta.json()["parse_status"] == "failed"
    assert meta.json()["raw_text"] == "第一章\n保留原文"
    assert meta.json()["normalized_text"] is None
    missing = client.get(f"/api/imports/{source_id}/normalized")
    assert missing.status_code == 409
    assert missing.json()["detail"]["code"] == "import_normalized_unavailable"
    with client.app.state.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM chapters")).scalar_one() == 0
