from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.adapters.sqlite.models import Chapter, ChapterVersion, ImportSource, Novel
from app.domain.catalog import CatalogError, ChapterProvenance
from app.domain.chapter import TitleSource, VersionKind, resolve_chapter_title
from app.domain.chapter_canon import set_canon_pointer


def _now() -> datetime:
    return datetime.now(UTC)


def require_novel(session: Session, novel_id: str) -> Novel:
    novel = session.get(Novel, novel_id)
    if novel is None:
        raise CatalogError("novel_not_found", "Novel does not exist.")
    return novel


def require_chapter(session: Session, chapter_id: str) -> Chapter:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise CatalogError("chapter_not_found", "Chapter does not exist.")
    return chapter


def create_novel(session: Session, title: str) -> Novel:
    cleaned = title.strip()
    if not cleaned:
        raise CatalogError("novel_title_empty", "Novel title cannot be empty.")
    now = _now()
    novel = Novel(id=str(uuid4()), title=cleaned, created_at=now, updated_at=now)
    session.add(novel)
    session.flush()
    return novel


def get_novel(session: Session, novel_id: str) -> Novel:
    return require_novel(session, novel_id)


def list_novels(session: Session) -> list[Novel]:
    return list(session.scalars(select(Novel).order_by(Novel.updated_at.desc(), Novel.id)))


def list_chapters(session: Session, novel_id: str) -> list[Chapter]:
    require_novel(session, novel_id)
    return list(
        session.scalars(
            select(Chapter)
            .where(Chapter.novel_id == novel_id)
            .options(selectinload(Chapter.versions))
            .order_by(Chapter.sequence, Chapter.id)
        )
    )


def next_sequence(session: Session, novel_id: str) -> int:
    current = session.scalar(
        select(func.max(Chapter.sequence)).where(Chapter.novel_id == novel_id)
    )
    return 1 if current is None else int(current) + 1


def _original_version(chapter: Chapter) -> ChapterVersion | None:
    for version in chapter.versions:
        if version.version_kind == VersionKind.ORIGINAL.value:
            return version
    return None


def create_chapter(
    session: Session,
    novel_id: str,
    *,
    body: str,
    sequence: int | None = None,
    original_label: str = "",
    original_title: str = "",
    display_title: str | None = None,
    title_source: TitleSource | str | None = None,
    import_source_id: str | None = None,
    start_offset: int | None = None,
    end_offset: int | None = None,
    source_checksum: str | None = None,
) -> Chapter:
    novel = require_novel(session, novel_id)
    if sequence is None:
        sequence = next_sequence(session, novel_id)
    if sequence < 1:
        raise CatalogError("chapter_sequence_invalid", "Chapter sequence must be >= 1.")
    existing = session.scalar(
        select(Chapter.id).where(Chapter.novel_id == novel_id, Chapter.sequence == sequence)
    )
    if existing is not None:
        raise CatalogError(
            "chapter_sequence_conflict",
            "Chapter sequence is already used in this novel.",
        )
    if import_source_id is not None and session.get(ImportSource, import_source_id) is None:
        raise CatalogError("import_source_not_found", "Import source does not exist.")

    resolved_title, resolved_source = resolve_chapter_title(
        sequence=sequence,
        original_label=original_label,
        original_title=original_title,
        display_title=display_title,
        title_source=title_source,
    )
    now = _now()
    chapter = Chapter(
        id=str(uuid4()),
        novel_id=novel.id,
        sequence=sequence,
        original_label=original_label,
        original_title=original_title,
        display_title=resolved_title,
        title_source=resolved_source.value,
        created_at=now,
        updated_at=now,
        import_source_id=import_source_id,
    )
    original = ChapterVersion(
        id=str(uuid4()),
        chapter_id=chapter.id,
        version_kind=VersionKind.ORIGINAL.value,
        body=body,
        import_source_id=import_source_id,
        start_offset=start_offset,
        end_offset=end_offset,
        source_checksum=source_checksum,
        created_at=now,
    )
    session.add_all([chapter, original])
    session.flush()
    set_canon_pointer(chapter, original)
    novel.updated_at = now
    session.flush()
    return chapter


def update_chapter(
    session: Session,
    chapter_id: str,
    *,
    display_title: str | None = None,
    title_source: TitleSource | str | None = None,
) -> Chapter:
    chapter = require_chapter(session, chapter_id)
    if display_title is not None or title_source is not None:
        resolved_title, resolved_source = resolve_chapter_title(
            sequence=chapter.sequence,
            original_label=chapter.original_label,
            original_title=chapter.original_title,
            display_title=display_title if display_title is not None else chapter.display_title,
            title_source=title_source if title_source is not None else chapter.title_source,
        )
        chapter.display_title = resolved_title
        chapter.title_source = resolved_source.value
    chapter.updated_at = _now()
    session.flush()
    return chapter


def delete_chapter(session: Session, chapter_id: str) -> None:
    chapter = require_chapter(session, chapter_id)
    novel = require_novel(session, chapter.novel_id)
    session.delete(chapter)
    novel.updated_at = _now()
    session.flush()


def delete_novel(session: Session, novel_id: str) -> None:
    novel = require_novel(session, novel_id)
    session.delete(novel)
    session.flush()


def reorder_chapters(
    session: Session, novel_id: str, ordered_chapter_ids: list[str]
) -> list[Chapter]:
    chapters = list_chapters(session, novel_id)
    current_ids = [chapter.id for chapter in chapters]
    if sorted(ordered_chapter_ids) != sorted(current_ids):
        raise CatalogError(
            "chapter_reorder_mismatch",
            "Reorder list must contain each chapter in the novel exactly once.",
        )
    by_id = {chapter.id: chapter for chapter in chapters}
    now = _now()
    for index, chapter_id in enumerate(ordered_chapter_ids, start=1):
        by_id[chapter_id].sequence = -index
    session.flush()
    for index, chapter_id in enumerate(ordered_chapter_ids, start=1):
        chapter = by_id[chapter_id]
        chapter.sequence = index
        chapter.updated_at = now
    require_novel(session, novel_id).updated_at = now
    session.flush()
    return list_chapters(session, novel_id)


def chapter_provenance(session: Session, chapter_id: str) -> ChapterProvenance:
    chapter = require_chapter(session, chapter_id)
    original = _original_version(chapter)
    if original is None:
        loaded = list(
            session.scalars(
                select(ChapterVersion).where(
                    ChapterVersion.chapter_id == chapter.id,
                    ChapterVersion.version_kind == VersionKind.ORIGINAL.value,
                )
            )
        )
        original = loaded[0] if loaded else None
    if original is None:
        raise CatalogError("original_version_missing", "Chapter has no Original version.")
    return ChapterProvenance(
        chapter_id=chapter.id,
        novel_id=chapter.novel_id,
        original_version_id=original.id,
        import_source_id=original.import_source_id or chapter.import_source_id,
        start_offset=original.start_offset,
        end_offset=original.end_offset,
        source_checksum=original.source_checksum,
    )


def _copy_versions(
    session: Session,
    source: Chapter,
    target: Chapter,
    *,
    created_at: datetime,
) -> None:
    versions = list(
        session.scalars(
            select(ChapterVersion)
            .where(ChapterVersion.chapter_id == source.id)
            .order_by(ChapterVersion.created_at, ChapterVersion.id)
        )
    )
    id_map = {version.id: str(uuid4()) for version in versions}
    copies: list[ChapterVersion] = []
    for version in versions:
        copies.append(
            ChapterVersion(
                id=id_map[version.id],
                chapter_id=target.id,
                version_kind=version.version_kind,
                body=version.body,
                parent_version_id=None,
                superseded_by_id=None,
                import_source_id=version.import_source_id,
                start_offset=version.start_offset,
                end_offset=version.end_offset,
                source_checksum=version.source_checksum,
                created_at=created_at,
            )
        )
    session.add_all(copies)
    session.flush()
    by_old_id = {version.id: copy for version, copy in zip(versions, copies, strict=True)}
    for version, copy in zip(versions, copies, strict=True):
        if version.parent_version_id in id_map:
            copy.parent_version_id = id_map[version.parent_version_id]
        if version.superseded_by_id in id_map:
            copy.superseded_by_id = id_map[version.superseded_by_id]
    session.flush()
    if source.current_canon_version_id in id_map:
        canon = by_old_id[source.current_canon_version_id]
        set_canon_pointer(target, canon)
    session.flush()


def copy_novel(session: Session, novel_id: str, *, title: str | None = None) -> Novel:
    source = require_novel(session, novel_id)
    copied = create_novel(session, title or f"{source.title}（副本）")
    now = copied.created_at
    for chapter in list_chapters(session, source.id):
        replica = Chapter(
            id=str(uuid4()),
            novel_id=copied.id,
            sequence=chapter.sequence,
            original_label=chapter.original_label,
            original_title=chapter.original_title,
            display_title=chapter.display_title,
            title_source=chapter.title_source,
            title_confidence=chapter.title_confidence,
            import_source_id=chapter.import_source_id,
            created_at=now,
            updated_at=now,
        )
        session.add(replica)
        session.flush()
        _copy_versions(session, chapter, replica, created_at=now)
    copied.updated_at = now
    session.flush()
    return copied
