import pytest
from app.domain.importing import sha256_hex
from app.services import importer as importer_service
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

SAMPLE = "第一章 开场\r\n林深时见鹿。"


def _post_txt(
    client: TestClient,
    payload: bytes,
    *,
    filename: str = "novel.txt",
    encoding: str | None = None,
    path: str = "/api/imports/txt",
):
    data = {"encoding": encoding} if encoding is not None else None
    return client.post(
        path,
        files={"file": (filename, payload, "text/plain")},
        data=data,
    )


@pytest.mark.parametrize(
    ("payload", "encoding"),
    [
        (SAMPLE.encode("utf-8"), "utf-8"),
        (b"\xef\xbb\xbf" + SAMPLE.encode("utf-8"), "utf-8"),
        (SAMPLE.encode("gbk"), "gbk"),
    ],
)
def test_txt_import_persists_original_file_and_normalized_text(
    client: TestClient, payload: bytes, encoding: str
) -> None:
    response = _post_txt(client, payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_type"] == "txt"
    assert body["parse_status"] == "normalized"
    assert body["detected_encoding"] == encoding
    assert body["checksum"] == sha256_hex(payload)
    assert body["original_filename"] == "novel.txt"
    assert body["raw_text"] is None
    assert "林深时见鹿" in (body["normalized_text"] or "")
    assert "chapters" not in body

    source_id = body["id"]
    stored = client.app.state.settings.data_dir / body["original_storage_path"]
    assert stored.is_file()
    assert stored.read_bytes() == payload

    downloaded = client.get(f"/api/imports/{source_id}/file")
    assert downloaded.status_code == 200
    assert downloaded.content == payload

    normalized = client.get(f"/api/imports/{source_id}/normalized")
    assert normalized.status_code == 200
    assert stored.read_bytes() == payload


def test_txt_import_override_decodes_gbk(client: TestClient) -> None:
    payload = SAMPLE.encode("gbk")
    response = _post_txt(client, payload, encoding="gbk")
    assert response.status_code == 201
    assert response.json()["detected_encoding"] == "gbk"
    assert response.json()["encoding_uncertain"] is False


def test_txt_preview_decodes_without_persisting(client: TestClient, isolated_data_dir) -> None:
    payload = SAMPLE.encode("gbk")
    response = _post_txt(client, payload, path="/api/imports/txt/preview")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["detected_encoding"] == "gbk"
    assert body["original_filename"] == "novel.txt"
    assert body["raw_byte_size"] == len(payload)
    assert "林深时见鹿" in body["preview_text"]
    assert body["preview_truncated"] is False
    imports_dir = isolated_data_dir / "imports"
    leftovers = list(imports_dir.rglob("*")) if imports_dir.exists() else []
    assert leftovers == []
    with client.app.state.engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM import_sources")).scalar_one()
    assert count == 0


def test_txt_preview_override_and_reject_non_txt(client: TestClient) -> None:
    payload = SAMPLE.encode("gbk")
    ok = _post_txt(client, payload, encoding="gbk", path="/api/imports/txt/preview")
    assert ok.status_code == 200
    assert ok.json()["detected_encoding"] == "gbk"
    assert ok.json()["encoding_uncertain"] is False

    markdown = _post_txt(
        client, SAMPLE.encode(), filename="notes.md", path="/api/imports/txt/preview"
    )
    assert markdown.status_code == 400
    assert markdown.json()["detail"]["code"] == "txt_unsupported_type"


def test_txt_import_rejects_non_txt_and_binary_without_files(
    client: TestClient, isolated_data_dir
) -> None:
    markdown = _post_txt(client, SAMPLE.encode(), filename="notes.md")
    assert markdown.status_code == 400
    assert markdown.json()["detail"]["code"] == "txt_unsupported_type"

    binary = _post_txt(client, b"\x00PNG" + b"\xff" * 16)
    assert binary.status_code == 400
    assert binary.json()["detail"]["code"] == "txt_binary"

    imports_dir = isolated_data_dir / "imports"
    leftovers = list(imports_dir.rglob("*")) if imports_dir.exists() else []
    assert not any(path.is_file() for path in leftovers)
    tables = inspect(client.app.state.engine).get_table_names()
    assert "chapters" not in tables
    with client.app.state.engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM import_sources")).scalar_one()
    assert count == 0


def test_txt_import_write_failure_leaves_no_half_state(
    client: TestClient, isolated_data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(importer_service, "write_original_txt", boom)
    response = _post_txt(client, SAMPLE.encode())
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "txt_persist_failed"
    with client.app.state.engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM import_sources")).scalar_one()
    assert count == 0
    imports_dir = isolated_data_dir / "imports"
    leftovers = list(imports_dir.rglob("*.txt")) if imports_dir.exists() else []
    assert leftovers == []


def test_txt_import_db_failure_removes_written_file(
    client: TestClient, isolated_data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(importer_service, "create_txt_source", boom)
    response = _post_txt(client, SAMPLE.encode())
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "txt_persist_failed"
    with client.app.state.engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM import_sources")).scalar_one()
    assert count == 0
    imports_dir = isolated_data_dir / "imports"
    leftovers = list(imports_dir.rglob("*.txt")) if imports_dir.exists() else []
    assert leftovers == []
