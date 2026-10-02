from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.embedding.types import EmbeddingProvider
from app.adapters.llm.types import LLMProvider
from app.adapters.milvus.collections import MilvusCollectionClient
from app.adapters.sqlite.continuation import AcceptOperation, continuation_now
from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.chapter import VersionKind
from app.domain.chapter_canon import (
    add_draft_version,
    make_accepted_from_draft,
    mark_superseded,
    set_canon_pointer,
)
from app.domain.jobs import JobKind, JobState
from app.schemas.analysis import parse_stored_analysis_payload
from app.services import catalog
from app.services.analysis import get_chapter_analysis
from app.services.canon_chunks import build_chapter_chunks
from app.services.consistency import list_issues
from app.services.drafts import DraftError, get_draft
from app.services.embedding_batches import embed_canon_chunks
from app.services.embedding_profiles import get_active_embedding_profile
from app.services.jobs import create_job, transition_job
from app.services.memory_incremental import commit_canon_memory
from app.services.milvus_vectors import upsert_canon_embeddings
from app.services.plans import require_confirmed_plan
from app.services.title_generator import generate_title_candidates


def _view(row: AcceptOperation) -> dict:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "draft_id": row.draft_id,
        "chapter_id": row.chapter_id,
        "version_id": row.version_id,
        "plan_id": row.plan_id,
        "memory_status": row.memory_status,
        "index_status": row.index_status,
    }


def preflight_accept(session: Session, novel_id: str, draft_id: str, plan_id: str) -> None:
    draft = get_draft(session, novel_id, draft_id)
    require_confirmed_plan(session, novel_id, plan_id)
    if draft.plan_id not in {None, plan_id}:
        raise DraftError("accept_plan_mismatch", "草稿不属于这版已确认计划。")
    blocking = [
        item for item in list_issues(session, novel_id, draft_id) if item["severity"] == "blocking"
    ]
    if blocking:
        raise DraftError("accept_blocked", "还有挡住续写的一致性问题，不能接受。")
    if not draft.body.strip():
        raise DraftError("accept_draft_empty", "草稿是空的，不能接受。")


async def accept_draft(
    session: Session,
    novel_id: str,
    draft_id: str,
    plan_id: str,
    *,
    llm: LLMProvider | None = None,
    embedding: EmbeddingProvider | None = None,
    milvus: MilvusCollectionClient | None = None,
) -> dict:
    existing = session.scalar(select(AcceptOperation).where(AcceptOperation.draft_id == draft_id))
    if existing is not None:
        if existing.novel_id != novel_id:
            raise DraftError("accept_plan_mismatch", "这份接受记录不属于当前小说。")
        return _view(existing)
    preflight_accept(session, novel_id, draft_id, plan_id)
    draft = get_draft(session, novel_id, draft_id)
    plan = require_confirmed_plan(session, novel_id, plan_id)
    chapter = catalog.create_chapter(
        session, novel_id, body=draft.body, sequence=plan.target_sequence
    )
    original = session.get(ChapterVersion, chapter.current_canon_version_id)
    if original is None:
        raise DraftError("accept_canon_missing", "新章节没有 Canon 版本。")
    draft_version = add_draft_version(
        chapter, body=draft.body, parent=original, created_at=continuation_now()
    )
    session.flush()
    accepted = make_accepted_from_draft(chapter, draft_version, created_at=continuation_now())
    session.add(accepted)
    session.flush()
    if original.version_kind == VersionKind.ACCEPTED.value:
        mark_superseded(original, accepted)
    set_canon_pointer(chapter, accepted)
    session.flush()
    operation = AcceptOperation(
        id=str(uuid4()),
        novel_id=novel_id,
        draft_id=draft.id,
        chapter_id=chapter.id,
        version_id=accepted.id,
        plan_id=plan.id,
        memory_status="pending",
        index_status="pending",
        created_at=continuation_now(),
    )
    session.add(operation)
    session.flush()
    operation.memory_status = await _memory(session, llm, novel_id, chapter.id, accepted.id)
    operation.index_status = await _index(session, embedding, milvus, novel_id, chapter, accepted)
    session.flush()
    return _view(operation)


async def _memory(session, llm, novel_id: str, chapter_id: str, version_id: str) -> str:
    job = create_job(session, kind=JobKind.UPDATE_MEMORY, novel_id=novel_id, progress_total=1)
    transition_job(session, job, JobState.RUNNING)
    if llm is None:
        transition_job(session, job, JobState.FAILED)
        job.error_code = "analysis_required"
        return "skipped"
    try:
        await commit_canon_memory(session, novel_id, chapter_id, version_id, llm)
        await _title(session, llm, chapter_id, version_id)
    except Exception as exc:
        job.error_code = getattr(exc, "code", "memory_update_failed")
        job.error_message = str(exc)
        transition_job(session, job, JobState.FAILED)
        return "failed"
    job.progress_done = 1
    transition_job(session, job, JobState.COMPLETED)
    return "completed"


async def _title(session, llm, chapter_id: str, version_id: str) -> None:
    chapter = session.get(Chapter, chapter_id)
    version = session.get(ChapterVersion, version_id)
    stored = None if chapter is None else get_chapter_analysis(session, chapter.id, version_id)
    if chapter is None or version is None or stored is None:
        return
    payload = parse_stored_analysis_payload(
        stored.payload, schema_version=stored.schema_version
    )
    await generate_title_candidates(session, llm, chapter, version, payload)


async def _index(session, embedding, milvus, novel_id: str, chapter, version) -> str:
    if embedding is None or milvus is None:
        return "skipped"
    try:
        build_chapter_chunks(session, novel_id, chapter, version)
        report = await embed_canon_chunks(session, novel_id, embedding)
        if report.failed:
            return "failed"
        profile = get_active_embedding_profile(session)
        if profile is None:
            return "skipped"
        await upsert_canon_embeddings(session, milvus, novel_id, profile)
    except Exception:
        return "failed"
    return "completed"
