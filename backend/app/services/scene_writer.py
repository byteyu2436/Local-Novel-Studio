from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from app.adapters.llm.errors import LLMCancelledError, LLMError
from app.adapters.llm.profiles import default_model_profiles
from app.adapters.llm.types import ChatMessage, LLMProvider, ModelRole
from app.domain.jobs import JobState
from app.prompts import PromptKind, current_prompt
from app.services.context_builder import build_context, render_context
from app.services.drafts import DraftError, save_draft
from app.services.jobs import create_job, get_job, job_fingerprint, transition_job
from app.services.plans import plan_payload, require_confirmed_plan
from app.settings import get_settings


def _scene(plan, scene_id: str):
    for scene in plan.scenes:
        if scene.scene_id == scene_id:
            return scene
    raise DraftError("scene_not_found", "确认过的计划里没有这个场景。")


async def stream_scene(
    session: Session,
    provider: LLMProvider,
    novel_id: str,
    *,
    plan_id: str,
    scene_id: str,
    prefix: str = "",
    parent_draft_id: str | None = None,
) -> AsyncIterator[dict]:
    row = require_confirmed_plan(session, novel_id, plan_id)
    plan = plan_payload(row)
    scene = _scene(plan, scene_id)
    model = default_model_profiles(get_settings())[ModelRole.WRITER]
    manifest = build_context(
        session,
        novel_id,
        model,
        chapter_goal=plan.chapter_goal,
        plan_text=scene.goal,
        plan_id=row.id,
        evidence=[],
    )
    prompt = current_prompt(PromptKind.SCENE_WRITER)
    job = create_job(
        session,
        kind="GENERATE_SCENE",
        novel_id=novel_id,
        progress_total=1,
        input_fingerprint=job_fingerprint(
            novel_id=novel_id, kind="GENERATE_SCENE", extra=f"{plan_id}:{scene_id}:{prefix[:24]}"
        ),
    )
    transition_job(session, job, JobState.RUNNING)
    job.checkpoint = {"plan_id": plan_id, "scene_id": scene_id, "text": prefix}
    session.flush()
    yield {"event": "started", "job_id": job.id, "state": job.state, "text": prefix}
    messages = [
        ChatMessage(role="system", content=prompt.text),
        ChatMessage(role="user", content=render_context(manifest)),
    ]
    parts: list[str] = []
    try:
        async for chunk in provider.stream_chat(messages, model):
            session.refresh(job)
            if job.state == JobState.CANCELLED.value:
                break
            if not chunk.text:
                continue
            parts.append(chunk.text)
            job.checkpoint = {
                "plan_id": plan_id,
                "scene_id": scene_id,
                "text": prefix + "".join(parts),
            }
            session.flush()
            yield {"event": "chunk", "job_id": job.id, "state": job.state, "text": chunk.text}
    except LLMCancelledError:
        transition_job(session, job, JobState.CANCELLED)
    except LLMError as exc:
        job.error_code = getattr(exc, "code", "scene_failed")
        job.error_message = str(exc)
        transition_job(session, job, JobState.FAILED)
        session.flush()
        raise DraftError(job.error_code or "scene_failed", str(exc)) from exc
    text = prefix + "".join(parts).strip()
    draft = None
    if text:
        draft = save_draft(
            session,
            novel_id=novel_id,
            target_sequence=row.target_sequence,
            body=text,
            origin="generated",
            plan_id=row.id,
            parent_id=parent_draft_id,
        )
        job.checkpoint = {**(job.checkpoint or {}), "draft_id": draft.id, "text": text}
    if job.state == JobState.RUNNING.value:
        job.progress_done = 1
        transition_job(session, job, JobState.COMPLETED)
    session.flush()
    yield {
        "event": "done",
        "job_id": job.id,
        "state": job.state,
        "text": text,
        "draft_id": None if draft is None else draft.id,
    }


async def generate_scene(
    session: Session,
    provider: LLMProvider,
    novel_id: str,
    *,
    plan_id: str,
    scene_id: str,
    prefix: str = "",
    parent_draft_id: str | None = None,
) -> dict:
    final: dict = {}
    async for event in stream_scene(
        session,
        provider,
        novel_id,
        plan_id=plan_id,
        scene_id=scene_id,
        prefix=prefix,
        parent_draft_id=parent_draft_id,
    ):
        final = event
    return {
        "job_id": final.get("job_id"),
        "state": final.get("state"),
        "text": final.get("text") or "",
        "draft": None if not final.get("draft_id") else {"id": final["draft_id"]},
    }


def cancel_scene(session: Session, novel_id: str, job_id: str) -> dict:
    job = get_job(session, job_id)
    if job.novel_id != novel_id or job.kind != "GENERATE_SCENE":
        raise DraftError("scene_job_not_found", "找不到这个生成任务。")
    if job.state == JobState.COMPLETED.value:
        raise DraftError("scene_not_cancellable", "已经写完的场景不能取消。")
    if job.state != JobState.CANCELLED.value:
        transition_job(session, job, JobState.CANCELLED)
    session.flush()
    return {"job_id": job.id, "state": job.state, "checkpoint": job.checkpoint or {}}


async def resume_scene(
    session: Session, provider: LLMProvider, novel_id: str, job_id: str
) -> dict:
    previous = get_job(session, job_id)
    if previous.novel_id != novel_id or previous.kind != "GENERATE_SCENE":
        raise DraftError("scene_job_not_found", "找不到这个生成任务。")
    if previous.state not in {JobState.CANCELLED.value, JobState.FAILED.value}:
        raise DraftError("scene_not_resumable", "只有中断或失败的生成可以接着写。")
    checkpoint = previous.checkpoint or {}
    plan_id = str(checkpoint.get("plan_id") or "")
    scene_id = str(checkpoint.get("scene_id") or "")
    if not plan_id or not scene_id:
        raise DraftError("scene_not_resumable", "这次生成没有可继续的检查点。")
    parent = checkpoint.get("draft_id")
    return await generate_scene(
        session,
        provider,
        novel_id,
        plan_id=plan_id,
        scene_id=scene_id,
        prefix=str(checkpoint.get("text") or ""),
        parent_draft_id=str(parent) if parent else None,
    )
