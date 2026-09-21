from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.domain.catalog import CatalogError
from app.schemas.imports import ImportErrorDTO
from app.schemas.reader import (
    CanonChapterDTO,
    ChapterNavDTO,
    ChapterTocItemDTO,
    ChapterVersionDTO,
    NovelChapterTocDTO,
)
from app.services.reader import novel_chapter_toc, read_canon_chapter, read_chapter_version

router = APIRouter(tags=["reader"])


def _catalog_http(exc: CatalogError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if exc.code
        in {
            "novel_not_found",
            "chapter_not_found",
            "canon_missing",
            "version_not_found",
            "version_chapter_mismatch",
        }
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message})


@router.get(
    "/api/novels/{novel_id}/chapters",
    response_model=NovelChapterTocDTO,
    responses={404: {"model": ImportErrorDTO}},
)
def get_novel_chapters(
    novel_id: str, session: Annotated[Session, Depends(get_session)]
) -> NovelChapterTocDTO:
    try:
        resolved_id, title, items = novel_chapter_toc(session, novel_id)
    except CatalogError as exc:
        raise _catalog_http(exc) from exc
    return NovelChapterTocDTO(
        novel_id=resolved_id,
        novel_title=title,
        chapters=[
            ChapterTocItemDTO(
                chapter_id=item.chapter_id,
                sequence=item.sequence,
                original_label=item.original_label,
                display_title=item.display_title,
                title_source=item.title_source,
                canon_version_id=item.canon_version_id,
                canon_kind=item.canon_kind,
                has_draft=item.has_draft,
            )
            for item in items
        ],
    )


def _nav_dto(item) -> ChapterNavDTO | None:
    if item is None:
        return None
    return ChapterNavDTO(
        chapter_id=item.chapter_id,
        sequence=item.sequence,
        display_title=item.display_title,
    )


@router.get(
    "/api/chapters/{chapter_id}",
    response_model=CanonChapterDTO,
    responses={404: {"model": ImportErrorDTO}},
)
def get_canon_chapter(
    chapter_id: str, session: Annotated[Session, Depends(get_session)]
) -> CanonChapterDTO:
    try:
        chapter = read_canon_chapter(session, chapter_id)
    except CatalogError as exc:
        raise _catalog_http(exc) from exc
    return CanonChapterDTO(
        novel_id=chapter.novel_id,
        chapter_id=chapter.chapter_id,
        sequence=chapter.sequence,
        original_label=chapter.original_label,
        original_title=chapter.original_title,
        display_title=chapter.display_title,
        title_source=chapter.title_source,
        body=chapter.body,
        version_id=chapter.version_id,
        version_kind=chapter.version_kind,
        is_canon=chapter.is_canon,
        has_draft=chapter.has_draft,
        previous=_nav_dto(chapter.previous),
        next=_nav_dto(chapter.next),
    )


@router.get(
    "/api/chapters/{chapter_id}/versions/{version_id}",
    response_model=ChapterVersionDTO,
    responses={404: {"model": ImportErrorDTO}},
)
def get_chapter_version(
    chapter_id: str,
    version_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> ChapterVersionDTO:
    try:
        version = read_chapter_version(session, chapter_id, version_id)
    except CatalogError as exc:
        raise _catalog_http(exc) from exc
    return ChapterVersionDTO(
        novel_id=version.novel_id,
        chapter_id=version.chapter_id,
        version_id=version.version_id,
        version_kind=version.version_kind,
        body=version.body,
        is_canon=version.is_canon,
        created_at=version.created_at,
        import_source_id=version.import_source_id,
        parent_version_id=version.parent_version_id,
    )
