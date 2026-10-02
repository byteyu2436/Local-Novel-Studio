from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.embedding.ollama import OllamaEmbeddingAdapter
from app.adapters.milvus.collections import MilvusCollectionClient
from app.api.deps import get_session
from app.domain.catalog import CatalogError
from app.schemas.retrieval import QueryBuilderInput
from app.services.retrieval import RetrievalServiceError, retrieve_evidence

router = APIRouter(tags=["retrieval"])


class RetrievalRequest(BaseModel):
    chapter_goal: str = ""
    current_scene: str = ""
    characters: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    previous_chapter_state: str = ""
    top_n: int = Field(default=8, ge=1, le=100)


def _embedding_provider(request: Request):
    provider = getattr(request.app.state, "embedding_provider", None)
    if provider is not None:
        return provider
    return OllamaEmbeddingAdapter(request.app.state.settings)


def _milvus_client(request: Request) -> MilvusCollectionClient:
    client = getattr(request.app.state, "milvus_client", None)
    if client is not None:
        return client
    return MilvusCollectionClient(request.app.state.settings)


@router.post("/api/novels/{novel_id}/retrieval")
async def retrieve_novel(
    novel_id: str,
    body: RetrievalRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    debug: Annotated[bool, Query()] = False,
) -> dict:
    try:
        report = await retrieve_evidence(
            session,
            _milvus_client(request),
            _embedding_provider(request),
            QueryBuilderInput(novel_id=novel_id, **body.model_dump()),
            debug=debug,
        )
    except CatalogError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except RetrievalServiceError as exc:
        code = status.HTTP_409_CONFLICT
        if exc.code in {"embedding_unavailable", "milvus_unavailable"}:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
        if exc.code in {"query_text_empty", "draft_retrieval_unsupported"}:
            code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(
            status_code=code, detail={"code": exc.code, "message": exc.message}
        ) from exc
    payload = {
        "novel_id": report.result.novel_id,
        "evidence": [item.model_dump(mode="json") for item in report.result.evidence],
        "scoring_profile_version": report.result.scoring_profile_version,
        "embedding_profile_id": report.result.embedding_profile_id,
        "index_version": report.result.index_version,
        "collection_name": report.result.collection_name,
        "query_builder_version": report.query_builder_version,
        "selection_version": report.selection_version,
        "elapsed_ms": report.elapsed_ms,
        "empty": report.empty,
    }
    if debug and report.trace is not None:
        payload["trace"] = report.trace.model_dump(mode="json")
    return payload
