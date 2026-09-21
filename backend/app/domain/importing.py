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


def sha256_hex(payload: bytes) -> str:
    """Stable checksum for original paste bytes or TXT file bytes."""

    return sha256(payload).hexdigest()


def relative_import_storage_path(source_id: str, filename: str) -> str:
    """Path under DATA_DIR for an original TXT. Does not write the file."""

    safe_name = Path(filename).name or "original.txt"
    return f"imports/{source_id}/{safe_name}"
