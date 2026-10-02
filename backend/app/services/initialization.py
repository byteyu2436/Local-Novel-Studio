from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.adapters.embedding.errors import EmbeddingError
from app.adapters.embedding.types import EmbeddingProvider
from app.adapters.llm.types import LLMProvider
from app.adapters.milvus.collections import MilvusCollectionClient
from app.adapters.sqlite.initialization import INIT_PHASES, NovelInitializationRun, init_now
from app.domain.analysis import CHAPTER_ANALYSIS_SCHEMA_VERSION
from app.domain.jobs import JobState, require_job_transition
from app.services import catalog
from app.services.analysis import get_chapter_analysis
from app.services.analysis_orchestrator import run_novel_analysis
from app.services.canon_chunks import build_novel_chunks
from app.services.embedding_batches import embed_canon_chunks
from app.services.embedding_profiles import get_active_embedding_profile
from app.services.index_rebuild import RebuildError, rebuild_canon_index
from app.services.index_registry import serving_index
from app.services.memory_reduce import reduce_novel_memory

PHASE_LABELS = {
    "analysis": "分析章节",
    "memory_reduce": "构建记忆",
    "chunk": "准备检索索引",
    "embedding": "准备检索索引",
    "index_validate_activate": "准备检索索引",
    "ready": "完成",
}
PHASE_DETAILS = {
    "analysis": "分析章节",
    "memory_reduce": "构建记忆",
    "chunk": "整理章节",
    "embedding": "准备检索",
    "index_validate_activate": "校验索引",
    "ready": "完成",
}
SUGGESTIONS = {
    "analysis_required": "先完成本地章节分析，再从分析阶段重试。",
    "embedding_unavailable": "检查本地向量模型后，从准备检索索引阶段重试。",
    "no_active_index": "从索引校验阶段重试。已完成的章节不会重做。",
    "chapters_empty": "先确认章节，再开始初始化。",
}


class InitializationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def initialization_fingerprint(session: Session, novel_id: str) -> str:
    parts = [novel_id]
    for chapter in catalog.list_chapters(session, novel_id):
        parts.append(f"{chapter.id}:{chapter.current_canon_version_id}")
    profile = get_active_embedding_profile(session)
    parts.append(profile.id if profile is not None else "")
    return sha256("\n".join(parts).encode()).hexdigest()


def get_initialization(session: Session, novel_id: str) -> NovelInitializationRun | None:
    catalog.require_novel(session, novel_id)
    return session.scalar(
        select(NovelInitializationRun).where(NovelInitializationRun.novel_id == novel_id)
    )


