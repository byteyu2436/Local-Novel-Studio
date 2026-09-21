from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.domain.catalog import CatalogError
from app.schemas.imports import ImportErrorDTO
from app.schemas.reader import ChapterTocItemDTO, NovelChapterTocDTO
from app.services.reader import novel_chapter_toc

router = APIRouter(tags=["reader"])


def _catalog_http(exc: CatalogError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if exc.code in {"novel_not_found", "chapter_not_found"}
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
