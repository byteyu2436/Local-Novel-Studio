from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.sqlite.memory import MemoryOperationLog


def write_operation(
    session: Session,
    *,
    novel_id: str,
    action: str,
    target_kind: str,
    target_id: str,
    before_revision: int | None,
    after_revision: int | None,
    detail: dict | None = None,
) -> MemoryOperationLog:
    row = MemoryOperationLog(
        id=str(uuid4()),
        novel_id=novel_id,
        action=action,
        target_kind=target_kind,
        target_id=target_id,
        before_revision=before_revision,
        after_revision=after_revision,
        detail=detail or {},
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def list_operations(session: Session, novel_id: str) -> list[MemoryOperationLog]:
    return list(
        session.scalars(
            select(MemoryOperationLog)
            .where(MemoryOperationLog.novel_id == novel_id)
            .order_by(MemoryOperationLog.created_at, MemoryOperationLog.id)
        )
    )
