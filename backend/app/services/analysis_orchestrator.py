from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.adapters.llm.types import LLMProvider
from app.adapters.sqlite.models import Chapter, ChapterVersion, Job
from app.domain.analysis import CHAPTER_ANALYSIS_SCHEMA_VERSION, AnalysisError
from app.domain.catalog import CatalogError
from app.domain.jobs import JobKind, JobState, UnitState
from app.prompts.chapter_analyzer import CHAPTER_ANALYZER_PROMPT_VERSION
from app.schemas.jobs import AnalysisJobProgressDTO
from app.services import catalog, jobs
from app.services.analysis import get_chapter_analysis, persist_chapter_analysis
from app.services.analysis_recovery import recommended_action
from app.services.chapter_analyzer import analyze_chapter_text


def analysis_job_fingerprint(novel_id: str) -> str:
    return jobs.job_fingerprint(
        novel_id=novel_id,
        kind=JobKind.ANALYZE_CHAPTER.value,
        extra=f"{CHAPTER_ANALYSIS_SCHEMA_VERSION}:{CHAPTER_ANALYZER_PROMPT_VERSION}",
    )


def find_active_analysis_job(session: Session, novel_id: str) -> Job | None:
    fingerprint = analysis_job_fingerprint(novel_id)
    return session.scalar(
        select(Job)
        .options(selectinload(Job.units))
        .where(
            Job.novel_id == novel_id,
            Job.kind == JobKind.ANALYZE_CHAPTER.value,
            Job.input_fingerprint == fingerprint,
            Job.state != JobState.CANCELLED.value,
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )


def job_progress(job: Job) -> AnalysisJobProgressDTO:
    failed = [unit.chapter_id for unit in job.units if unit.state == UnitState.FAILED.value]
    current = next(
        (unit.chapter_id for unit in job.units if unit.state == UnitState.RUNNING.value),
        None,
    )
    return AnalysisJobProgressDTO(
        job_id=job.id,
        novel_id=job.novel_id,
        state=job.state,
        total=job.progress_total,
        completed=job.progress_done,
        failed_chapter_ids=failed,
        current_chapter_id=current,
        recommended_action=recommended_action(job),
    )


def _ensure_units(session: Session, job: Job, chapters: list[Chapter]) -> None:
    existing = {unit.chapter_id for unit in job.units}
    for chapter in chapters:
        if chapter.id in existing:
            continue
        jobs.add_analysis_unit(
            session,
            job,
            chapter,
            schema_version=CHAPTER_ANALYSIS_SCHEMA_VERSION,
            analyzer_version=CHAPTER_ANALYZER_PROMPT_VERSION,
            prompt_version=CHAPTER_ANALYZER_PROMPT_VERSION,
        )


def _reload_job(session: Session, job: Job) -> Job:
    for unit in list(job.units):
        session.expire(unit)
    session.expire(job, ["units"])
    session.refresh(job)
    list(job.units)
    return job


def _success_checkpoint(unit, **extra: object) -> dict:
    checkpoint = dict(extra)
    previous = unit.checkpoint or {}
    if previous.get("last_error_code"):
        checkpoint["last_error_code"] = previous["last_error_code"]
        checkpoint["last_error_message"] = previous.get("last_error_message")
    elif unit.error_code:
        checkpoint["last_error_code"] = unit.error_code
        checkpoint["last_error_message"] = unit.error_message
    return checkpoint


def _cancel_open_units(session: Session, job: Job) -> None:
    for unit in job.units:
        jobs.cancel_analysis_unit(session, unit)
    job.checkpoint = {"current_chapter_id": None}
    session.commit()


def _settle_job(session: Session, job: Job) -> Job:
    _reload_job(session, job)
    if job.state == JobState.CANCELLED.value:
        _cancel_open_units(session, job)
        return job
    if job.state == JobState.PAUSED.value:
        job.checkpoint = {"current_chapter_id": None}
        session.commit()
        return job
    if job.state != JobState.RUNNING.value:
        return job
    if any(unit.state == UnitState.FAILED.value for unit in job.units):
        jobs.fail_job(
            session, job, code="analysis_units_failed", message="One or more chapters failed."
        )
    elif all(unit.state == UnitState.COMPLETED.value for unit in job.units):
        job.error_code = None
        job.error_message = None
        jobs.transition_job(session, job, JobState.COMPLETED)
    job.checkpoint = {"current_chapter_id": None}
    session.commit()
    return job


def _prepare_job(session: Session, novel_id: str, chapters: list[Chapter]) -> Job:
    job = find_active_analysis_job(session, novel_id)
    if job is not None and job.state in {JobState.COMPLETED.value, JobState.PAUSED.value}:
        return job
    if job is None:
        job = jobs.create_job(
            session,
            kind=JobKind.ANALYZE_CHAPTER,
            novel_id=novel_id,
            input_fingerprint=analysis_job_fingerprint(novel_id),
        )
    elif job.state == JobState.FAILED.value:
        jobs.retry_job(session, job)
    if job.state != JobState.RUNNING.value:
        jobs.transition_job(session, job, JobState.RUNNING)
    _ensure_units(session, job, chapters)
    session.commit()
    return job


async def _analyze_unit(
    session: Session,
    job: Job,
    chapter: Chapter,
    provider: LLMProvider,
) -> None:
    _reload_job(session, job)
    if job.state in {JobState.PAUSED.value, JobState.CANCELLED.value}:
        return
    unit = next(item for item in job.units if item.chapter_id == chapter.id)
    if unit.state in {UnitState.COMPLETED.value, UnitState.CANCELLED.value}:
        return
    jobs.start_analysis_unit(session, unit)
    job.checkpoint = {"current_chapter_id": chapter.id}
    jobs.heartbeat_job(session, job)
    session.commit()

    canon_id = chapter.current_canon_version_id
    canon = session.get(ChapterVersion, canon_id) if canon_id is not None else None
    if canon is None:
        jobs.fail_analysis_unit(
            session, unit, code="canon_missing", message="Chapter has no Canon version."
        )
        session.commit()
        return

    existing = get_chapter_analysis(session, chapter.id, canon.id)
    if existing is not None:
        jobs.complete_analysis_unit(
            session,
            unit,
            analysis_id=existing.id,
            checkpoint=_success_checkpoint(unit, reused=True),
        )
        session.commit()
        return

    try:
        result = await analyze_chapter_text(
            provider,
            canon.body,
            chapter_id=chapter.id,
            source_version_id=canon.id,
        )
        saved = persist_chapter_analysis(
            session,
            chapter,
            canon,
            payload=result.payload,
            analyzer_version=result.analyzer_version,
            model_profile_id=result.model_profile_id,
            prompt_version=result.prompt_version,
            profile_version=result.profile_version,
            model_ref=result.model_ref,
        )
    except AnalysisError as exc:
        jobs.fail_analysis_unit(session, unit, code=exc.code, message=exc.message)
        session.commit()
        return

    jobs.complete_analysis_unit(
        session,
        unit,
        analysis_id=saved.id,
        checkpoint=_success_checkpoint(unit, attempts=result.attempts, repaired=result.repaired),
    )
    session.commit()


async def run_novel_analysis(
    session: Session,
    novel_id: str,
    provider: LLMProvider,
) -> Job:
    """Analyze each Canon chapter. One failure does not stop the remaining chapters."""

    catalog.require_novel(session, novel_id)
    chapters = catalog.list_chapters(session, novel_id)
    if not chapters:
        raise CatalogError("chapters_empty", "Novel has no chapters to analyze.")
    job = _prepare_job(session, novel_id, chapters)
    if job.state in {JobState.COMPLETED.value, JobState.PAUSED.value}:
        return job
    return await _run_chapters(session, job, chapters, provider)


async def _run_chapters(
    session: Session,
    job: Job,
    chapters: list[Chapter],
    provider: LLMProvider,
) -> Job:
    for chapter in chapters:
        _reload_job(session, job)
        if job.state == JobState.PAUSED.value:
            break
        if job.state == JobState.CANCELLED.value:
            break
        await _analyze_unit(session, job, chapter, provider)
    return _settle_job(session, job)


def pause_novel_analysis(session: Session, job_id: str) -> Job:
    job = _require_analysis_job(session, job_id)
    if job.state != JobState.PAUSED.value:
        jobs.pause_job(session, job)
        session.commit()
    return job


def cancel_novel_analysis(session: Session, job_id: str) -> Job:
    job = _require_analysis_job(session, job_id)
    if job.state != JobState.CANCELLED.value:
        jobs.cancel_job(session, job)
    _cancel_open_units(session, job)
    return job


async def resume_novel_analysis(session: Session, job_id: str, provider: LLMProvider) -> Job:
    job = _require_analysis_job(session, job_id)
    if job.state in {JobState.RUNNING.value, JobState.COMPLETED.value}:
        return job
    if job.state != JobState.PAUSED.value:
        raise jobs.JobError(
            "illegal_job_transition",
            f"Cannot move job from {job.state} to {JobState.RUNNING.value}.",
        )
    jobs.resume_job(session, job)
    session.commit()
    chapters = catalog.list_chapters(session, job.novel_id or "")
    return await _run_chapters(session, job, chapters, provider)


async def retry_failed_chapter(
    session: Session,
    job_id: str,
    chapter_id: str,
    provider: LLMProvider,
) -> Job:
    job = _require_analysis_job(session, job_id)
    unit = next((item for item in job.units if item.chapter_id == chapter_id), None)
    if unit is None:
        raise jobs.JobError("analysis_unit_not_found", "Chapter is not part of this analysis job.")
    if unit.state != UnitState.FAILED.value:
        return job
    kept_retry_count = unit.retry_count
    jobs.requeue_failed_analysis_unit(session, unit)
    unit.retry_count = kept_retry_count
    if job.state == JobState.FAILED.value:
        jobs.retry_job(session, job)
    elif job.state == JobState.PAUSED.value:
        jobs.resume_job(session, job)
    elif job.state != JobState.RUNNING.value:
        raise jobs.JobError(
            "illegal_job_transition",
            f"Cannot retry a chapter while the job is {job.state}.",
        )
    if job.state != JobState.RUNNING.value:
        jobs.transition_job(session, job, JobState.RUNNING)
    session.commit()
    chapter = catalog.require_chapter(session, chapter_id)
    await _analyze_unit(session, job, chapter, provider)
    return _settle_job(session, job)


def _require_analysis_job(session: Session, job_id: str) -> Job:
    job = session.scalar(select(Job).options(selectinload(Job.units)).where(Job.id == job_id))
    if job is None or job.kind != JobKind.ANALYZE_CHAPTER.value:
        raise jobs.JobError("analysis_job_not_found", "Analysis job does not exist.")
    return job
