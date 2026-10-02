from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.memory import MemoryCharacter, MemoryFact
from app.services import catalog
from app.services.memory_reduce import reduce_novel_memory
from app.services.memory_reduce_report import write_reduce_regression_report
from app.services.memory_repository import MemoryRepository
from sqlalchemy import select
from tests.test_memory_reduce import _payload, _store


def _snapshot(session, novel_id: str) -> list[tuple]:
    rows = session.scalars(
        select(MemoryFact).where(MemoryFact.novel_id == novel_id).order_by(MemoryFact.id)
    ).all()
    return [
        (
            row.id,
            row.revision,
            row.status,
            row.confidence,
            row.fact_key,
            row.fact_value["value"],
            row.source_chapter_version_id,
        )
        for row in rows
    ]


def test_repeated_reduce_stays_stable_and_report_locates_duplicates(
    isolated_data_dir, tmp_path
) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapters = [
                catalog.create_chapter(session, novel.id, body=f"第{index}章。")
                for index in range(1, 19)
            ]
            for index, chapter in enumerate(chapters, start=1):
                _store(session, chapter, _payload(index))
            first = reduce_novel_memory(session, novel.id)
            assert first.chapters_applied == 18
            assert first.chapters_skipped == 0
            before = _snapshot(session, novel.id)
            revision = MemoryRepository(session).memory_revision(novel.id)
            second = reduce_novel_memory(session, novel.id)
            assert second.chapters_applied == 0
            assert second.chapters_skipped == 18
            assert second.facts_created == 0
            assert second.facts_reinforced == 0
            assert _snapshot(session, novel.id) == before
            assert MemoryRepository(session).memory_revision(novel.id) == revision
            report = write_reduce_regression_report(session, novel.id, tmp_path)
            assert report["consistent"] is True
            assert report["counts"]["characters"] == 2
            assert report["counts"]["events"] == 1
            assert report["counts"]["foreshadowing"] == 1
            assert report["counts"]["relationships"] == 1
            assert "duplicate_character" not in (tmp_path / "memory-reduce-report.md").read_text(
                encoding="utf-8"
            )
            session.add(
                MemoryCharacter(
                    id="00000000-0000-0000-0000-000000000164",
                    novel_id=novel.id,
                    name="林深",
                    aliases=[],
                    created_at=chapters[0].created_at,
                    updated_at=chapters[0].created_at,
                )
            )
            session.flush()
            located = write_reduce_regression_report(session, novel.id, tmp_path)
            assert located["consistent"] is False
            assert located["findings"][0]["kind"] == "duplicate_character"
            assert located["findings"][0]["name"] == "林深"
            markdown = (tmp_path / "memory-reduce-report.md").read_text(encoding="utf-8")
            assert "林深" in markdown
    finally:
        engine.dispose()
