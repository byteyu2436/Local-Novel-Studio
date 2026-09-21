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


class ChapterCandidateDTO(BaseModel):
    candidate_id: str
    sequence: int
    original_label: str
    title_candidate: str
    start_offset: int
    end_offset: int
    confidence: float
    classification: Literal["single", "multi", "unstructured"]
    preview_text: str


class DetectionResultDTO(BaseModel):
    import_source_id: str
    checksum: str
    classification: Literal["single", "multi", "unstructured"]
    candidates: list[ChapterCandidateDTO]
    warnings: list[str]
    normalized_char_count: int


class ImportSpanDTO(BaseModel):
    import_source_id: str
    start_offset: int
    end_offset: int
    text: str


class ConfirmCandidateDTO(BaseModel):
    candidate_id: str
    sequence: int
    original_label: str = ""
    title_candidate: str = ""
    start_offset: int
    end_offset: int
    confidence: float = 1.0
    classification: Literal["single", "multi", "unstructured"] = "multi"


class ImportConfirmRequest(BaseModel):
    checksum: str
    destination: Literal["new_novel", "append"] = "new_novel"
    novel_id: str | None = None
    novel_title: str | None = None
    unstructured_ack: bool = False
    classification: Literal["single", "multi", "unstructured"] = "multi"
    candidates: list[ConfirmCandidateDTO]


class ConfirmedChapterDTO(BaseModel):
    chapter_id: str
    sequence: int
    display_title: str
    start_offset: int | None = None
    end_offset: int | None = None


class ImportConfirmDTO(BaseModel):
    import_source_id: str
    novel_id: str
    novel_title: str
    destination: Literal["new_novel", "append"]
    idempotent: bool
    chapters: list[ConfirmedChapterDTO]
