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
