from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.sqlite.models import AnalysisChapterUnit, Chapter, Job, Novel
from app.domain.jobs import JobError, JobKind, JobState, UnitState, require_job_transition


def _now() -> datetime:
    return datetime.now(UTC)


def job_fingerprint(*, novel_id: str, kind: str, extra: str = "") -> str:
    return sha256(f"{kind}:{novel_id}:{extra}".encode()).hexdigest()


def create_job(
    session: Session,
    *,
    kind: JobKind | str,
    novel_id: str | None = None,
    progress_total: int = 0,
    input_fingerprint: str | None = None,
) -> Job:
    resolved_kind = JobKind(kind)
    if novel_id is not None and session.get(Novel, novel_id) is None:
        raise JobError("novel_not_found", "Novel does not exist.")
    now = _now()
    job = Job(
        id=str(uuid4()),
        kind=resolved_kind.value,
        state=JobState.QUEUED.value,
        novel_id=novel_id,
        progress_done=0,
        progress_total=progress_total,
        checkpoint=None,
        retry_count=0,
        input_fingerprint=input_fingerprint
        or job_fingerprint(novel_id=novel_id or "", kind=resolved_kind.value),
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.flush()
    return job


def get_job(session: Session, job_id: str) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise JobError("job_not_found", "Job does not exist.")
    return job


def transition_job(session: Session, job: Job, target: JobState | str) -> Job:
    dest = JobState(target)
    require_job_transition(job.state, dest)
    if JobState(job.state) is dest:
        return job
    now = _now()
    if dest is JobState.RUNNING and job.started_at is None:
        job.started_at = now
        job.heartbeat_at = now
    if dest is JobState.RUNNING:
        job.heartbeat_at = now
    job.state = dest.value
    job.updated_at = now
    session.flush()
    return job


def heartbeat_job(session: Session, job: Job) -> Job:
    if job.state != JobState.RUNNING.value:
        raise JobError("illegal_job_transition", "Heartbeat requires a running job.")
    job.heartbeat_at = _now()
    job.updated_at = job.heartbeat_at
    session.flush()
    return job


def pause_job(session: Session, job: Job) -> Job:
    return transition_job(session, job, JobState.PAUSED)


def resume_job(session: Session, job: Job) -> Job:
    return transition_job(session, job, JobState.RUNNING)


def cancel_job(session: Session, job: Job) -> Job:
    return transition_job(session, job, JobState.CANCELLED)


def fail_job(session: Session, job: Job, *, code: str, message: str) -> Job:
    job.error_code = code
    job.error_message = message
    return transition_job(session, job, JobState.FAILED)


def retry_job(session: Session, job: Job) -> Job:
    require_job_transition(job.state, JobState.QUEUED)
    job.retry_count += 1
    return transition_job(session, job, JobState.QUEUED)


def add_analysis_unit(
    session: Session,
    job: Job,
    chapter: Chapter,
    *,
    schema_version: str,
    analyzer_version: str,
    prompt_version: str,
) -> AnalysisChapterUnit:
    if job.kind != JobKind.ANALYZE_CHAPTER.value:
        raise JobError("illegal_job_kind", "Chapter units require ANALYZE_CHAPTER jobs.")
    if chapter.current_canon_version_id is None:
        raise JobError("analysis_requires_current_canon", "Chapter has no Canon version.")
    now = _now()
    unit = AnalysisChapterUnit(
        id=str(uuid4()),
        job_id=job.id,
        chapter_id=chapter.id,
        source_version_id=chapter.current_canon_version_id,
        state=UnitState.QUEUED.value,
        schema_version=schema_version,
        analyzer_version=analyzer_version,
        prompt_version=prompt_version,
        created_at=now,
        updated_at=now,
    )
    session.add(unit)
    job.progress_total = int(job.progress_total) + 1
    job.updated_at = now
    session.flush()
    return unit


def complete_analysis_unit(
    session: Session, unit: AnalysisChapterUnit, *, analysis_id: str, checkpoint: dict | None = None
) -> AnalysisChapterUnit:
    job = unit.job
    unit.state = UnitState.COMPLETED.value
    unit.analysis_id = analysis_id
    unit.checkpoint = checkpoint
    unit.updated_at = _now()
    job.progress_done = int(job.progress_done) + 1
    job.updated_at = unit.updated_at
    session.flush()
    return unit


def fail_analysis_unit(
    session: Session, unit: AnalysisChapterUnit, *, code: str, message: str
) -> AnalysisChapterUnit:
    unit.state = UnitState.FAILED.value
    unit.error_code = code
    unit.error_message = message
    unit.retry_count += 1
    unit.updated_at = _now()
    session.flush()
    return unit


def list_jobs(session: Session, *, novel_id: str | None = None) -> list[Job]:
    stmt = select(Job).order_by(Job.created_at, Job.id)
    if novel_id is not None:
        stmt = stmt.where(Job.novel_id == novel_id)
    return list(session.scalars(stmt))
