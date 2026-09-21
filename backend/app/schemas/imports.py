from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PasteImportRequest(BaseModel):
    text: str = Field(min_length=0)


class ImportSourceDTO(BaseModel):
    id: str
    source_type: Literal["paste", "txt"]
    checksum: str
    created_at: datetime
    parse_status: Literal["received", "normalized", "failed"]
    original_filename: str | None
    original_storage_path: str | None
    raw_byte_size: int
    raw_char_count: int
    has_normalized_text: bool
    detected_encoding: str | None = None
    encoding_uncertain: bool = False
    raw_text: str | None = None
    normalized_text: str | None = None


class ImportTextDTO(BaseModel):
    import_source_id: str
    kind: Literal["raw", "normalized"]
    text: str


class ImportErrorDTO(BaseModel):
    code: str
    message: str
    import_source_id: str | None = None


class TxtPreviewDTO(BaseModel):
    original_filename: str
    raw_byte_size: int
    detected_encoding: str | None
    encoding_uncertain: bool
    preview_text: str
    preview_truncated: bool
    char_count: int
