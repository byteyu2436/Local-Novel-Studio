import pytest
from app.domain.importing import ImportValidationError, normalize_imported_text
from app.domain.txt_encoding import EncodingConfidence, decode_txt_bytes
from sqlalchemy import inspect

SAMPLE = "第一章 开场\r\n林深时见鹿。"


@pytest.mark.parametrize(
    ("payload", "expected_encoding", "had_bom"),
    [
        (SAMPLE.encode("utf-8"), "utf-8", False),
        (b"\xef\xbb\xbf" + SAMPLE.encode("utf-8"), "utf-8", True),
        (SAMPLE.encode("gbk"), "gbk", False),
        (SAMPLE.encode("gb18030"), "gbk", False),
    ],
)
def test_detects_common_chinese_txt_encodings(
    payload: bytes, expected_encoding: str, had_bom: bool
) -> None:
    result = decode_txt_bytes(payload)
    assert result.ok
    assert result.encoding == expected_encoding
    assert result.had_bom is had_bom
    assert result.text is not None
    assert "\ufeff" not in result.text
    assert result.normalized_text == normalize_imported_text(result.text)
    assert "林深时见鹿" in (result.normalized_text or "")


def test_utf8_bom_is_not_part_of_decoded_body() -> None:
    result = decode_txt_bytes(b"\xef\xbb\xbf" + "第一章".encode())
    assert result.ok
    assert result.had_bom is True
    assert result.text == "第一章"
    assert result.normalized_text == "第一章"


def test_encoding_override_rejects_wrong_codec_then_succeeds() -> None:
    payload = SAMPLE.encode("gbk")
    with pytest.raises(ImportValidationError) as exc:
        decode_txt_bytes(payload, encoding="utf-8")
    assert exc.value.code == "txt_encoding_invalid"

    fixed = decode_txt_bytes(payload, encoding="gbk")
    assert fixed.ok
    assert fixed.encoding == "gbk"
    assert fixed.uncertain is False
    assert "第一章" in (fixed.text or "")


def test_override_gb18030_reads_gbk_bytes() -> None:
    result = decode_txt_bytes(SAMPLE.encode("gbk"), encoding="gb18030")
    assert result.ok
    assert result.encoding == "gb18030"
    assert result.normalized_text == normalize_imported_text(SAMPLE.replace("\r\n", "\n"))


def test_binary_and_corrupt_files_fail_without_chapter_tables(client) -> None:
    binary = decode_txt_bytes(b"\x00PNG" + b"\xff" * 32)
    assert not binary.ok
    assert binary.error_code == "txt_binary"
    assert binary.text is None

    corrupt = decode_txt_bytes(bytes(range(128, 256)) * 4)
    assert not corrupt.ok
    assert corrupt.error_code in {"txt_decode_failed", "txt_binary"}
    assert corrupt.text is None

    tables = inspect(client.app.state.engine).get_table_names()
    assert "chapters" not in tables
    assert "novels" not in tables


def test_empty_txt_raises_stable_code() -> None:
    with pytest.raises(ImportValidationError) as exc:
        decode_txt_bytes(b"")
    assert exc.value.code == "txt_empty"


def test_unsupported_override_is_rejected() -> None:
    with pytest.raises(ImportValidationError) as exc:
        decode_txt_bytes(SAMPLE.encode("utf-8"), encoding="latin-1")
    assert exc.value.code == "txt_encoding_unsupported"


def test_dual_valid_encodings_are_marked_uncertain() -> None:
    payload = "café".encode()
    utf8_text = payload.decode("utf-8")
    gbk_text = payload.decode("gbk")
    result = decode_txt_bytes(payload)
    assert result.ok
    if utf8_text == gbk_text:
        assert result.uncertain is False
        return
    assert result.uncertain is True
    assert result.confidence == EncodingConfidence.UNCERTAIN
