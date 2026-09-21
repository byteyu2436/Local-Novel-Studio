from dataclasses import dataclass


class CatalogError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ChapterProvenance:
    chapter_id: str
    novel_id: str
    original_version_id: str
    import_source_id: str | None
    start_offset: int | None
    end_offset: int | None
    source_checksum: str | None
