from enum import StrEnum


class JobKind(StrEnum):
    IMPORT = "IMPORT"
    INITIALIZE_NOVEL = "INITIALIZE_NOVEL"
    ANALYZE_CHAPTER = "ANALYZE_CHAPTER"
    MEMORY_REDUCE = "MEMORY_REDUCE"
    BATCH_EMBED = "BATCH_EMBED"
    REBUILD_INDEX = "REBUILD_INDEX"
    PLAN_CHAPTER = "PLAN_CHAPTER"
    GENERATE_SCENE = "GENERATE_SCENE"
    CHECK_CONSISTENCY = "CHECK_CONSISTENCY"
    UPDATE_MEMORY = "UPDATE_MEMORY"
    BACKUP = "BACKUP"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class UnitState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


TERMINAL_JOB_STATES = frozenset({JobState.COMPLETED.value, JobState.CANCELLED.value})

ALLOWED_JOB_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.CANCELLED}),
    JobState.RUNNING: frozenset(
        {JobState.PAUSED, JobState.FAILED, JobState.COMPLETED, JobState.CANCELLED}
    ),
    JobState.PAUSED: frozenset({JobState.RUNNING, JobState.CANCELLED, JobState.FAILED}),
    JobState.FAILED: frozenset({JobState.QUEUED, JobState.CANCELLED}),
    JobState.COMPLETED: frozenset(),
    JobState.CANCELLED: frozenset(),
}


class JobError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def require_job_transition(current: JobState | str, target: JobState | str) -> None:
    source = JobState(current)
    dest = JobState(target)
    if source is dest:
        return
    allowed = ALLOWED_JOB_TRANSITIONS[source]
    if dest not in allowed:
        raise JobError(
            "illegal_job_transition",
            f"Cannot move job from {source.value} to {dest.value}.",
        )
