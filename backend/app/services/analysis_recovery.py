from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.adapters.sqlite.models import Job
from app.domain.jobs import JobKind, JobState, UnitState
from app.schemas.jobs import AnalysisRecoveryItemDTO
from app.services import jobs

STALE_ANALYSIS_HEARTBEAT = timedelta(seconds=90)
_OPEN_STATES = (
    JobState.QUEUED.value,
    JobState.RUNNING.value,
    JobState.PAUSED.value,
    JobState.FAILED.value,
)


def recommended_action(job: Job) -> str:
    unit_states = {unit.state for unit in job.units}
    if job.state == JobState.PAUSED.value and UnitState.QUEUED.value in unit_states:
        return "resume"
    if job.state == JobState.FAILED.value and UnitState.FAILED.value in unit_states:
        return "retry_failed"
    if job.state == JobState.QUEUED.value:
        return "start"
    if job.state == JobState.RUNNING.value:
        return "wait"
    return "none"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _is_stale(job: Job, now: datetime, stale_after: timedelta) -> bool:
    if job.heartbeat_at is None:
        return True
    return now - _aware(job.heartbeat_at) >= stale_after


def _interrupted_ids(job: Job) -> list[str]:
    return [
        unit.chapter_id
        for unit in job.units
        if unit.state == UnitState.QUEUED.value
        and (unit.checkpoint or {}).get("recovered_from") == "running"
    ]


def _open_analysis_jobs(session: Session) -> list[Job]:
    return list(
        session.scalars(
            select(Job)
            .options(selectinload(Job.units))
            .where(Job.kind == JobKind.ANALYZE_CHAPTER.value, Job.state.in_(_OPEN_STATES))
            .order_by(Job.created_at, Job.id)
        )
    )


def recover_analysis_jobs(
    session: Session,
    *,
    now: datetime | None = None,
    stale_after: timedelta = STALE_ANALYSIS_HEARTBEAT,
) -> list[Job]:
    """Requeue chapters left running by a dead process. Do not call the model."""

    current = now or datetime.now(UTC)
    found = _open_analysis_jobs(session)
    for job in found:
        if job.state == JobState.RUNNING.value and _is_stale(job, current, stale_after):
            for unit in job.units:
                jobs.requeue_interrupted_analysis_unit(session, unit)
            jobs.pause_job(session, job)
            job.checkpoint = {
                "current_chapter_id": None,
                "recommended_action": "resume",
            }
        elif job.state == JobState.PAUSED.value:
            for unit in job.units:
                jobs.requeue_interrupted_analysis_unit(session, unit)
    session.commit()
    return found


def analysis_recovery_report(
    session: Session,
    *,
    now: datetime | None = None,
    stale_after: timedelta = STALE_ANALYSIS_HEARTBEAT,
) -> list[AnalysisRecoveryItemDTO]:
    recover_analysis_jobs(session, now=now, stale_after=stale_after)
    return [
        AnalysisRecoveryItemDTO(
            job_id=job.id,
            novel_id=job.novel_id,
            state=job.state,
            recommended_action=recommended_action(job),
            interrupted_chapter_ids=_interrupted_ids(job),
            completed=job.progress_done,
            total=job.progress_total,
        )
        for job in _open_analysis_jobs(session)
    ]
