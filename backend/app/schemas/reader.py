from datetime import datetime

from pydantic import BaseModel


class ChapterTocItemDTO(BaseModel):
    chapter_id: str
    sequence: int
    original_label: str
    display_title: str
    title_source: str
    canon_version_id: str | None
    canon_kind: str | None
    has_draft: bool


class NovelChapterTocDTO(BaseModel):
    novel_id: str
    novel_title: str
    chapters: list[ChapterTocItemDTO]


class ChapterNavDTO(BaseModel):
    chapter_id: str
    sequence: int
    display_title: str


class CanonChapterDTO(BaseModel):
    novel_id: str
    chapter_id: str
    sequence: int
    original_label: str
    original_title: str
    display_title: str
    title_source: str
    body: str
    version_id: str
    version_kind: str
    is_canon: bool
    has_draft: bool
    previous: ChapterNavDTO | None
    next: ChapterNavDTO | None


class ChapterVersionDTO(BaseModel):
    novel_id: str
    chapter_id: str
    version_id: str
    version_kind: str
    body: str
    is_canon: bool
    created_at: datetime
    import_source_id: str | None = None
    parent_version_id: str | None = None
