import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.canon_chunks import list_canon_chunks


def write_chunk_regression_report(session: Session, novel_id: str, directory: Path) -> dict:
    rows = list_canon_chunks(session, novel_id, active_only=False)
    active = [row for row in rows if row.canon_status == "active"]
    payload = {
        "novel_id": novel_id,
        "active_count": len(active),
        "inactive_count": len(rows) - len(active),
        "chunks": [
            {
                "id": row.id,
                "chapter_id": row.chapter_id,
                "chunk_index": row.chunk_index,
                "start_offset": row.start_offset,
                "end_offset": row.end_offset,
                "overlap_tokens": row.overlap_tokens,
                "text_checksum": row.text_checksum,
                "chunking_version": row.chunking_version,
                "canon_status": row.canon_status,
            }
            for row in rows
        ],
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chunk-regression.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Chunk regression",
        "",
        f"- novel_id: {novel_id}",
        f"- active: {payload['active_count']}",
        f"- inactive: {payload['inactive_count']}",
        "",
    ]
    for item in payload["chunks"]:
        lines.append(
            f"- {item['canon_status']} {item['id'][:8]} "
            f"chapter {item['chapter_id']} [{item['start_offset']}:{item['end_offset']}]"
        )
    (directory / "chunk-regression.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload
