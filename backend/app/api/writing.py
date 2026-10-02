import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.adapters.embedding.ollama import OllamaEmbeddingAdapter
from app.adapters.milvus.collections import MilvusCollectionClient
from app.adapters.ollama import create_llm_provider
from app.api.deps import get_session
from app.domain.catalog import CatalogError
from app.domain.context_budget import ContextBudgetError
from app.domain.jobs import JobError
from app.schemas.plan import ChapterPlan
from app.services.accept import accept_draft
from app.services.consistency import check_draft, list_issues
from app.services.context_builder import build_context
from app.services.drafts import (
    DraftError,
    draft_view,
    get_draft,
    list_drafts,
    restore_draft,
    rewrite_draft,
    save_draft,
)
from app.services.jobs import get_job
from app.services.planner import generate_plan
from app.services.plans import (
    PlanError,
    confirm_plan,
    edit_plan,
    get_plan,
    list_plans,
    plan_view,
    reorder_scenes,
)
from app.services.scene_writer import cancel_scene, generate_scene, resume_scene
from app.settings import get_settings

router = APIRouter(tags=["writing"])


class ContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_goal: str = ""
    plan_text: str = ""
    plan_id: str = ""
    evidence: list[dict] | None = None


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_goal: str
    target_sequence: int = Field(ge=1)
    locked_facts: list[str] = Field(default_factory=list)


class ReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_ids: list[str] = Field(min_length=1)


class SceneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    scene_id: str


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_sequence: int = Field(ge=1)
    body: str
    plan_id: str | None = None


class RewriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(ge=1)
    instruction: str = Field(min_length=1)


class AcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str


def _llm(request: Request):
    provider = getattr(request.app.state, "llm_provider", None)
    return provider if provider is not None else create_llm_provider(request.app.state.settings)


def _embedding(request: Request):
    provider = getattr(request.app.state, "embedding_provider", None)
    return provider if provider is not None else OllamaEmbeddingAdapter(request.app.state.settings)


def _milvus(request: Request) -> MilvusCollectionClient:
    client = getattr(request.app.state, "milvus_client", None)
    return client if client is not None else MilvusCollectionClient(request.app.state.settings)


def _http(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "writing_failed")
    message = getattr(exc, "message", str(exc))
    missing = {
        "novel_not_found",
        "plan_not_found",
        "draft_not_found",
        "scene_job_not_found",
        "job_not_found",
    }
    if code == "chapter_goal_empty":
        status_code = status.HTTP_400_BAD_REQUEST
    elif code in missing:
        status_code = status.HTTP_404_NOT_FOUND
    else:
        status_code = status.HTTP_409_CONFLICT
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _profile():
    from app.adapters.llm.profiles import default_model_profiles
    from app.adapters.llm.types import ModelRole

    return default_model_profiles(get_settings())[ModelRole.WRITER]


