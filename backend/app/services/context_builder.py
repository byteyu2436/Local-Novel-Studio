import logging
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.llm.types import ModelProfile
from app.adapters.sqlite.memory import MemoryForeshadowing
from app.adapters.sqlite.models import ChapterVersion
from app.domain.context_budget import (
    BUILDER_VERSION,
    ESTIMATOR_VERSION,
    budget_for_profile,
    estimate_section_tokens,
    trim_sections,
)
from app.domain.memory import ForeshadowingStatus
from app.schemas.context import ContextManifest, ContextSection
from app.services import catalog
from app.services.memory_query import list_memory_facts

logger = logging.getLogger("app.context")

WRITING_RULES = (
    "只依据已确认的 Canon 和锁定事实续写。Draft 不是 Canon。"
    "不得推翻锁定设定，不得把草稿写成既成事实。"
)
OPEN_FORESHADOWING = {
    ForeshadowingStatus.PLANTED.value,
    ForeshadowingStatus.REINFORCED.value,
}


def _section(**kwargs) -> ContextSection:
    text = str(kwargs.get("text") or "")
    kwargs["token_estimate"] = estimate_section_tokens(text)
    kwargs["checksum"] = sha256(text.encode()).hexdigest()
    kwargs.setdefault("version", BUILDER_VERSION)
    return ContextSection(**kwargs)


def _facts(session: Session, novel_id: str, kind: str, *, locked: bool | None = None) -> list[dict]:
    return list_memory_facts(session, novel_id, kind=kind, status="active", locked=locked)


def collect_sections(
    session: Session,
    novel_id: str,
    *,
    chapter_goal: str,
    evidence: list[dict] | None,
    plan_text: str = "",
    plan_id: str = "",
) -> tuple[list[ContextSection], list[str]]:
    """Gather Canon-backed slices. Missing sources are omitted instead of invented."""

    catalog.require_novel(session, novel_id)
    degraded: list[str] = []
    sections = [
        _section(
            section_type="writing_rules",
            source_type="system",
            source_id="writing-rules",
            priority=100,
            locked=True,
            text=WRITING_RULES,
        ),
        _section(
            section_type="current_goal",
            source_type="user",
            source_id="chapter-goal",
            priority=70,
            locked=True,
            text=chapter_goal.strip(),
        ),
    ]
    for fact in _facts(session, novel_id, "world_fact", locked=True):
        sections.append(
            _section(
                section_type="locked_facts",
                source_type="memory",
                source_id=fact["id"],
                priority=90,
                locked=True,
                text=str(fact["value"]),
            )
        )
    for fact in _facts(session, novel_id, "character"):
        sections.append(
            _section(
                section_type="character_state",
                source_type="memory",
                source_id=fact["id"],
                priority=80,
                locked=True,
                text=str(fact["value"]),
            )
        )
    for fact in _facts(session, novel_id, "relationship"):
        sections.append(
            _section(
                section_type="relationship",
                source_type="memory",
                source_id=fact["id"],
                priority=30,
                text=str(fact["value"]),
            )
        )
    summaries = _facts(session, novel_id, "style_profile")
    if summaries:
        sections.append(
            _section(
                section_type="global_summary",
                source_type="memory",
                source_id=summaries[0]["id"],
                priority=20,
                text=str(summaries[0]["value"]),
                compressed_text=_shorten(str(summaries[0]["value"])),
            )
        )
    else:
        degraded.append("global_summary")
    open_items = session.scalars(
        select(MemoryForeshadowing)
        .where(
            MemoryForeshadowing.novel_id == novel_id,
            MemoryForeshadowing.status.in_(tuple(OPEN_FORESHADOWING)),
        )
        .order_by(MemoryForeshadowing.id)
    ).all()
    for item in open_items:
        sections.append(
            _section(
                section_type="open_foreshadowing",
                source_type="memory",
                source_id=item.id,
                priority=40,
                text=item.label,
            )
        )
    if evidence is None:
        degraded.append("retrieval")
    else:
        for item in evidence:
            sections.append(
                _section(
                    section_type="retrieved_evidence",
                    source_type="retrieval",
                    source_id=str(item["id"]),
                    priority=10,
                    score=float(item.get("score") or 0),
                    text=str(item.get("text") or ""),
                )
            )
    chapters = catalog.list_chapters(session, novel_id)
    recent = chapters[-2:]
    for offset, chapter in enumerate(recent):
        version = session.get(ChapterVersion, chapter.current_canon_version_id)
        if version is None:
            continue
        sections.append(
            _section(
                section_type="recent_text",
                source_type="canon",
                source_id=chapter.id,
                priority=50,
                recency=offset + 1,
                text=version.body,
            )
        )
    if plan_text.strip():
        sections.append(
            _section(
                section_type="plan",
                source_type="user",
                source_id=plan_id or "plan",
                priority=60,
                text=plan_text.strip(),
            )
        )
    return sections, degraded


def _shorten(text: str) -> str:
    if estimate_section_tokens(text) <= 40:
        return ""
    kept = text[:40]
    return kept


def build_context(
    session: Session,
    novel_id: str,
    profile: ModelProfile,
    *,
    chapter_goal: str,
    evidence: list[dict] | None = None,
    plan_text: str = "",
    plan_id: str = "",
) -> ContextManifest:
    if not chapter_goal.strip():
        from app.domain.context_budget import ContextBudgetError

        raise ContextBudgetError("chapter_goal_empty", "要先写下这一章想写什么。")
    budget = budget_for_profile(profile)
    collected, degraded = collect_sections(
        session,
        novel_id,
        chapter_goal=chapter_goal,
        evidence=evidence,
        plan_text=plan_text,
        plan_id=plan_id,
    )
    trimmed = trim_sections(collected, budget)
    included = [item for item in trimmed if item.included and item.text.strip()]
    omitted = [item for item in trimmed if not item.included or not item.text.strip()]
    total = sum(item.token_estimate for item in included)
    logger.info(
        "context built novel_id=%s sections=%s omitted=%s tokens=%s",
        novel_id,
        len(included),
        len(omitted),
        total,
    )
    return ContextManifest(
        builder_version=BUILDER_VERSION,
        profile_id=budget.profile_id,
        estimator_version=ESTIMATOR_VERSION,
        max_context_tokens=budget.max_context_tokens,
        input_budget=budget.input_budget,
        output_reserve=budget.output_reserve,
        safety_margin=budget.safety_margin,
        total_tokens=total,
        degraded=degraded,
        sections=included,
        omitted=omitted,
    )


def render_context(manifest: ContextManifest) -> str:
    parts = [f"[{item.section_type}]\n{item.text}" for item in manifest.sections]
    return "\n\n".join(parts)