def open_initialization(session: Session, novel_id: str) -> NovelInitializationRun:
    fingerprint = initialization_fingerprint(session, novel_id)
    row = get_initialization(session, novel_id)
    now = init_now()
    if row is None:
        row = NovelInitializationRun(
            id=str(uuid4()),
            novel_id=novel_id,
            state=JobState.QUEUED.value,
            current_phase="analysis",
            child_job_ids=[],
            progress_done=0,
            progress_total=len(INIT_PHASES),
            checkpoint={"completed": []},
            error_code=None,
            error_message=None,
            suggested_action=None,
            input_fingerprint=fingerprint,
            profile_fingerprint=None,
            schema_fingerprint=CHAPTER_ANALYSIS_SCHEMA_VERSION,
            index_fingerprint=None,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return row
    if row.state == JobState.COMPLETED.value and row.input_fingerprint == fingerprint:
        return row
    if row.state == JobState.CANCELLED.value or (
        row.state == JobState.COMPLETED.value and row.input_fingerprint != fingerprint
    ):
        row.state = JobState.QUEUED.value
        row.current_phase = "analysis"
        row.checkpoint = {"completed": []}
        row.progress_done = 0
        row.error_code = None
        row.error_message = None
        row.suggested_action = None
        row.input_fingerprint = fingerprint
        row.updated_at = now
        session.flush()
    return row


async def execute_initialization(
    session: Session,
    client: MilvusCollectionClient,
    embedding: EmbeddingProvider,
    novel_id: str,
    *,
    llm: LLMProvider | None = None,
    pause_before: str | None = None,
) -> NovelInitializationRun:
    row = open_initialization(session, novel_id)
    if row.state == JobState.COMPLETED.value:
        return row
    if row.state == JobState.FAILED.value:
        return row
    if row.state == JobState.PAUSED.value and pause_before is None:
        return row
    _transition(row, JobState.RUNNING)
    for phase in INIT_PHASES:
        session.refresh(row)
        if row.state in {JobState.PAUSED.value, JobState.CANCELLED.value}:
            return row
        completed = list(row.checkpoint.get("completed") or [])
        if phase in completed:
            continue
        if pause_before == phase:
            _transition(row, JobState.PAUSED)
            row.current_phase = phase
            row.updated_at = init_now()
            session.flush()
            return row
        row.current_phase = phase
        row.updated_at = init_now()
        session.flush()
        try:
            await _run_phase(session, client, embedding, llm, row, phase)
        except InitializationError as exc:
            return _fail(row, exc.code, exc.message)
        completed.append(phase)
        row.checkpoint = {"completed": completed}
        row.progress_done = len(completed)
        row.updated_at = init_now()
        session.flush()
    _transition(row, JobState.COMPLETED)
    row.current_phase = "ready"
    session.flush()
    return row


def pause_initialization(session: Session, novel_id: str) -> NovelInitializationRun:
    row = _require(session, novel_id)
    if row.state != JobState.PAUSED.value:
        _transition(row, JobState.PAUSED)
    return row


async def resume_initialization(
    session: Session,
    client: MilvusCollectionClient,
    embedding: EmbeddingProvider,
    novel_id: str,
    *,
    llm: LLMProvider | None = None,
) -> NovelInitializationRun:
    row = _require(session, novel_id)
    if row.state == JobState.PAUSED.value:
        _transition(row, JobState.RUNNING)
    return await execute_initialization(session, client, embedding, novel_id, llm=llm)


def cancel_initialization(session: Session, novel_id: str) -> NovelInitializationRun:
    row = _require(session, novel_id)
    if row.state != JobState.CANCELLED.value:
        _transition(row, JobState.CANCELLED)
    return row


async def retry_initialization(
    session: Session,
    client: MilvusCollectionClient,
    embedding: EmbeddingProvider,
    novel_id: str,
    *,
    llm: LLMProvider | None = None,
) -> NovelInitializationRun:
    row = _require(session, novel_id)
    if row.state == JobState.FAILED.value:
        _transition(row, JobState.QUEUED)
        row.error_code = None
        row.error_message = None
        row.suggested_action = None
        session.flush()
    return await execute_initialization(session, client, embedding, novel_id, llm=llm)


def initialization_status(session: Session, novel_id: str) -> dict:
    row = get_initialization(session, novel_id)
    if row is None:
        return {
            "run_id": None,
            "novel_id": novel_id,
            "state": "not_started",
            "current_phase": None,
            "phase_label": "尚未开始",
            "phases": _phase_view([], None, "not_started"),
            "progress_done": 0,
            "progress_total": len(INIT_PHASES),
            "error_code": None,
            "error_message": None,
            "suggested_action": "开始初始化。",
            "ready": False,
        }
    completed = list(row.checkpoint.get("completed") or [])
    return {
        "run_id": row.id,
        "novel_id": row.novel_id,
        "state": row.state,
        "current_phase": row.current_phase,
        "phase_label": PHASE_LABELS.get(row.current_phase, row.current_phase),
        "phases": _phase_view(completed, row.current_phase, row.state),
        "progress_done": row.progress_done,
        "progress_total": row.progress_total,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "suggested_action": row.suggested_action,
        "ready": novel_is_ready(session, novel_id),
    }


def novel_is_ready(session: Session, novel_id: str) -> bool:
    row = get_initialization(session, novel_id)
    if row is None or row.state != JobState.COMPLETED.value or row.current_phase != "ready":
        return False
    return serving_index(session) is not None


def writing_gate(session: Session, novel_id: str) -> dict:
    ready = novel_is_ready(session, novel_id)
    status = initialization_status(session, novel_id)
    if ready:
        message = "初始化已完成，可以阅读，也可以进入续写。"
    elif status["state"] == "failed":
        message = status["error_message"] or "初始化失败，还不能续写。"
    elif status["state"] == "paused":
        message = "初始化已暂停，还不能续写。"
    else:
        message = "初始化尚未完成，还不能续写。"
    return {"ready": ready, "state": status["state"], "message": message}


async def _run_phase(
    session, client, embedding, llm, row: NovelInitializationRun, phase: str
) -> None:
    if phase == "analysis":
        await _analysis(session, row, llm)
    elif phase == "memory_reduce":
        reduce_novel_memory(session, row.novel_id)
    elif phase == "chunk":
        build_novel_chunks(session, row.novel_id)
    elif phase == "embedding":
        await _embedding(session, embedding, row)
    elif phase == "index_validate_activate":
        await _index(session, client, embedding, row)
    elif phase == "ready":
        if serving_index(session) is None:
            raise InitializationError("no_active_index", "索引还没有就绪。")
        profile = get_active_embedding_profile(session)
        if profile is not None:
            row.profile_fingerprint = profile.id
            row.index_fingerprint = profile.index_version


async def _analysis(session: Session, row: NovelInitializationRun, llm: LLMProvider | None) -> None:
    chapters = catalog.list_chapters(session, row.novel_id)
    if not chapters:
        raise InitializationError("chapters_empty", "没有可初始化的章节。")
    missing = []
    for chapter in chapters:
        if chapter.current_canon_version_id is None:
            continue
        if get_chapter_analysis(session, chapter.id, chapter.current_canon_version_id) is None:
            missing.append(chapter.id)
    if not missing:
        return
    if llm is None:
        raise InitializationError("analysis_required", "还有章节没有分析结果。")
    job = await run_novel_analysis(session, row.novel_id, llm)
    ids = list(row.child_job_ids)
    if job.id not in ids:
        ids.append(job.id)
    row.child_job_ids = ids
    if job.state == JobState.FAILED.value:
        raise InitializationError(
            job.error_code or "analysis_failed", job.error_message or "分析失败。"
        )


async def _embedding(session, embedding: EmbeddingProvider, row: NovelInitializationRun) -> None:
    try:
        report = await embed_canon_chunks(session, row.novel_id, embedding)
    except EmbeddingError as exc:
        raise InitializationError(exc.code, str(exc)) from exc
    if report.failed:
        raise InitializationError("embedding_unavailable", "还有章节片段没有生成向量。")


async def _index(session, client, embedding, row: NovelInitializationRun) -> None:
    profile = get_active_embedding_profile(session)
    current = serving_index(session)
    if (
        profile is not None
        and current is not None
        and current.embedding_profile_id == profile.id
        and current.index_version == profile.index_version
    ):
        row.index_fingerprint = current.index_version
        return
    try:
        report = await rebuild_canon_index(session, client, embedding)
    except RebuildError as exc:
        raise InitializationError(exc.code, exc.message) from exc
    except EmbeddingError as exc:
        raise InitializationError(exc.code, str(exc)) from exc
    row.index_fingerprint = report.index_id


def _fail(row: NovelInitializationRun, code: str, message: str) -> NovelInitializationRun:
    row.error_code = code
    row.error_message = message
    row.suggested_action = SUGGESTIONS.get(code, "从失败阶段重试。已完成的步骤会保留。")
    _transition(row, JobState.FAILED)
    return row


def _transition(row: NovelInitializationRun, target: JobState) -> None:
    require_job_transition(row.state, target)
    if row.state != target.value:
        row.state = target.value
    row.updated_at = init_now()
    bound = object_session(row)
    if bound is not None:
        bound.flush()


def _require(session: Session, novel_id: str) -> NovelInitializationRun:
    row = get_initialization(session, novel_id)
    if row is None:
        raise InitializationError("initialization_not_found", "这本小说还没有初始化记录。")
    return row


def _phase_view(completed: list[str], current: str | None, state: str) -> list[dict]:
    rows = []
    for phase in INIT_PHASES:
        if phase in completed:
            status = "completed"
        elif state == "failed" and phase == current:
            status = "failed"
        elif phase == current and state in {"running", "paused"}:
            status = state
        else:
            status = "pending"
        rows.append(
            {
                "id": phase,
                "label": PHASE_LABELS[phase],
                "detail": PHASE_DETAILS[phase],
                "status": status,
            }
        )
    return rows
