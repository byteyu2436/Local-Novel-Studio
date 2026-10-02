from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.sqlite.chunks import CanonChunk, chunk_now
from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.chapter import VersionKind
from app.domain.chunking import (
    ChunkingProfile,
    ChunkPiece,
    chunk_identity,
    chunk_text,
    text_checksum,
)
from app.schemas.analysis import parse_stored_analysis_payload
from app.services import catalog
from app.services.analysis import get_chapter_analysis


class ChunkError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def build_chapter_chunks(
    session: Session,
    novel_id: str,
    chapter: Chapter,
    version: ChapterVersion,
    profile: ChunkingProfile | None = None,
) -> list[CanonChunk]:
    """Replace this chapter's active chunks. Other chapters stay untouched."""

    _require_canon_chunk_source(chapter, version, novel_id)
    resolved = profile or ChunkingProfile()
    metadata = _analysis_metadata(session, chapter, version)
    pieces = chunk_text(version.body, resolved)
    desired: list[tuple[str, ChunkPiece, str]] = []
    for piece in pieces:
        checksum = text_checksum(piece.text)
        desired.append(
            (
                chunk_identity(
                    novel_id=novel_id,
                    chapter_id=chapter.id,
                    source_version_id=version.id,
                    chunking_version=resolved.version,
                    index=piece.index,
                    text_checksum=checksum,
                ),
                piece,
                checksum,
            )
        )
    with session.begin_nested():
        existing = list(
            session.scalars(select(CanonChunk).where(CanonChunk.chapter_id == chapter.id))
        )
        desired_ids = {item[0] for item in desired}
        by_id = {row.id: row for row in existing}
        for row in existing:
            if row.id not in desired_ids and row.canon_status == "active":
                row.canon_status = "inactive"
        for chunk_id, piece, checksum in desired:
            row = by_id.get(chunk_id)
            if row is None:
                row = CanonChunk(
                    id=chunk_id,
                    novel_id=novel_id,
                    chapter_id=chapter.id,
                    source_version_id=version.id,
                    source_version_kind=version.version_kind,
                    chunk_index=piece.index,
                    sequence=chapter.sequence * 100000 + piece.index,
                    chunk_type=piece.chunk_type,
                    text=piece.text,
                    text_checksum=checksum,
                    start_offset=piece.start_offset,
                    end_offset=piece.end_offset,
                    overlap_tokens=piece.overlap_tokens,
                    characters=list(metadata["characters"]),
                    locations=list(metadata["locations"]),
                    event_ids=list(metadata["event_ids"]),
                    importance=metadata["importance"],
                    canon_status="active",
                    chunking_version=resolved.version,
                    embedding_profile_id=None,
                    created_at=chunk_now(),
                )
                session.add(row)
            else:
                row.canon_status = "active"
                row.text = piece.text
                row.text_checksum = checksum
                row.start_offset = piece.start_offset
                row.end_offset = piece.end_offset
                row.overlap_tokens = piece.overlap_tokens
                row.characters = list(metadata["characters"])
                row.locations = list(metadata["locations"])
                row.event_ids = list(metadata["event_ids"])
                row.importance = metadata["importance"]
        session.flush()
    return list_canon_chunks(session, novel_id, chapter_id=chapter.id)


def build_novel_chunks(
    session: Session, novel_id: str, profile: ChunkingProfile | None = None
) -> list[CanonChunk]:
    catalog.require_novel(session, novel_id)
    built: list[CanonChunk] = []
    for chapter in catalog.list_chapters(session, novel_id):
        if chapter.current_canon_version_id is None:
            continue
        version = session.get(ChapterVersion, chapter.current_canon_version_id)
        if version is None:
            continue
        built.extend(build_chapter_chunks(session, novel_id, chapter, version, profile))
    return built


def list_canon_chunks(
    session: Session, novel_id: str, *, chapter_id: str | None = None, active_only: bool = True
) -> list[CanonChunk]:
    catalog.require_novel(session, novel_id)
    stmt = select(CanonChunk).where(CanonChunk.novel_id == novel_id)
    if chapter_id is not None:
        stmt = stmt.where(CanonChunk.chapter_id == chapter_id)
    if active_only:
        stmt = stmt.where(CanonChunk.canon_status == "active")
    stmt = stmt.order_by(CanonChunk.sequence, CanonChunk.chunk_index, CanonChunk.id)
    return list(session.scalars(stmt))


def _require_canon_chunk_source(chapter: Chapter, version: ChapterVersion, novel_id: str) -> None:
    if chapter.novel_id != novel_id or version.chapter_id != chapter.id:
        raise ChunkError(
            "version_novel_mismatch",
            "Chunk source must belong to this novel and chapter.",
        )
    if version.version_kind == VersionKind.DRAFT.value:
        raise ChunkError(
            "draft_cannot_be_canon_chunk",
            "A Draft version cannot enter the official chunk set.",
        )
    if version.version_kind not in {VersionKind.ORIGINAL.value, VersionKind.ACCEPTED.value}:
        raise ChunkError(
            "rejected_version",
            "Official chunks require an Original or Accepted version.",
        )


def _analysis_metadata(session: Session, chapter: Chapter, version: ChapterVersion) -> dict:
    empty = {"characters": [], "locations": [], "event_ids": [], "importance": "medium"}
    stored = get_chapter_analysis(session, chapter.id, version.id)
    if stored is None:
        return empty
    payload = parse_stored_analysis_payload(stored.payload, schema_version=stored.schema_version)
    ranks = {"low": 0, "medium": 1, "high": 2}
    importance = "medium"
    best = -1
    event_ids: list[str] = []
    for event in payload.events:
        event_ids.append(sha256(event.summary.encode()).hexdigest()[:16])
        score = ranks.get(event.importance, 1)
        if score > best:
            best = score
            importance = event.importance
    return {
        "characters": [item.name for item in payload.characters],
        "locations": [item.name for item in payload.locations],
        "event_ids": event_ids,
        "importance": importance,
    }
