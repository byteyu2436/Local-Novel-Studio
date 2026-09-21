from dataclasses import dataclass
from enum import StrEnum

from app.domain.importing import ImportValidationError, normalize_imported_text

UTF8_BOM = b"\xef\xbb\xbf"
_ALLOWED_CONTROLS = {"\t", "\n", "\r"}
_OVERRIDE_ENCODINGS = {"utf-8", "gbk", "gb18030"}


class EncodingConfidence(StrEnum):
    CERTAIN = "certain"
    LIKELY = "likely"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class TxtDecodeResult:
    encoding: str | None
    confidence: EncodingConfidence | None
    uncertain: bool
    had_bom: bool
    text: str | None
    normalized_text: str | None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_code is None and self.text is not None


def _try_decode(data: bytes, encoding: str) -> str | None:
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        return None


def _cjk_count(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def _is_plausible_text(text: str) -> bool:
    if not text or "\x00" in text:
        return False
    controls = sum(1 for ch in text if ord(ch) < 32 and ch not in _ALLOWED_CONTROLS)
    return (controls / len(text)) <= 0.05


def _normalize_label(encoding: str) -> str:
    label = encoding.strip().lower().replace("_", "-")
    aliases = {
        "utf8": "utf-8",
        "utf-8-sig": "utf-8",
        "gb2312": "gbk",
        "cp936": "gbk",
    }
    return aliases.get(label, label)


def decode_txt_bytes(data: bytes, *, encoding: str | None = None) -> TxtDecodeResult:
    """Detect and decode TXT bytes. Does not persist files or Chapter records."""

    if not data:
        raise ImportValidationError("txt_empty", "TXT file is empty.")
    if b"\x00" in data:
        return TxtDecodeResult(
            encoding=None,
            confidence=None,
            uncertain=False,
            had_bom=False,
            text=None,
            normalized_text=None,
            error_code="txt_binary",
            error_message="The file looks like binary data, not a text novel.",
        )

    had_bom = data.startswith(UTF8_BOM)
    if encoding is not None:
        return _decode_with_override(data, encoding, had_bom=had_bom)
    return _detect_and_decode(data, had_bom=had_bom)


def _strip_decoded_bom(text: str) -> str:
    return text.lstrip("\ufeff")


def _result(
    *,
    encoding: str,
    confidence: EncodingConfidence,
    uncertain: bool,
    had_bom: bool,
    text: str,
) -> TxtDecodeResult:
    cleaned = _strip_decoded_bom(text)
    return TxtDecodeResult(
        encoding=encoding,
        confidence=confidence,
        uncertain=uncertain,
        had_bom=had_bom,
        text=cleaned,
        normalized_text=normalize_imported_text(cleaned),
    )


def _decode_with_override(data: bytes, encoding: str, *, had_bom: bool) -> TxtDecodeResult:
    label = _normalize_label(encoding)
    codec = "utf-8-sig" if label == "utf-8" and had_bom else label
    if label not in _OVERRIDE_ENCODINGS:
        raise ImportValidationError(
            "txt_encoding_unsupported",
            f"Unsupported encoding override: {encoding}.",
        )
    text = _try_decode(data, codec)
    if text is None or not _is_plausible_text(text):
        raise ImportValidationError(
            "txt_encoding_invalid",
            f"The file could not be decoded as {label}.",
        )
    return _result(
        encoding=label,
        confidence=EncodingConfidence.CERTAIN,
        uncertain=False,
        had_bom=had_bom,
        text=text,
    )


def _detect_and_decode(data: bytes, *, had_bom: bool) -> TxtDecodeResult:
    if had_bom:
        text = _try_decode(data, "utf-8-sig")
        if text is not None and _is_plausible_text(text):
            return _result(
                encoding="utf-8",
                confidence=EncodingConfidence.CERTAIN,
                uncertain=False,
                had_bom=True,
                text=text,
            )

    utf8 = _try_decode(data, "utf-8")
    gbk = _try_decode(data, "gbk")
    gb18030 = _try_decode(data, "gb18030") if gbk is None else gbk

    if utf8 is not None and gbk is not None and utf8 != gbk:
        chosen, label = (utf8, "utf-8") if _cjk_count(utf8) >= _cjk_count(gbk) else (gbk, "gbk")
        if not _is_plausible_text(chosen):
            return _failed_decode()
        return _result(
            encoding=label,
            confidence=EncodingConfidence.UNCERTAIN,
            uncertain=True,
            had_bom=False,
            text=chosen,
        )

    if utf8 is not None and _is_plausible_text(utf8):
        return _result(
            encoding="utf-8",
            confidence=EncodingConfidence.CERTAIN,
            uncertain=False,
            had_bom=False,
            text=utf8,
        )

    if gbk is not None and _is_plausible_text(gbk):
        return _result(
            encoding="gbk",
            confidence=EncodingConfidence.CERTAIN,
            uncertain=False,
            had_bom=False,
            text=gbk,
        )

    if gb18030 is not None and _is_plausible_text(gb18030):
        return _result(
            encoding="gb18030",
            confidence=EncodingConfidence.LIKELY,
            uncertain=True,
            had_bom=False,
            text=gb18030,
        )

    return _failed_decode()


def _failed_decode() -> TxtDecodeResult:
    return TxtDecodeResult(
        encoding=None,
        confidence=None,
        uncertain=False,
        had_bom=False,
        text=None,
        normalized_text=None,
        error_code="txt_decode_failed",
        error_message=(
            "The TXT encoding could not be detected. Choose UTF-8 or GBK and preview again."
        ),
    )
