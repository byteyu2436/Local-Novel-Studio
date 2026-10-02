from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.sqlite.continuation import ChapterPlanVersion, continuation_now
from app.prompts.chapter_planner import CHAPTER_PLAN_SCHEMA_VERSION
from app.schemas.plan import ChapterPlan, PlanStatus
from app.services import catalog


class PlanError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _next_version(session: Session, novel_id: str, target_sequence: int) -> int:
    current = session.scalar(
        select(func.max(ChapterPlanVersion.version_number)).where(
            ChapterPlanVersion.novel_id == novel_id,
            ChapterPlanVersion.target_sequence == target_sequence,
        )
    )
    return 1 if current is None else int(current) + 1


def plan_payload(row: ChapterPlanVersion) -> ChapterPlan:
    return ChapterPlan.model_validate(row.payload)


def plan_view(row: ChapterPlanVersion) -> dict:
    payload = plan_payload(row)
    return {
        "id": row.id,
        "novel_id": row.novel_id,
        "target_sequence": row.target_sequence,
        "version_number": row.version_number,
        "status": row.status,
        "parent_id": row.parent_id,
        "is_confirmed_pointer": row.is_confirmed_pointer,
        "prompt_version": row.prompt_version,
        "model_ref": row.model_ref,
        "schema_version": row.schema_version,
        "profile_id": row.profile_id,
        "plan": payload.model_dump(),
    }


def get_plan(session: Session, novel_id: str, plan_id: str) -> ChapterPlanVersion:
    row = session.get(ChapterPlanVersion, plan_id)
    if row is None or row.novel_id != novel_id:
        raise PlanError("plan_not_found", "找不到这版章节计划。")
    return row


def list_plans(session: Session, novel_id: str) -> list[dict]:
    catalog.require_novel(session, novel_id)
    rows = session.scalars(
        select(ChapterPlanVersion)
        .where(ChapterPlanVersion.novel_id == novel_id)
        .order_by(ChapterPlanVersion.target_sequence, ChapterPlanVersion.version_number)
    ).all()
    return [plan_view(row) for row in rows]


def save_plan_version(
    session: Session,
    *,
    novel_id: str,
    target_sequence: int,
    plan: ChapterPlan,
    status: PlanStatus,
    parent_id: str | None = None,
    prompt_version: str = "",
    model_ref: str = "",
    profile_id: str = "",
    context_checksum: str = "",
) -> ChapterPlanVersion:
    catalog.require_novel(session, novel_id)
    row = ChapterPlanVersion(
        id=str(uuid4()),
        novel_id=novel_id,
        target_sequence=target_sequence,
        version_number=_next_version(session, novel_id, target_sequence),
        status=status.value,
        parent_id=parent_id,
        chapter_goal=plan.chapter_goal,
        payload=plan.model_dump(),
        prompt_version=prompt_version,
        model_ref=model_ref,
        schema_version=CHAPTER_PLAN_SCHEMA_VERSION,
        profile_id=profile_id,
        context_checksum=context_checksum,
        is_confirmed_pointer=False,
        created_at=continuation_now(),
    )
    session.add(row)
    session.flush()
    return row


def edit_plan(
    session: Session, novel_id: str, plan_id: str, plan: ChapterPlan
) -> ChapterPlanVersion:
    current = get_plan(session, novel_id, plan_id)
    return save_plan_version(
        session,
        novel_id=novel_id,
        target_sequence=current.target_sequence,
        plan=plan,
        status=PlanStatus.EDITED,
        parent_id=current.id,
        prompt_version=current.prompt_version,
        model_ref=current.model_ref,
        profile_id=current.profile_id,
        context_checksum=current.context_checksum,
    )


def reorder_scenes(
    session: Session, novel_id: str, plan_id: str, scene_ids: list[str]
) -> ChapterPlanVersion:
    current = get_plan(session, novel_id, plan_id)
    payload = plan_payload(current)
    by_id = {scene.scene_id: scene for scene in payload.scenes}
    if set(scene_ids) != set(by_id) or len(scene_ids) != len(by_id):
        raise PlanError("scene_order_invalid", "场景顺序必须包含全部场景，且不能重复。")
    ordered = []
    for index, scene_id in enumerate(scene_ids, start=1):
        scene = by_id[scene_id].model_copy(update={"order": index})
        ordered.append(scene)
    updated = payload.model_copy(update={"scenes": ordered})
    return edit_plan(session, novel_id, plan_id, updated)


def confirm_plan(session: Session, novel_id: str, plan_id: str) -> ChapterPlanVersion:
    row = get_plan(session, novel_id, plan_id)
    if row.is_confirmed_pointer and row.status == PlanStatus.CONFIRMED.value:
        return row
    if row.status == PlanStatus.SUPERSEDED.value:
        raise PlanError("plan_not_confirmable", "已被替换的计划不能再确认。")
    previous = session.scalars(
        select(ChapterPlanVersion).where(
            ChapterPlanVersion.novel_id == novel_id,
            ChapterPlanVersion.target_sequence == row.target_sequence,
            ChapterPlanVersion.is_confirmed_pointer.is_(True),
        )
    ).all()
    for item in previous:
        item.is_confirmed_pointer = False
        if item.status == PlanStatus.CONFIRMED.value:
            item.status = PlanStatus.SUPERSEDED.value
    session.flush()
    row.status = PlanStatus.CONFIRMED.value
    row.is_confirmed_pointer = True
    session.flush()
    return row


def require_confirmed_plan(session: Session, novel_id: str, plan_id: str) -> ChapterPlanVersion:
    row = get_plan(session, novel_id, plan_id)
    if row.status != PlanStatus.CONFIRMED.value or not row.is_confirmed_pointer:
        raise PlanError("plan_not_confirmed", "还没有确认的计划，不能开始写正文。")
    return row
