import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.llm.errors import LLMError
from app.adapters.llm.profiles import default_model_profiles
from app.adapters.llm.types import ChatMessage, LLMProvider, ModelRole
from app.adapters.sqlite.continuation import ConsistencyIssueRecord, continuation_now
from app.domain.analysis import AnalysisError, extract_json_object
from app.domain.jobs import JobState
from app.prompts import PromptKind, current_prompt
from app.prompts.consistency_checker import CONSISTENCY_REPAIR_V1
from app.services.context_builder import build_context, render_context
from app.services.drafts import DraftError, get_draft
from app.services.jobs import create_job, transition_job
from app.settings import get_settings

SEVERITIES = {"info", "warning", "blocking"}


def issue_view(row: ConsistencyIssueRecord) -> dict:
    return {
        "id": row.id,
        "draft_id": row.draft_id,
        "severity": row.severity,
        "category": row.category,
        "summary": row.summary,
        "evidence_ids": list(row.evidence),
    }


def list_issues(session: Session, novel_id: str, draft_id: str) -> list[dict]:
    get_draft(session, novel_id, draft_id)
    rows = session.scalars(
        select(ConsistencyIssueRecord)
        .where(ConsistencyIssueRecord.draft_id == draft_id)
        .order_by(ConsistencyIssueRecord.created_at, ConsistencyIssueRecord.id)
    ).all()
    return [issue_view(row) for row in rows]


def _parse_issues(raw: str) -> list[dict]:
    data = extract_json_object(raw)
    if isinstance(data, dict) and "issues" in data:
        data = data["issues"]
    if not isinstance(data, list):
        raise DraftError("consistency_invalid", "检查结果不是问题列表。")
    issues = []
    for item in data:
        if not isinstance(item, dict):
            raise DraftError("consistency_invalid", "检查结果不是问题列表。")
        severity = str(item.get("severity") or "")
        summary = str(item.get("summary") or "").strip()
        if severity not in SEVERITIES or not summary:
            raise DraftError("consistency_invalid", "检查结果缺少严重级别或说明。")
        evidence = item.get("evidence_ids") or []
        if not isinstance(evidence, list):
            raise DraftError("consistency_invalid", "证据编号不是列表。")
        issues.append(
            {
                "severity": severity,
                "category": str(item.get("category") or "canon"),
                "summary": summary,
                "evidence_ids": [str(value) for value in evidence],
            }
        )
    return issues


async def check_draft(
    session: Session,
    provider: LLMProvider,
    novel_id: str,
    draft_id: str,
) -> dict:
    draft = get_draft(session, novel_id, draft_id)
    model = default_model_profiles(get_settings())[ModelRole.ANALYZER]
    manifest = build_context(
        session,
        novel_id,
        model,
        chapter_goal="检查这份草稿是否违背已确认事实",
        evidence=[],
    )
    prompt = current_prompt(PromptKind.CONSISTENCY_CHECKER)
    messages = [
        ChatMessage(role="system", content=prompt.text),
        ChatMessage(
            role="user",
            content=f"Draft 正文如下，它不是 Canon。\n{draft.body}\n\n{render_context(manifest)}",
        ),
    ]
    job = create_job(session, kind="CHECK_CONSISTENCY", novel_id=novel_id, progress_total=1)
    transition_job(session, job, JobState.RUNNING)
    last_error = "检查结果无法解析。"
    parsed: list[dict] | None = None
    for attempt in (1, 2):
        try:
            raw = await provider.chat(messages, model)
        except LLMError as exc:
            job.error_message = str(exc)
            transition_job(session, job, JobState.FAILED)
            raise DraftError("consistency_unavailable", str(exc)) from exc
        try:
            parsed = _parse_issues(raw)
            break
        except (DraftError, AnalysisError, json.JSONDecodeError) as exc:
            last_error = getattr(exc, "message", str(exc))
            if attempt == 2:
                transition_job(session, job, JobState.FAILED)
                raise DraftError("consistency_invalid", last_error) from exc
            messages = [
                *messages,
                ChatMessage(role="assistant", content=raw),
                ChatMessage(role="user", content=CONSISTENCY_REPAIR_V1.format(error=last_error)),
            ]
    assert parsed is not None
    saved = []
    for item in parsed:
        row = ConsistencyIssueRecord(
            id=str(uuid4()),
            novel_id=novel_id,
            draft_id=draft.id,
            severity=item["severity"],
            category=item["category"],
            summary=item["summary"],
            evidence=item["evidence_ids"],
            created_at=continuation_now(),
        )
        session.add(row)
        saved.append(row)
    job.progress_done = 1
    transition_job(session, job, JobState.COMPLETED)
    session.flush()
    return {"job_id": job.id, "issues": [issue_view(row) for row in saved]}
