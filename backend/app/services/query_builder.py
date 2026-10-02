from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domain.memory import MemorySubjectKind
from app.schemas.retrieval import (
    QUERY_BUILDER_VERSION,
    MetadataHints,
    QueryBuilderInput,
    RetrievalQuery,
)
from app.services.memory_query import list_memory_entities
from app.services.memory_snapshot import latest_memory_snapshot, snapshot_chapter


@dataclass(frozen=True)
class MemoryHints:
    characters: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    foreshadowing: tuple[str, ...] = ()
    previous_chapter_state: str = ""


def load_memory_hints(session: Session, novel_id: str) -> MemoryHints:
    """Read local memory labels. An empty novel still returns empty hints."""

    characters = _labels(session, novel_id, MemorySubjectKind.CHARACTER.value)
    events = _labels(session, novel_id, MemorySubjectKind.EVENT.value)
    foreshadowing = _labels(session, novel_id, MemorySubjectKind.FORESHADOWING.value)
    snapshot = latest_memory_snapshot(session, novel_id)
    state = ""
    if snapshot is not None:
        state = snapshot_chapter(session, snapshot).display_title
    return MemoryHints(
        characters=tuple(characters),
        events=tuple(events),
        foreshadowing=tuple(foreshadowing),
        previous_chapter_state=state,
    )


def build_retrieval_query(
    context: QueryBuilderInput, memory: MemoryHints | None = None
) -> RetrievalQuery:
    """Turn planning context into one repeatable Canon query. Does not search."""

    recalled = memory or MemoryHints()
    characters = _prefer(context.characters, recalled.characters)
    locations = _prefer(context.locations, recalled.locations)
    events = _prefer(context.events, recalled.events)
    foreshadowing = _prefer(context.foreshadowing, recalled.foreshadowing)
    state = context.previous_chapter_state.strip() or recalled.previous_chapter_state.strip()
    goal = context.chapter_goal.strip()
    scene = context.current_scene.strip()
    return RetrievalQuery(
        novel_id=context.novel_id,
        chapter_goal=goal,
        current_scene=scene,
        characters=characters,
        locations=locations,
        events=events,
        foreshadowing=foreshadowing,
        previous_chapter_state=state,
        top_n=context.top_n,
        semantic_query_text=_semantic_text(
            goal=goal,
            scene=scene,
            characters=characters,
            locations=locations,
            events=events,
            foreshadowing=foreshadowing,
            previous_chapter_state=state,
        ),
        metadata_hints=MetadataHints(
            characters=characters,
            locations=locations,
            events=events,
            foreshadowing=foreshadowing,
        ),
        query_builder_version=QUERY_BUILDER_VERSION,
    )


def _prefer(explicit: list[str], recalled: tuple[str, ...]) -> list[str]:
    chosen = _names(explicit)
    if chosen:
        return chosen
    return _names(recalled)


def _names(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        names.append(cleaned)
    return names


def _semantic_text(
    *,
    goal: str,
    scene: str,
    characters: list[str],
    locations: list[str],
    events: list[str],
    foreshadowing: list[str],
    previous_chapter_state: str,
) -> str:
    lines: list[str] = []
    if goal:
        lines.append(f"章节目标：{goal}")
    if scene:
        lines.append(f"当前场景：{scene}")
    if characters:
        lines.append("人物：" + "、".join(characters))
    if locations:
        lines.append("地点：" + "、".join(locations))
    if events:
        lines.append("事件：" + "、".join(events))
    if foreshadowing:
        lines.append("伏笔：" + "、".join(foreshadowing))
    if previous_chapter_state:
        lines.append(f"上一章：{previous_chapter_state}")
    if not lines:
        lines.append("续写当前章节")
    return "\n".join(lines)


def _labels(session: Session, novel_id: str, kind: str) -> list[str]:
    return [str(row["label"]) for row in list_memory_entities(session, novel_id, kind)]
