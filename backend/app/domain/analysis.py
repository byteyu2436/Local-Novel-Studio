from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.chapter import VersionKind

CHAPTER_ANALYSIS_SCHEMA_VERSION = "chapter-analysis.v1"
SUPPORTED_SCHEMA_VERSIONS = frozenset({CHAPTER_ANALYSIS_SCHEMA_VERSION})
CANON_ANALYSIS_KINDS = frozenset({VersionKind.ORIGINAL.value, VersionKind.ACCEPTED.value})


class AnalysisError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def require_supported_schema_version(schema_version: str) -> str:
    """Reject unknown families. v1 has no silent compatibility shims."""

    version = schema_version.strip()
    if version in SUPPORTED_SCHEMA_VERSIONS:
        return version
    raise AnalysisError(
        "unsupported_schema_version",
        f"Schema version {schema_version!r} is not supported.",
    )


def require_canon_analysis_source(chapter: Chapter, version: ChapterVersion) -> None:
    """Official analysis may only bind the chapter's current Original/Accepted Canon."""

    if version.chapter_id != chapter.id:
        raise AnalysisError(
            "version_chapter_mismatch",
            "Version does not belong to this chapter.",
        )
    if version.version_kind == VersionKind.DRAFT.value:
        raise AnalysisError(
            "draft_cannot_be_analysis_source",
            "A Draft version cannot be the official analysis source.",
        )
    if version.version_kind not in CANON_ANALYSIS_KINDS:
        raise AnalysisError(
            "invalid_analysis_source_kind",
            "Official analysis requires an Original or Accepted version.",
        )
    if chapter.current_canon_version_id != version.id:
        raise AnalysisError(
            "analysis_requires_current_canon",
            "Official analysis must use the chapter's current Canon version.",
        )
