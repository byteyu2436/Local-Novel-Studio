from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.adapters.llm.types import LLMProvider
from app.adapters.sqlite.memory import MemoryReduceApplication
from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.chapter import VersionKind
from app.domain.memory import MemoryError
from app.schemas.analysis import parse_stored_analysis_payload
from app.services import catalog
from app.services.analysis import get_chapter_analysis, persist_chapter_analysis
from app.services.chapter_analyzer import analyze_chapter_text
from app.services.memory_facts import require_canon_memory_source
from app.services.memory_reduce import ReduceReport, reduce_chapter_analysis
from app.services.memory_repository import MemoryRepository
from app.services.memory_snapshot import (
    create_memory_snapshot,
    get_memory_snapshot,
    snapshot_chapter,
)


async def commit_canon_memory(
    session: Session,
    novel_id: str,
    chapter_id: str,
    version_id: str,
    provider: LLMProvider,
) -> str:
    """Analyze and reduce one Canon chapter, then anchor a snapshot. Drafts are refused."""

    chapter, version = _canon_inputs(session, novel_id, chapter_id, version_id)
    body = version.body
    try:
        await _ensure_analysis(session, chapter, version, provider)
        stored = get_chapter_analysis(session, chapter.id, version.id)
        if stored is None:
            raise MemoryError("analysis_missing", "Canon analysis was not stored.")
        payload = parse_stored_analysis_payload(
            stored.payload, schema_version=stored.schema_version
        )
        reduce_chapter_analysis(
            session,
            novel_id=novel_id,
            chapter=chapter,
            source_version=version,
            payload=payload,
        )
        snapshot = create_memory_snapshot(session, novel_id, chapter.id)
    except Exception:
        version.body = body
        raise
    if version.body != body:
        version.body = body
        raise MemoryError("canon_mutated", "Incremental memory must not change Canon text.")
    return snapshot.id


async def rebuild_memory_after_snapshot(
    session: Session,
    novel_id: str,
    snapshot_id: str,
    provider: LLMProvider,
) -> str:
    """Re-apply Canon chapters after a snapshot. The original snapshot row stays."""

    snapshot = get_memory_snapshot(session, snapshot_id)
    if snapshot.novel_id != novel_id:
        raise MemoryError("snapshot_novel_mismatch", "Snapshot belongs to another novel.")
    anchor = snapshot_chapter(session, snapshot)
    if anchor.novel_id != novel_id:
        raise MemoryError("snapshot_novel_mismatch", "Snapshot belongs to another novel.")
    original_bodies = {
        chapter.id: _canon_body(session, chapter)
        for chapter in catalog.list_chapters(session, novel_id)
    }
    try:
        later = [
            chapter
            for chapter in catalog.list_chapters(session, novel_id)
            if chapter.sequence > anchor.sequence and chapter.current_canon_version_id
        ]
        report = ReduceReport(replay=True)
        for chapter in later:
            version = session.get(ChapterVersion, chapter.current_canon_version_id)
            if version is None:
                continue
            require_canon_memory_source(chapter, version, novel_id)
            session.execute(
                delete(MemoryReduceApplication).where(
                    MemoryReduceApplication.novel_id == novel_id,
                    MemoryReduceApplication.source_chapter_version_id == version.id,
                )
            )
            await _ensure_analysis(session, chapter, version, provider)
            stored = get_chapter_analysis(session, chapter.id, version.id)
            if stored is None:
                raise MemoryError("analysis_missing", "Canon analysis was not stored.")
            payload = parse_stored_analysis_payload(
                stored.payload, schema_version=stored.schema_version
            )
            reduce_chapter_analysis(
                session,
                novel_id=novel_id,
                chapter=chapter,
                source_version=version,
                payload=payload,
                report=report,
            )
        MemoryRepository(session).note_revision(novel_id)
        tip = later[-1].id if later else anchor.id
        created = create_memory_snapshot(session, novel_id, tip)
    except Exception:
        _restore_bodies(session, original_bodies)
        raise
    _restore_bodies(session, original_bodies)
    return created.id


def _canon_inputs(
    session: Session, novel_id: str, chapter_id: str, version_id: str
) -> tuple[Chapter, ChapterVersion]:
    catalog.require_novel(session, novel_id)
    chapter = catalog.require_chapter(session, chapter_id)
    version = session.get(ChapterVersion, version_id)
    if version is None or chapter.novel_id != novel_id or version.chapter_id != chapter.id:
        raise MemoryError("version_novel_mismatch", "Canon version does not belong to this novel.")
    if version.version_kind == VersionKind.DRAFT.value:
        raise MemoryError("draft_cannot_be_memory_source", "A Draft version cannot update memory.")
    if version.version_kind not in {VersionKind.ORIGINAL.value, VersionKind.ACCEPTED.value}:
        raise MemoryError("rejected_version", "Only Original or Accepted Canon can update memory.")
    return chapter, version


async def _ensure_analysis(
    session: Session, chapter: Chapter, version: ChapterVersion, provider: LLMProvider
) -> None:
    if get_chapter_analysis(session, chapter.id, version.id) is not None:
        return
    result = await analyze_chapter_text(
        provider,
        version.body,
        chapter_id=chapter.id,
        source_version_id=version.id,
    )
    persist_chapter_analysis(
        session,
        chapter,
        version,
        payload=result.payload,
        analyzer_version=result.analyzer_version,
        model_profile_id=result.model_profile_id,
        prompt_version=result.prompt_version,
        profile_version=result.profile_version,
        schema_version=result.schema_version,
        model_ref=result.model_ref,
    )


def _canon_body(session: Session, chapter: Chapter) -> str:
    if chapter.current_canon_version_id is None:
        return ""
    version = session.get(ChapterVersion, chapter.current_canon_version_id)
    return "" if version is None else version.body


def _restore_bodies(session: Session, bodies: dict[str, str]) -> None:
    for chapter_id, body in bodies.items():
        chapter = session.get(Chapter, chapter_id)
        if chapter is None or chapter.current_canon_version_id is None:
            continue
        version = session.get(ChapterVersion, chapter.current_canon_version_id)
        if version is not None and version.body != body:
            version.body = body
