from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.adapters.sqlite.memory import MemoryConflict, MemoryFact
from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.memory import FactOrigin, MemoryError
from app.domain.memory_conflict import ConflictResolution, ConflictStatus
from app.services.memory_audit import write_operation
from app.services.memory_repository import MemoryRepository


def resolve_memory_conflict(
    session: Session,
    *,
    novel_id: str,
    conflict_id: str,
    action: ConflictResolution | str,
    fact_value: dict | None = None,
    expected_revision: int | None = None,
) -> MemoryConflict:
    """Resolve one conflict. A failed step rolls back both the conflict and the fact."""

    conflict = _conflict(session, novel_id, conflict_id)
    if conflict.status != ConflictStatus.OPEN.value:
        raise MemoryError("conflict_not_open", "Only an open conflict can be resolved.")
    fact = session.get(MemoryFact, conflict.existing_fact_id)
    if fact is None or fact.novel_id != novel_id:
        raise MemoryError("fact_not_found", "Conflict fact does not exist in this novel.")
    if expected_revision is not None and fact.revision != expected_revision:
        raise MemoryError("stale_revision", "The fact revision changed before this resolution.")
    resolution = ConflictResolution(action)
    repo = MemoryRepository(session)
    try:
        with session.begin_nested():
            conflict.status = (
                ConflictStatus.DISMISSED.value
                if resolution is ConflictResolution.DISMISS
                else ConflictStatus.RESOLVED.value
            )
            conflict.resolution = resolution.value
            conflict.resolved_at = datetime.now(UTC)
            session.flush()
            successor: MemoryFact | None = None
            if resolution is ConflictResolution.ACCEPT_INCOMING:
                successor = _supersede(repo, fact, conflict.incoming_value, conflict)
            elif resolution is ConflictResolution.EDIT:
                if not fact_value:
                    raise MemoryError("edit_value_required", "An edited fact needs a value.")
                successor = _supersede(repo, fact, fact_value, conflict)
            write_operation(
                session,
                novel_id=novel_id,
                action=f"resolve_conflict_{resolution.value}",
                target_kind="conflict",
                target_id=conflict.id,
                before_revision=fact.revision,
                after_revision=None if successor is None else successor.revision,
                detail={"fact_id": fact.id},
            )
    except Exception:
        session.expire_all()
        raise
    return conflict


def _conflict(session: Session, novel_id: str, conflict_id: str) -> MemoryConflict:
    row = session.get(MemoryConflict, conflict_id)
    if row is None or row.novel_id != novel_id:
        raise MemoryError("conflict_not_found", "Conflict does not exist in this novel.")
    return row


def _supersede(
    repo: MemoryRepository, fact: MemoryFact, value: dict, conflict: MemoryConflict
) -> MemoryFact:
    chapter = repo.session.get(Chapter, conflict.incoming_source_chapter_id)
    version = repo.session.get(ChapterVersion, conflict.incoming_source_chapter_version_id)
    if chapter is None or version is None:
        raise MemoryError("conflict_source_missing", "Conflict source chapter is missing.")
    return repo.supersede_fact(
        fact_id=fact.id,
        novel_id=fact.novel_id,
        fact_value=value,
        source_chapter=chapter,
        source_version=version,
        origin=FactOrigin.INFERRED,
        confidence=fact.confidence,
    )
