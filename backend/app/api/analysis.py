from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.adapters.ollama import create_llm_provider
from app.adapters.sqlite.models import Job
from app.api.deps import get_session
from app.domain.catalog import CatalogError
from app.domain.jobs import JobError, JobKind
from app.schemas.jobs import AnalysisJobProgressDTO, AnalysisRecoveryReportDTO, JobErrorDTO
from app.services import catalog, jobs
from app.services.analysis_orchestrator import (
    cancel_novel_analysis,
    find_active_analysis_job,
    job_progress,
    pause_novel_analysis,
    resume_novel_analysis,
    retry_failed_chapter,
    run_novel_analysis,
)
from app.services.analysis_recovery import analysis_recovery_report

router = APIRouter(tags=["analysis"])


def _catalog_http(exc: CatalogError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND if exc.code == "novel_not_found" else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message})


def _job_http(exc: JobError) -> HTTPException:
    not_found = {"job_not_found", "analysis_job_not_found", "analysis_unit_not_found"}
    code = status.HTTP_404_NOT_FOUND if exc.code in not_found else status.HTTP_409_CONFLICT
    return HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message})


def _require_analysis_job(session: Session, job_id: str) -> Job:
    try:
        job = jobs.get_job(session, job_id)
    except JobError as exc:
        raise _job_http(exc) from exc
    if job.kind != JobKind.ANALYZE_CHAPTER.value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "analysis_job_not_found", "message": "Analysis job does not exist."},
        )
    session.refresh(job, attribute_names=["units"])
    return job


@router.post(
    "/api/novels/{novel_id}/analysis-jobs",
    response_model=AnalysisJobProgressDTO,
    responses={
        400: {"model": JobErrorDTO},
        404: {"model": JobErrorDTO},
        409: {"model": JobErrorDTO},
    },
)
async def start_novel_analysis(
    novel_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AnalysisJobProgressDTO:
    provider = create_llm_provider(request.app.state.settings)
    try:
        job = await run_novel_analysis(session, novel_id, provider)
    except CatalogError as exc:
        raise _catalog_http(exc) from exc
    except JobError as exc:
        raise _job_http(exc) from exc
    return job_progress(job)


@router.get(
    "/api/novels/{novel_id}/analysis-jobs",
    response_model=AnalysisJobProgressDTO,
    responses={404: {"model": JobErrorDTO}},
)
def get_novel_analysis_job(
    novel_id: str, session: Annotated[Session, Depends(get_session)]
) -> AnalysisJobProgressDTO:
    try:
        catalog.require_novel(session, novel_id)
    except CatalogError as exc:
        raise _catalog_http(exc) from exc
    job = find_active_analysis_job(session, novel_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "analysis_job_not_found",
                "message": "Novel has no analysis job.",
            },
        )
    return job_progress(job)


@router.get("/api/analysis-jobs/recovery", response_model=AnalysisRecoveryReportDTO)
def get_analysis_recovery(
    session: Annotated[Session, Depends(get_session)],
) -> AnalysisRecoveryReportDTO:
    return AnalysisRecoveryReportDTO(jobs=analysis_recovery_report(session))


@router.get(
    "/api/analysis-jobs/{job_id}",
    response_model=AnalysisJobProgressDTO,
    responses={404: {"model": JobErrorDTO}},
)
def get_analysis_job(
    job_id: str, session: Annotated[Session, Depends(get_session)]
) -> AnalysisJobProgressDTO:
    job = _require_analysis_job(session, job_id)
    return job_progress(job)


@router.post(
    "/api/analysis-jobs/{job_id}/pause",
    response_model=AnalysisJobProgressDTO,
    responses={404: {"model": JobErrorDTO}, 409: {"model": JobErrorDTO}},
)
def pause_analysis_job(
    job_id: str, session: Annotated[Session, Depends(get_session)]
) -> AnalysisJobProgressDTO:
    try:
        job = pause_novel_analysis(session, job_id)
    except JobError as exc:
        raise _job_http(exc) from exc
    return job_progress(job)


@router.post(
    "/api/analysis-jobs/{job_id}/resume",
    response_model=AnalysisJobProgressDTO,
    responses={404: {"model": JobErrorDTO}, 409: {"model": JobErrorDTO}},
)
async def resume_analysis_job(
    job_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AnalysisJobProgressDTO:
    provider = create_llm_provider(request.app.state.settings)
    try:
        job = await resume_novel_analysis(session, job_id, provider)
    except JobError as exc:
        raise _job_http(exc) from exc
    return job_progress(job)


@router.post(
    "/api/analysis-jobs/{job_id}/cancel",
    response_model=AnalysisJobProgressDTO,
    responses={404: {"model": JobErrorDTO}, 409: {"model": JobErrorDTO}},
)
def cancel_analysis_job(
    job_id: str, session: Annotated[Session, Depends(get_session)]
) -> AnalysisJobProgressDTO:
    try:
        job = cancel_novel_analysis(session, job_id)
    except JobError as exc:
        raise _job_http(exc) from exc
    return job_progress(job)


@router.post(
    "/api/analysis-jobs/{job_id}/chapters/{chapter_id}/retry",
    response_model=AnalysisJobProgressDTO,
    responses={404: {"model": JobErrorDTO}, 409: {"model": JobErrorDTO}},
)
async def retry_analysis_chapter(
    job_id: str,
    chapter_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AnalysisJobProgressDTO:
    provider = create_llm_provider(request.app.state.settings)
    try:
        job = await retry_failed_chapter(session, job_id, chapter_id, provider)
    except JobError as exc:
        raise _job_http(exc) from exc
    return job_progress(job)
