"""Domain models. Novel / chapter / memory implementations come later."""

from app.domain.importing import (
    ImportSourceImmutableError,
    ImportValidationError,
    ParseStatus,
    SourceType,
    normalize_imported_text,
    relative_import_storage_path,
    sha256_hex,
    validate_paste_text,
)
from app.domain.txt_encoding import (
    EncodingConfidence,
    TxtDecodeResult,
    decode_txt_bytes,
)

__all__ = [
    "EncodingConfidence",
    "ImportSourceImmutableError",
    "ImportValidationError",
    "ParseStatus",
    "SourceType",
    "TxtDecodeResult",
    "decode_txt_bytes",
    "normalize_imported_text",
    "relative_import_storage_path",
    "sha256_hex",
    "validate_paste_text",
]
