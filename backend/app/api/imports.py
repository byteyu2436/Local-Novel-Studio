from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.adapters.sqlite.models import ImportSource
from app.api.deps import get_session
from app.domain.importing import ImportValidationError, ParseStatus, SourceType
from app.schemas.imports import ImportErrorDTO, ImportSourceDTO, ImportTextDTO, PasteImportRequest
from app.services.importer import import_pasted_text, require_import_source

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _char_count(source: ImportSource) -> int:
    return len(source.raw_text) if source.raw_text is not None else 0


def _to_dto(source: ImportSource, *, include_text: bool) -> ImportSourceDTO:
    normalized = source.normalized.text if source.normalized is not None else None
    return ImportSourceDTO(
        id=source.id,
        source_type=SourceType(source.source_type),
        checksum=source.checksum,
        created_at=source.created_at,
        parse_status=ParseStatus(source.parse_status),
        original_filename=source.original_filename,
        original_storage_path=source.original_storage_path,
        raw_byte_size=source.raw_byte_size,
        raw_char_count=_char_count(source),
        has_normalized_text=normalized is not None,
        raw_text=source.raw_text if include_text else None,
        normalized_text=normalized if include_text else None,
    )


@router.post(
    "/paste",
    response_model=ImportSourceDTO,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ImportErrorDTO},
        500: {"model": ImportErrorDTO},
    },
)
def paste_import(
    payload: PasteImportRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ImportSourceDTO:
    try:
        outcome = import_pasted_text(session, payload.text)
    except ImportValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message, "import_source_id": None},
        ) from exc

    if not outcome.ok:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": outcome.error_code,
                "message": outcome.error_message or "Normalization failed.",
                "import_source_id": outcome.source_id,
            },
        )
    return _to_dto(require_import_source(session, outcome.source_id), include_text=True)


@router.get("/{source_id}", response_model=ImportSourceDTO)
def get_import(
    source_id: str, session: Annotated[Session, Depends(get_session)]
) -> ImportSourceDTO:
    try:
        source = require_import_source(session, source_id)
    except ImportValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": exc.message, "import_source_id": source_id},
        ) from exc
    return _to_dto(source, include_text=True)


@router.get("/{source_id}/raw", response_model=ImportTextDTO)
def get_import_raw(
    source_id: str, session: Annotated[Session, Depends(get_session)]
) -> ImportTextDTO:
    try:
        source = require_import_source(session, source_id)
    except ImportValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": exc.message, "import_source_id": source_id},
        ) from exc
    if source.raw_text is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "import_raw_unavailable",
                "message": "This import has a file snapshot instead of pasted text.",
                "import_source_id": source_id,
            },
        )
    return ImportTextDTO(import_source_id=source.id, kind="raw", text=source.raw_text)


@router.get("/{source_id}/normalized", response_model=ImportTextDTO)
def get_import_normalized(
    source_id: str, session: Annotated[Session, Depends(get_session)]
) -> ImportTextDTO:
    try:
        source = require_import_source(session, source_id)
    except ImportValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": exc.message, "import_source_id": source_id},
        ) from exc
    if source.normalized is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "import_normalized_unavailable",
                "message": "Normalized text is not available for this import.",
                "import_source_id": source_id,
            },
        )
    return ImportTextDTO(
        import_source_id=source.id,
        kind="normalized",
        text=source.normalized.text,
    )
