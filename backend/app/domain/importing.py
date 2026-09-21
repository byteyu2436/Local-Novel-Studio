from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path


class SourceType(StrEnum):
    PASTE = "paste"
    TXT = "txt"


class ParseStatus(StrEnum):
    RECEIVED = "received"
    NORMALIZED = "normalized"
    FAILED = "failed"


class ImportSourceImmutableError(Exception):
    """Raised when a caller tries to overwrite an Original Source snapshot."""


class ImportValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


PASTE_MAX_CHARS = 2_000_000
_ALLOWED_CONTROLS = {"\t", "\n"}


def sha256_hex(payload: bytes) -> str:
    """Stable checksum for original paste bytes or TXT file bytes."""

    return sha256(payload).hexdigest()


def relative_import_storage_path(source_id: str, filename: str) -> str:
    """Path under DATA_DIR for an original TXT. Does not write the file."""

    safe_name = Path(filename).name or "original.txt"
    return f"imports/{source_id}/{safe_name}"


def validate_txt_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    if not name:
        raise ImportValidationError("txt_filename_required", "TXT filename is required.")
    if not name.lower().endswith(".txt"):
        raise ImportValidationError(
            "txt_unsupported_type",
            "Only .txt files can be imported.",
        )
    return name


def validate_paste_text(text: str, *, max_chars: int | None = None) -> None:
    limit = PASTE_MAX_CHARS if max_chars is None else max_chars
    if not text.strip():
        raise ImportValidationError("import_empty", "Paste text is empty.")
    if len(text) > limit:
        raise ImportValidationError(
            "import_too_large",
            f"Paste text exceeds the {limit} character limit.",
        )
    if "\x00" in text:
        raise ImportValidationError(
            "import_invalid_characters",
            "Paste text contains a NUL character and cannot be imported.",
        )


def normalize_imported_text(raw: str) -> str:
    """Derive a display/pipeline copy. Never mutate the original snapshot."""

    text = raw[1:] if raw.startswith("\ufeff") else raw
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(ch for ch in text if ch in _ALLOWED_CONTROLS or ord(ch) >= 32)


@dataclass(frozen=True, slots=True)
class PasteImportOutcome:
    source_id: str
    parse_status: ParseStatus
    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_code is None


@dataclass(frozen=True, slots=True)
class TxtImportOutcome:
    source_id: str
    parse_status: ParseStatus
    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_code is None
