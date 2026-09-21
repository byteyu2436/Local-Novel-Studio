from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.sqlite.models import Chapter, ChapterAnalysis, ChapterVersion
from app.domain.analysis import (
    CHAPTER_ANALYSIS_SCHEMA_VERSION,
    AnalysisError,
    require_canon_analysis_source,
    require_supported_schema_version,
)
from app.schemas.analysis import (
    AnalysisResultDTO,
    ChapterAnalysisPayload,
    parse_stored_analysis_payload,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _require_metadata(
    analyzer_version: str,
    model_profile_id: str,
    prompt_version: str,
    profile_version: str,
) -> tuple[str, str, str, str]:
    analyzer = analyzer_version.strip()
    profile = model_profile_id.strip()
    prompt = prompt_version.strip()
    sampling = profile_version.strip()
    if not analyzer:
        raise AnalysisError("analysis_metadata_invalid", "analyzer_version is required.")
    if not profile:
        raise AnalysisError("analysis_metadata_invalid", "model_profile_id is required.")
    if not prompt:
        raise AnalysisError("analysis_metadata_invalid", "prompt_version is required.")
    if not sampling:
        raise AnalysisError("analysis_metadata_invalid", "profile_version is required.")
    return analyzer, profile, prompt, sampling


def persist_chapter_analysis(
    session: Session,
    chapter: Chapter,
    source_version: ChapterVersion,
    *,
    payload: ChapterAnalysisPayload | dict,
    analyzer_version: str,
    model_profile_id: str,
    prompt_version: str,
    profile_version: str,
    schema_version: str = CHAPTER_ANALYSIS_SCHEMA_VERSION,
    model_ref: str | None = None,
    created_at: datetime | None = None,
) -> ChapterAnalysis:
    """Validate then persist an official analysis for the chapter's current Canon."""

    require_canon_analysis_source(chapter, source_version)
    resolved_schema = require_supported_schema_version(schema_version)
    analyzer, profile, prompt, sampling = _require_metadata(
        analyzer_version, model_profile_id, prompt_version, profile_version
    )
    validated = parse_stored_analysis_payload(payload, schema_version=resolved_schema)
    existing = session.scalar(
        select(ChapterAnalysis).where(
            ChapterAnalysis.chapter_id == chapter.id,
            ChapterAnalysis.source_version_id == source_version.id,
        )
    )
    if existing is not None:
        raise AnalysisError(
            "analysis_already_exists",
            "Official analysis for this Canon version already exists.",
        )
    row = ChapterAnalysis(
        id=str(uuid4()),
        chapter_id=chapter.id,
        source_version_id=source_version.id,
        source_version_kind=source_version.version_kind,
        schema_version=resolved_schema,
        analyzer_version=analyzer,
        prompt_version=prompt,
        profile_version=sampling,
        model_profile_id=profile,
        model_ref=(model_ref.strip() if model_ref and model_ref.strip() else None),
        payload=validated.model_dump(mode="json"),
        created_at=created_at or _now(),
    )
    session.add(row)
    session.flush()
    return row


def get_chapter_analysis(
    session: Session, chapter_id: str, source_version_id: str
) -> ChapterAnalysis | None:
    return session.scalar(
        select(ChapterAnalysis).where(
            ChapterAnalysis.chapter_id == chapter_id,
            ChapterAnalysis.source_version_id == source_version_id,
        )
    )


def analysis_result_dto(row: ChapterAnalysis) -> AnalysisResultDTO:
    payload = parse_stored_analysis_payload(row.payload, schema_version=row.schema_version)
    return AnalysisResultDTO(
        id=row.id,
        chapter_id=row.chapter_id,
        source_version_id=row.source_version_id,
        source_version_kind=row.source_version_kind,  # type: ignore[arg-type]
        schema_version=row.schema_version,
        analyzer_version=row.analyzer_version,
        prompt_version=row.prompt_version,
        profile_version=row.profile_version,
        model_profile_id=row.model_profile_id,
        model_ref=row.model_ref,
        payload=payload,
        created_at=row.created_at,
    )
