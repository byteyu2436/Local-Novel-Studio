from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.adapters.embedding.ollama import OllamaEmbeddingAdapter
from app.adapters.milvus.collections import MilvusCollectionClient
from app.api.deps import get_session
from app.domain.catalog import CatalogError
from app.domain.jobs import JobError
from app.services.initialization import (
    InitializationError,
    cancel_initialization,
    execute_initialization,
    initialization_status,
    pause_initialization,
    resume_initialization,
    retry_initialization,
    writing_gate,
)

router = APIRouter(tags=["initialization"])


def _embedding(request: Request):
    provider = getattr(request.app.state, "embedding_provider", None)
    return provider if provider is not None else OllamaEmbeddingAdapter(request.app.state.settings)


def _milvus(request: Request) -> MilvusCollectionClient:
    client = getattr(request.app.state, "milvus_client", None)
    return client if client is not None else MilvusCollectionClient(request.app.state.settings)


def _llm(request: Request):
    return getattr(request.app.state, "llm_provider", None)


def _http(exc: InitializationError | CatalogError | JobError) -> HTTPException:
    missing = {"novel_not_found", "initialization_not_found"}
    code = status.HTTP_404_NOT_FOUND if exc.code in missing else status.HTTP_409_CONFLICT
    return HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message})


@router.post("/api/novels/{novel_id}/initialize")
async def initialize_novel(
    novel_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        await execute_initialization(
            session,
            _milvus(request),
            _embedding(request),
            novel_id,
            llm=_llm(request),
        )
        return initialization_status(session, novel_id)
    except (InitializationError, CatalogError, JobError) as exc:
        raise _http(exc) from exc


@router.get("/api/novels/{novel_id}/initialization")
def read_initialization(novel_id: str, session: Annotated[Session, Depends(get_session)]) -> dict:
    try:
        return initialization_status(session, novel_id)
    except CatalogError as exc:
        raise _http(exc) from exc


@router.get("/api/novels/{novel_id}/writing-gate")
def read_writing_gate(novel_id: str, session: Annotated[Session, Depends(get_session)]) -> dict:
    try:
        return writing_gate(session, novel_id)
    except CatalogError as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/initialization/pause")
def pause_novel(novel_id: str, session: Annotated[Session, Depends(get_session)]) -> dict:
    try:
        pause_initialization(session, novel_id)
        return initialization_status(session, novel_id)
    except (InitializationError, CatalogError, JobError) as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/initialization/resume")
async def resume_novel(
    novel_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        await resume_initialization(
            session, _milvus(request), _embedding(request), novel_id, llm=_llm(request)
        )
        return initialization_status(session, novel_id)
    except (InitializationError, CatalogError, JobError) as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/initialization/cancel")
def cancel_novel(novel_id: str, session: Annotated[Session, Depends(get_session)]) -> dict:
    try:
        cancel_initialization(session, novel_id)
        return initialization_status(session, novel_id)
    except (InitializationError, CatalogError, JobError) as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/initialization/retry")
async def retry_novel(
    novel_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        await retry_initialization(
            session, _milvus(request), _embedding(request), novel_id, llm=_llm(request)
        )
        return initialization_status(session, novel_id)
    except (InitializationError, CatalogError, JobError) as exc:
        raise _http(exc) from exc
