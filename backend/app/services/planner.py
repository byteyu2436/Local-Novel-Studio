from hashlib import sha256

from sqlalchemy.orm import Session

from app.adapters.llm.errors import LLMError
from app.adapters.llm.profiles import default_model_profiles
from app.adapters.llm.types import ChatMessage, LLMProvider, ModelProfile, ModelRole
from app.domain.analysis import AnalysisError, extract_json_object
from app.prompts import PromptKind, current_prompt
from app.prompts.chapter_planner import CHAPTER_PLANNER_REPAIR_V1
from app.schemas.plan import ChapterPlan, PlanStatus, chapter_plan_json_schema
from app.services.context_builder import build_context, render_context
from app.services.plans import PlanError, plan_view, save_plan_version
from app.settings import Settings, get_settings


def _conflict(plan: ChapterPlan, locked_facts: list[str]) -> str:
    for fact in locked_facts:
        if fact and fact in plan.forbidden_items:
            return fact
    return ""


async def generate_plan(
    session: Session,
    provider: LLMProvider,
    novel_id: str,
    *,
    chapter_goal: str,
    target_sequence: int,
    locked_facts: list[str] | None = None,
    evidence: list[dict] | None = None,
    settings: Settings | None = None,
    profile: ModelProfile | None = None,
    parent_id: str | None = None,
) -> dict:
    resolved = settings or get_settings()
    model = profile or default_model_profiles(resolved)[ModelRole.WRITER]
    prompt = current_prompt(PromptKind.CHAPTER_PLANNER)
    manifest = build_context(
        session,
        novel_id,
        model,
        chapter_goal=chapter_goal,
        evidence=evidence,
    )
    messages = [
        ChatMessage(role="system", content=prompt.text),
        ChatMessage(
            role="user",
            content=f"章节目标：{chapter_goal}\n\n{render_context(manifest)}",
        ),
    ]
    schema = chapter_plan_json_schema()
    last_error = "计划没有通过校验。"
    for attempt in (1, 2):
        try:
            raw = await provider.chat(messages, model, response_format=schema)
        except LLMError as exc:
            raise PlanError("planner_unavailable", str(exc)) from exc
        try:
            data = extract_json_object(raw)
        except AnalysisError as exc:
            last_error = exc.message
            data = None
        if isinstance(data, dict) and data.get("constraint_conflict"):
            raise PlanError("constraint_conflict", str(data["constraint_conflict"]))
        if data is not None:
            try:
                plan = ChapterPlan.model_validate(data)
            except Exception as exc:
                last_error = str(exc)
                plan = None
            else:
                conflict = _conflict(plan, locked_facts or [])
                if conflict:
                    raise PlanError("constraint_conflict", conflict)
                row = save_plan_version(
                    session,
                    novel_id=novel_id,
                    target_sequence=target_sequence,
                    plan=plan,
                    status=PlanStatus.GENERATED,
                    parent_id=parent_id,
                    prompt_version=prompt.version,
                    model_ref=model.model_ref,
                    profile_id=model.profile_id,
                    context_checksum=sha256(render_context(manifest).encode()).hexdigest(),
                )
                view = plan_view(row)
                view["repaired"] = attempt == 2
                return view
        if attempt == 1:
            messages = [
                *messages,
                ChatMessage(role="assistant", content=raw),
                ChatMessage(
                    role="user",
                    content=CHAPTER_PLANNER_REPAIR_V1.format(error=last_error),
                ),
            ]
            continue
        raise PlanError("planner_repair_exhausted", "计划校验失败，已经尝试修复一次。")
    raise PlanError("planner_repair_exhausted", "计划校验失败，已经尝试修复一次。")
