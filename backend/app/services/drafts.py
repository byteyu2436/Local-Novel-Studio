from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.llm.errors import LLMError
from app.adapters.llm.profiles import default_model_profiles
from app.adapters.llm.types import ChatMessage, LLMProvider, ModelRole
from app.adapters.sqlite.continuation import DraftVersion, continuation_now
from app.prompts import PromptKind, current_prompt
from app.services import catalog
from app.settings import get_settings


class DraftError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def draft_view(row: DraftVersion) -> dict:
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "target_sequence": row.target_sequence,
        "plan_id": row.plan_id,
        "parent_id": row.parent_id,
        "origin": row.origin,
        "body": row.body,
    }


def list_drafts(session: Session, novel_id: str) -> list[dict]:
    catalog.require_novel(session, novel_id)
    rows = session.scalars(
        select(DraftVersion)
        .where(DraftVersion.novel_id == novel_id)
        .order_by(DraftVersion.created_at, DraftVersion.id)
    ).all()
    return [draft_view(row) for row in rows]


def restore_draft(session: Session, novel_id: str, draft_id: str) -> DraftVersion:
    current = get_draft(session, novel_id, draft_id)
    return save_draft(
        session,
        novel_id=novel_id,
        target_sequence=current.target_sequence,
        body=current.body,
        origin="user",
        plan_id=current.plan_id,
        parent_id=current.id,
    )


def get_draft(session: Session, novel_id: str, draft_id: str) -> DraftVersion:
    row = session.get(DraftVersion, draft_id)
    if row is None or row.novel_id != novel_id:
        raise DraftError("draft_not_found", "找不到这份草稿。")
    return row


def save_draft(
    session: Session,
    *,
    novel_id: str,
    target_sequence: int,
    body: str,
    origin: str,
    plan_id: str | None = None,
    parent_id: str | None = None,
) -> DraftVersion:
    catalog.require_novel(session, novel_id)
    if origin not in {"generated", "user", "rewrite"}:
        raise DraftError("draft_origin_invalid", "草稿来源不合法。")
    if parent_id is not None:
        get_draft(session, novel_id, parent_id)
    row = DraftVersion(
        id=str(uuid4()),
        novel_id=novel_id,
        target_sequence=target_sequence,
        plan_id=plan_id,
        parent_id=parent_id,
        body=body,
        origin=origin,
        created_at=continuation_now(),
    )
    session.add(row)
    session.flush()
    return row


def splice_rewrite(body: str, start: int, end: int, replacement: str) -> str:
    if start < 0 or end > len(body) or start >= end:
        raise DraftError("rewrite_range_invalid", "改写范围不在正文里。")
    if not replacement.strip():
        raise DraftError("rewrite_empty", "改写结果是空的。")
    prefix = body[:start]
    suffix = body[end:]
    echoed = replacement.startswith(prefix) and replacement.endswith(suffix)
    if echoed and len(replacement) >= len(body):
        middle = replacement[len(prefix) : len(replacement) - len(suffix)]
        if not middle.strip():
            raise DraftError("rewrite_outside_range", "改写碰到了范围外的文字。")
        return prefix + middle + suffix
    if prefix and prefix in replacement and not replacement.startswith(prefix):
        raise DraftError("rewrite_outside_range", "改写碰到了范围外的文字。")
    return prefix + replacement + suffix


async def rewrite_draft(
    session: Session,
    provider: LLMProvider,
    novel_id: str,
    draft_id: str,
    *,
    start: int,
    end: int,
    instruction: str,
) -> DraftVersion:
    current = get_draft(session, novel_id, draft_id)
    prompt = current_prompt(PromptKind.REWRITE)
    model = default_model_profiles(get_settings())[ModelRole.WRITER]
    span = current.body[start:end]
    messages = [
        ChatMessage(role="system", content=prompt.text),
        ChatMessage(role="user", content=f"改写要求：{instruction}\n\n原文片段：{span}"),
    ]
    try:
        raw = await provider.chat(messages, model)
    except LLMError as exc:
        raise DraftError("rewrite_unavailable", str(exc)) from exc
    body = splice_rewrite(current.body, start, end, raw.strip())
    if not body.startswith(current.body[:start]) or not body.endswith(current.body[end:]):
        raise DraftError("rewrite_outside_range", "改写碰到了范围外的文字。")
    return save_draft(
        session,
        novel_id=novel_id,
        target_sequence=current.target_sequence,
        body=body,
        origin="rewrite",
        plan_id=current.plan_id,
        parent_id=current.id,
    )