@router.post("/api/novels/{novel_id}/context")
def build_novel_context(
    novel_id: str,
    body: ContextRequest,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        manifest = build_context(
            session,
            novel_id,
            _profile(),
            chapter_goal=body.chapter_goal,
            evidence=body.evidence,
            plan_text=body.plan_text,
            plan_id=body.plan_id,
        )
        return manifest.model_dump()
    except (ContextBudgetError, CatalogError) as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/plans")
async def create_plan(
    novel_id: str,
    body: PlanRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        return await generate_plan(
            session,
            _llm(request),
            novel_id,
            chapter_goal=body.chapter_goal,
            target_sequence=body.target_sequence,
            locked_facts=body.locked_facts,
        )
    except (PlanError, ContextBudgetError, CatalogError) as exc:
        raise _http(exc) from exc


@router.get("/api/novels/{novel_id}/plans")
def read_plans(novel_id: str, session: Annotated[Session, Depends(get_session)]) -> dict:
    try:
        return {"plans": list_plans(session, novel_id)}
    except CatalogError as exc:
        raise _http(exc) from exc


@router.get("/api/novels/{novel_id}/plans/{plan_id}")
def read_plan(
    novel_id: str, plan_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        return plan_view(get_plan(session, novel_id, plan_id))
    except PlanError as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/plans/{plan_id}/edit")
def edit_existing_plan(
    novel_id: str,
    plan_id: str,
    body: ChapterPlan,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        return plan_view(edit_plan(session, novel_id, plan_id, body))
    except (PlanError, CatalogError) as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/plans/{plan_id}/reorder")
def reorder_plan(
    novel_id: str,
    plan_id: str,
    body: ReorderRequest,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        return plan_view(reorder_scenes(session, novel_id, plan_id, body.scene_ids))
    except PlanError as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/plans/{plan_id}/regenerate")
async def regenerate_plan(
    novel_id: str,
    plan_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        current = get_plan(session, novel_id, plan_id)
        return await generate_plan(
            session,
            _llm(request),
            novel_id,
            chapter_goal=current.chapter_goal,
            target_sequence=current.target_sequence,
            parent_id=current.id,
        )
    except (PlanError, ContextBudgetError, CatalogError) as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/plans/{plan_id}/confirm")
def confirm_existing_plan(
    novel_id: str, plan_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        return plan_view(confirm_plan(session, novel_id, plan_id))
    except PlanError as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/scenes")
async def create_scene(
    novel_id: str,
    body: SceneRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        return await generate_scene(
            session, _llm(request), novel_id, plan_id=body.plan_id, scene_id=body.scene_id
        )
    except (DraftError, PlanError, ContextBudgetError, JobError) as exc:
        raise _http(exc) from exc


@router.get("/api/novels/{novel_id}/scenes/{job_id}")
def read_scene(
    novel_id: str, job_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        job = get_job(session, job_id)
        if job.novel_id != novel_id or job.kind != "GENERATE_SCENE":
            raise DraftError("scene_job_not_found", "找不到这个生成任务。")
        return {"job_id": job.id, "state": job.state, "checkpoint": job.checkpoint or {}}
    except (DraftError, JobError) as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/scenes/{job_id}/cancel")
def cancel_existing_scene(
    novel_id: str, job_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        return cancel_scene(session, novel_id, job_id)
    except (DraftError, JobError) as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/scenes/{job_id}/resume")
async def resume_existing_scene(
    novel_id: str,
    job_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        return await resume_scene(session, _llm(request), novel_id, job_id)
    except (DraftError, PlanError, ContextBudgetError, JobError) as exc:
        raise _http(exc) from exc


@router.get("/api/novels/{novel_id}/scenes/{job_id}/events")
async def scene_events(
    novel_id: str,
    job_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> StreamingResponse:
    try:
        job = get_job(session, job_id)
    except JobError as exc:
        raise _http(exc) from exc
    checkpoint = job.checkpoint or {}
    if job.novel_id != novel_id or job.kind != "GENERATE_SCENE":
        raise _http(DraftError("scene_job_not_found", "找不到这个生成任务。"))
    text = str(checkpoint.get("text") or "")

    async def events():
        payload = {"event": "chunk", "job_id": job.id, "state": job.state, "text": text}
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        done = {"event": "done", "job_id": job.id, "state": job.state, "text": text, "done": True}
        yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/api/novels/{novel_id}/drafts")
def read_drafts(novel_id: str, session: Annotated[Session, Depends(get_session)]) -> dict:
    try:
        return {"drafts": list_drafts(session, novel_id)}
    except CatalogError as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/drafts/{draft_id}/restore")
def restore_existing_draft(
    novel_id: str, draft_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        return draft_view(restore_draft(session, novel_id, draft_id))
    except (DraftError, CatalogError) as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/drafts")
def create_draft(
    novel_id: str,
    body: DraftRequest,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        row = save_draft(
            session,
            novel_id=novel_id,
            target_sequence=body.target_sequence,
            body=body.body,
            origin="user",
            plan_id=body.plan_id,
        )
        return draft_view(row)
    except (DraftError, CatalogError) as exc:
        raise _http(exc) from exc


@router.get("/api/novels/{novel_id}/drafts/{draft_id}")
def read_draft(
    novel_id: str, draft_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        return draft_view(get_draft(session, novel_id, draft_id))
    except DraftError as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/drafts/{draft_id}/rewrite")
async def rewrite_existing_draft(
    novel_id: str,
    draft_id: str,
    body: RewriteRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        row = await rewrite_draft(
            session,
            _llm(request),
            novel_id,
            draft_id,
            start=body.start,
            end=body.end,
            instruction=body.instruction,
        )
        return draft_view(row)
    except (DraftError, CatalogError) as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/drafts/{draft_id}/consistency")
async def check_existing_draft(
    novel_id: str,
    draft_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        return await check_draft(session, _llm(request), novel_id, draft_id)
    except (DraftError, ContextBudgetError, JobError) as exc:
        raise _http(exc) from exc


@router.get("/api/novels/{novel_id}/drafts/{draft_id}/issues")
def read_issues(
    novel_id: str, draft_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        return {"issues": list_issues(session, novel_id, draft_id)}
    except DraftError as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/drafts/{draft_id}/accept")
async def accept_existing_draft(
    novel_id: str,
    draft_id: str,
    body: AcceptRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        return await accept_draft(
            session,
            novel_id,
            draft_id,
            body.plan_id,
            llm=getattr(request.app.state, "llm_provider", None),
            embedding=getattr(request.app.state, "embedding_provider", None),
            milvus=getattr(request.app.state, "milvus_client", None),
        )
    except (DraftError, PlanError, CatalogError, JobError) as exc:
        raise _http(exc) from exc
