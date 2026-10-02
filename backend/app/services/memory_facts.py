from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from sqlalchemy.orm import Session

from app.adapters.sqlite.memory import MemoryFact
from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.chapter import VersionKind
from app.domain.memory import FactOrigin, FactStatus, MemoryError, MemorySubjectKind


@dataclass(frozen=True)
class FactProvenance:
    fact_id: str
    novel_id: str
    origin: str
    chapter_id: str
    chapter_version_id: str
    version_kind: str
    start_offset: int | None
    end_offset: int | None
    source_text: str | None
    source_text_hash: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def require_canon_memory_source(chapter: Chapter, version: ChapterVersion, novel_id: str) -> None:
    if chapter.novel_id != novel_id or version.chapter_id != chapter.id:
        raise MemoryError(
            "version_novel_mismatch",
            "Memory source must belong to this novel and chapter.",
        )
    if version.version_kind == VersionKind.DRAFT.value:
        raise MemoryError(
            "draft_cannot_be_memory_source",
            "A Draft version cannot be written into official memory.",
        )
    if version.version_kind not in {VersionKind.ORIGINAL.value, VersionKind.ACCEPTED.value}:
        raise MemoryError(
            "invalid_memory_source_kind",
            "Official memory requires an Original or Accepted version.",
        )


def _explicit_span(body: str, start: int | None, end: int | None) -> tuple[int, int, str, str]:
    if start is None or end is None or start < 0 or end > len(body) or start >= end:
        raise MemoryError(
            "provenance_span_invalid",
            "An explicit fact must point at a real span of the Canon text.",
        )
    excerpt = body[start:end]
    return start, end, excerpt, sha256(excerpt.encode()).hexdigest()


def record_memory_fact(
    session: Session,
    *,
    novel_id: str,
    subject_kind: MemorySubjectKind | str,
    subject_id: str,
    fact_key: str,
    fact_value: dict,
    source_chapter: Chapter,
    source_version: ChapterVersion,
    origin: FactOrigin | str,
    confidence: float,
    revision: int = 1,
    active: bool = True,
    locked: bool = False,
    status: FactStatus | str | None = None,
    superseded_by_id: str | None = None,
    source_snapshot_id: str | None = None,
    start_offset: int | None = None,
    end_offset: int | None = None,
    source_chunk_ids: list[str] | None = None,
) -> MemoryFact:
    """Persist one fact. Draft text is rejected. Inferred facts cannot pretend to be quotes."""

    require_canon_memory_source(source_chapter, source_version, novel_id)
    if not 0 <= confidence <= 1:
        raise MemoryError("confidence_out_of_range", "Confidence must be between 0 and 1.")
    resolved_origin = FactOrigin(origin)
    resolved_status = FactStatus(status or (FactStatus.ACTIVE if active else FactStatus.SUPERSEDED))
    if active and resolved_status is not FactStatus.ACTIVE:
        raise MemoryError("fact_status_mismatch", "An active fact cannot be superseded.")
    if not active and resolved_status is not FactStatus.SUPERSEDED:
        raise MemoryError("fact_status_mismatch", "An inactive fact must be superseded.")
    text_hash: str | None = None
    if resolved_origin is FactOrigin.EXPLICIT:
        start_offset, end_offset, _excerpt, text_hash = _explicit_span(
            source_version.body, start_offset, end_offset
        )
    elif start_offset is not None or end_offset is not None:
        raise MemoryError(
            "inferred_cannot_claim_explicit_span",
            "An inferred fact cannot carry an explicit source span.",
        )
    now = _now()
    row = MemoryFact(
        id=str(uuid4()),
        novel_id=novel_id,
        subject_kind=MemorySubjectKind(subject_kind).value,
        subject_id=subject_id,
        fact_key=fact_key,
        fact_value=fact_value,
        revision=revision,
        active=active,
        origin=resolved_origin.value,
        status=resolved_status.value,
        confidence=confidence,
        locked=locked,
        source_chapter_id=source_chapter.id,
        source_chapter_version_id=source_version.id,
        source_snapshot_id=source_snapshot_id,
        source_start_offset=start_offset,
        source_end_offset=end_offset,
        source_text_hash=text_hash,
        source_chunk_ids=source_chunk_ids,
        superseded_by_id=superseded_by_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return row


def read_fact_provenance(session: Session, fact_id: str) -> FactProvenance:
    fact = session.get(MemoryFact, fact_id)
    if fact is None:
        raise MemoryError("fact_not_found", "Fact does not exist.")
    if fact.source_chapter_id is None or fact.source_chapter_version_id is None:
        raise MemoryError("provenance_missing", "Fact has no Canon source.")
    version = session.get(ChapterVersion, fact.source_chapter_version_id)
    chapter = session.get(Chapter, fact.source_chapter_id)
    if version is None or chapter is None or version.chapter_id != chapter.id:
        raise MemoryError("provenance_missing", "Fact source chapter version is missing.")
    excerpt: str | None = None
    if fact.origin == FactOrigin.EXPLICIT.value:
        if fact.source_start_offset is None or fact.source_end_offset is None:
            raise MemoryError("provenance_missing", "Explicit fact is missing its source span.")
        excerpt = version.body[fact.source_start_offset : fact.source_end_offset]
        digest = sha256(excerpt.encode()).hexdigest()
        if digest != fact.source_text_hash:
            raise MemoryError(
                "provenance_hash_mismatch",
                "Stored evidence no longer matches the Canon text.",
            )
    return FactProvenance(
        fact_id=fact.id,
        novel_id=fact.novel_id,
        origin=fact.origin,
        chapter_id=chapter.id,
        chapter_version_id=version.id,
        version_kind=version.version_kind,
        start_offset=fact.source_start_offset,
        end_offset=fact.source_end_offset,
        source_text=excerpt,
        source_text_hash=fact.source_text_hash,
    )
