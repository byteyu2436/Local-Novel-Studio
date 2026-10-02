import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.sqlite.memory import (
    MemoryCharacter,
    MemoryEvent,
    MemoryFact,
    MemoryForeshadowing,
    MemoryRelationship,
)
from app.domain.memory import FactStatus


def audit_reduced_memory(session: Session, novel_id: str) -> dict:
    """Count memory rows and point at duplicate entities or unsourced facts."""

    counts = {
        "characters": _count(session, MemoryCharacter, novel_id),
        "relationships": _count(session, MemoryRelationship, novel_id),
        "events": _count(session, MemoryEvent, novel_id),
        "foreshadowing": _count(session, MemoryForeshadowing, novel_id),
        "active_facts": _count_facts(session, novel_id, active_only=True),
        "fact_revisions": _count_facts(session, novel_id, active_only=False),
    }
    findings = [*_duplicate_characters(session, novel_id), *_unsourced_facts(session, novel_id)]
    return {
        "novel_id": novel_id,
        "consistent": not findings,
        "counts": counts,
        "findings": findings,
    }


def write_reduce_regression_report(session: Session, novel_id: str, directory: Path) -> dict:
    payload = audit_reduced_memory(session, novel_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "memory-reduce-report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (directory / "memory-reduce-report.md").write_text(
        _markdown(payload),
        encoding="utf-8",
    )
    return payload


def _duplicate_characters(session: Session, novel_id: str) -> list[dict]:
    rows = session.scalars(
        select(MemoryCharacter).where(MemoryCharacter.novel_id == novel_id)
    ).all()
    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(row.name, []).append(row.id)
    return [
        {
            "kind": "duplicate_character",
            "name": name,
            "entity_ids": ids,
        }
        for name, ids in sorted(grouped.items())
        if len(ids) > 1
    ]


def _unsourced_facts(session: Session, novel_id: str) -> list[dict]:
    rows = session.scalars(
        select(MemoryFact).where(
            MemoryFact.novel_id == novel_id,
            MemoryFact.active.is_(True),
            MemoryFact.source_chapter_version_id.is_(None),
        )
    ).all()
    return [
        {
            "kind": "missing_source",
            "fact_id": row.id,
            "fact_key": row.fact_key,
            "subject_id": row.subject_id,
        }
        for row in rows
    ]


def _markdown(payload: dict) -> str:
    lines = [
        "# Memory reduce regression",
        "",
        f"- novel_id: {payload['novel_id']}",
        f"- consistent: {payload['consistent']}",
        "",
        "## Counts",
        "",
    ]
    for key, value in payload["counts"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Findings", ""])
    if not payload["findings"]:
        lines.append("- none")
    else:
        for finding in payload["findings"]:
            if finding["kind"] == "duplicate_character":
                lines.append(
                    f"- duplicate_character {finding['name']}: {', '.join(finding['entity_ids'])}"
                )
            else:
                lines.append(f"- missing_source {finding['fact_key']} fact {finding['fact_id']}")
    lines.append("")
    return "\n".join(lines)


def _count(session: Session, model, novel_id: str) -> int:
    return int(
        session.scalar(select(func.count()).select_from(model).where(model.novel_id == novel_id))
        or 0
    )


def _count_facts(session: Session, novel_id: str, *, active_only: bool) -> int:
    stmt = select(func.count()).select_from(MemoryFact).where(MemoryFact.novel_id == novel_id)
    if active_only:
        stmt = stmt.where(MemoryFact.status == FactStatus.ACTIVE.value)
    return int(session.scalar(stmt) or 0)
