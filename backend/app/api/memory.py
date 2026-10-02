from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.domain.catalog import CatalogError
from app.domain.memory import MemoryError
from app.domain.memory_conflict import ConflictResolution
from app.services.entity_resolution import list_resolution_candidates
from app.services.memory_adjudication import resolve_memory_conflict
from app.services.memory_audit import list_operations
from app.services.memory_merge import merge_characters
from app.services.memory_query import fact_detail, list_memory_entities, list_memory_facts
from app.services.memory_repository import MemoryRepository

router = APIRouter(tags=["memory"])


class FactEditBody(BaseModel):
    value: dict
    expected_revision: int | None = None


class ResolveBody(BaseModel):
    action: ConflictResolution
    fact_value: dict | None = None
    expected_revision: int | None = None


class MergeBody(BaseModel):
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)


def _http(exc: MemoryError | CatalogError) -> HTTPException:
    not_found = {
        "fact_not_found",
        "conflict_not_found",
        "entity_not_found",
        "novel_not_found",
        "snapshot_not_found",
    }
    code = status.HTTP_404_NOT_FOUND if exc.code in not_found else status.HTTP_409_CONFLICT
    return HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message})


@router.get("/api/novels/{novel_id}/memory")
def read_memory(
    novel_id: str,
    session: Annotated[Session, Depends(get_session)],
    kind: str = Query(default="character"),
    status_filter: str | None = Query(default=None, alias="status"),
    locked: bool | None = None,
) -> dict:
    try:
        return {
            "entities": list_memory_entities(session, novel_id, kind),
            "facts": list_memory_facts(
                session, novel_id, kind=kind, status=status_filter, locked=locked
            ),
        }
    except (MemoryError, CatalogError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "memory_kind_invalid", "message": "Unknown memory kind."},
            ) from exc
        raise _http(exc) from exc


@router.get("/api/novels/{novel_id}/memory/facts/{fact_id}")
def read_fact(
    novel_id: str, fact_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        return fact_detail(session, novel_id, fact_id)
    except MemoryError as exc:
        raise _http(exc) from exc


@router.post("/api/novels/{novel_id}/memory/facts/{fact_id}/lock")
def lock_fact(
    novel_id: str, fact_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        fact = MemoryRepository(session).lock_fact(fact_id, novel_id)
    except MemoryError as exc:
        raise _http(exc) from exc
    return {"id": fact.id, "locked": fact.locked, "revision": fact.revision}


@router.post("/api/novels/{novel_id}/memory/facts/{fact_id}/unlock")
def unlock_fact(
    novel_id: str, fact_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        fact = MemoryRepository(session).unlock_fact(fact_id, novel_id)
    except MemoryError as exc:
        raise _http(exc) from exc
    return {"id": fact.id, "locked": fact.locked, "revision": fact.revision}


@router.post("/api/novels/{novel_id}/memory/facts/{fact_id}/edit")
def edit_fact(
    novel_id: str,
    fact_id: str,
    body: FactEditBody,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        from app.adapters.sqlite.memory import MemoryFact
        from app.adapters.sqlite.models import Chapter, ChapterVersion

        current = session.get(MemoryFact, fact_id)
        if current is None or current.novel_id != novel_id:
            raise MemoryError("fact_not_found", "Fact does not exist in this novel.")
        if body.expected_revision is not None and current.revision != body.expected_revision:
            raise MemoryError("stale_revision", "The fact revision changed before this edit.")
        chapter = session.get(Chapter, current.source_chapter_id)
        version = session.get(ChapterVersion, current.source_chapter_version_id)
        if chapter is None or version is None:
            raise MemoryError("conflict_source_missing", "Fact source chapter is missing.")
        created = MemoryRepository(session).supersede_fact(
            fact_id=current.id,
            novel_id=novel_id,
            fact_value=body.value,
            source_chapter=chapter,
            source_version=version,
            origin=current.origin,
            confidence=current.confidence,
        )
    except MemoryError as exc:
        raise _http(exc) from exc
    return {"id": created.id, "revision": created.revision, "value": created.fact_value}


@router.get("/api/novels/{novel_id}/memory/conflicts")
def read_conflicts(novel_id: str, session: Annotated[Session, Depends(get_session)]) -> dict:
    from app.services.memory_conflicts import list_open_conflicts

    try:
        rows = list_open_conflicts(session, novel_id)
    except Exception as exc:
        from app.domain.catalog import CatalogError as CatalogFailure

        if isinstance(exc, CatalogFailure):
            raise _http(exc) from exc
        raise
    return {
        "conflicts": [
            {
                "id": row.id,
                "category": row.category,
                "fact_key": row.fact_key,
                "status": row.status,
                "existing_fact_id": row.existing_fact_id,
                "existing_value": row.existing_value,
                "incoming_value": row.incoming_value,
                "existing_source_chapter_id": row.existing_source_chapter_id,
                "incoming_source_chapter_id": row.incoming_source_chapter_id,
            }
            for row in rows
        ]
    }


@router.post("/api/novels/{novel_id}/memory/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    novel_id: str,
    conflict_id: str,
    body: ResolveBody,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    try:
        conflict = resolve_memory_conflict(
            session,
            novel_id=novel_id,
            conflict_id=conflict_id,
            action=body.action,
            fact_value=body.fact_value,
            expected_revision=body.expected_revision,
        )
    except MemoryError as exc:
        raise _http(exc) from exc
    return {"id": conflict.id, "status": conflict.status, "resolution": conflict.resolution}


@router.get("/api/novels/{novel_id}/memory/operations")
def read_operations(novel_id: str, session: Annotated[Session, Depends(get_session)]) -> dict:
    return {
        "operations": [
            {
                "id": row.id,
                "action": row.action,
                "target_kind": row.target_kind,
                "target_id": row.target_id,
                "before_revision": row.before_revision,
                "after_revision": row.after_revision,
            }
            for row in list_operations(session, novel_id)
        ]
    }


@router.get("/api/novels/{novel_id}/memory/alias-candidates")
def read_alias_candidates(novel_id: str, session: Annotated[Session, Depends(get_session)]) -> dict:
    rows = list_resolution_candidates(session, novel_id)
    return {
        "candidates": [
            {
                "id": row.id,
                "mention_name": row.mention_name,
                "reason": row.reason,
                "candidate_entity_ids": list(row.candidate_entity_ids),
                "source_chapter_id": row.source_chapter_id,
            }
            for row in rows
        ]
    }


@router.post("/api/novels/{novel_id}/memory/aliases/merge")
def merge_alias(
    novel_id: str, body: MergeBody, session: Annotated[Session, Depends(get_session)]
) -> dict:
    try:
        target = merge_characters(session, novel_id, body.source_id, body.target_id)
    except MemoryError as exc:
        raise _http(exc) from exc
    return {"id": target.id, "name": target.name, "aliases": list(target.aliases)}
