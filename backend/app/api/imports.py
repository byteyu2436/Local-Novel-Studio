from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.adapters.sqlite.models import ImportSource
from app.api.deps import get_session
from app.domain.importing import ImportValidationError, ParseStatus, SourceType, sha256_hex
from app.schemas.imports import (
    ImportErrorDTO,
    ImportSourceDTO,
    ImportTextDTO,
    PasteImportRequest,
    TxtPreviewDTO,
)
from app.services.importer import (
    import_pasted_text,
    import_txt_file,
    original_txt_bytes,
    preview_txt_file,
    require_import_source,
)
from app.storage.imports import original_txt_path

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _char_count(source: ImportSource) -> int:
    if source.raw_text is not None:
        return len(source.raw_text)
    if source.normalized is not None:
        return len(source.normalized.text)
    return 0


def _http_error(
    exc: ImportValidationError,
    *,
    status_code: int,
    source_id: str | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message, "import_source_id": source_id},
    )


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
        detected_encoding=source.detected_encoding,
        encoding_uncertain=source.encoding_uncertain,
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


@router.post(
    "/txt/preview",
    response_model=TxtPreviewDTO,
    responses={400: {"model": ImportErrorDTO}},
)
async def txt_preview(
    file: Annotated[UploadFile, File()],
    encoding: Annotated[str | None, Form()] = None,
) -> TxtPreviewDTO:
    payload = await file.read()
    override = encoding.strip() if encoding else None
    try:
        outcome = preview_txt_file(
            filename=file.filename or "",
            payload=payload,
            encoding=override,
        )
    except ImportValidationError as exc:
        raise _http_error(exc, status_code=status.HTTP_400_BAD_REQUEST) from exc
    return TxtPreviewDTO(
        original_filename=outcome.original_filename,
        raw_byte_size=outcome.raw_byte_size,
        detected_encoding=outcome.detected_encoding,
        encoding_uncertain=outcome.encoding_uncertain,
        preview_text=outcome.preview_text,
        preview_truncated=outcome.preview_truncated,
        char_count=outcome.char_count,
    )


@router.post(
    "/txt",
    response_model=ImportSourceDTO,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ImportErrorDTO},
        500: {"model": ImportErrorDTO},
    },
)
async def txt_import(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    file: Annotated[UploadFile, File()],
    encoding: Annotated[str | None, Form()] = None,
) -> ImportSourceDTO:
    payload = await file.read()
    override = encoding.strip() if encoding else None
    try:
        outcome = import_txt_file(
            session,
            request.app.state.settings,
            filename=file.filename or "",
            payload=payload,
            encoding=override,
        )
    except ImportValidationError as exc:
        raise _http_error(exc, status_code=status.HTTP_400_BAD_REQUEST) from exc

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


@router.get("/{source_id}/file")
def get_original_file(
    source_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    try:
        source = require_import_source(session, source_id)
        payload = original_txt_bytes(request.app.state.settings, source)
    except ImportValidationError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if exc.code in {"import_not_found", "txt_file_unavailable", "txt_file_missing"}
            else status.HTTP_400_BAD_REQUEST
        )
        raise _http_error(exc, status_code=code, source_id=source_id) from exc
    if sha256_hex(payload) != source.checksum:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "txt_checksum_mismatch",
                "message": "Original TXT file does not match the stored checksum.",
                "import_source_id": source_id,
            },
        )
    path = original_txt_path(request.app.state.settings, source.original_storage_path or "")
    return FileResponse(
        path,
        media_type="text/plain",
        filename=source.original_filename or "original.txt",
    )


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
