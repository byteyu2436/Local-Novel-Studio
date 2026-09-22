import json
from pathlib import Path

from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.models import ChapterVersion
from app.domain.analysis import CHAPTER_ANALYSIS_SCHEMA_VERSION
from app.eval.analysis_golden import (
    check_fixture_contract,
    compare_key_facts,
    format_failures,
    iter_golden_fixtures,
    load_golden_fixture,
    run_cli,
)
from app.prompts.chapter_analyzer import CHAPTER_ANALYZER_PROMPT_VERSION
from app.schemas.analysis import parse_chapter_analysis_payload
from app.services import catalog
from app.services.analysis import persist_chapter_analysis
from tests.test_chapter_analysis import _trace

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "analysis" / "rain_alley_ch1.json"


def test_golden_baseline_passes_contract() -> None:
    fixture = load_golden_fixture(FIXTURE)
    failures = check_fixture_contract(fixture)
    assert failures == [], format_failures(failures)
    payload = parse_chapter_analysis_payload(fixture.baseline_payload)
    assert payload.characters[0].name == "林深"
    assert fixture.schema_version == CHAPTER_ANALYSIS_SCHEMA_VERSION
    assert fixture.prompt_version == CHAPTER_ANALYZER_PROMPT_VERSION


def test_runner_reports_chapter_and_field_on_drift() -> None:
    fixture = load_golden_fixture(FIXTURE)
    payload = parse_chapter_analysis_payload(fixture.baseline_payload)
    drifted = payload.model_copy(
        update={"characters": [payload.characters[0].model_copy(update={"name": "路人"})]}
    )
    failures = compare_key_facts(drifted, fixture.required, fixture_id=fixture.fixture_id)
    assert any(item.field == "characters.name" for item in failures)
    report = format_failures(failures)
    assert "rain-alley-ch1:characters.name:" in report


def test_broken_schema_fixture_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text(
        json.dumps(
            {
                "fixture_id": "broken-ch1",
                "chapter_body": "x",
                "source": {"version_kind": "ORIGINAL"},
                "schema_version": CHAPTER_ANALYSIS_SCHEMA_VERSION,
                "prompt_version": CHAPTER_ANALYZER_PROMPT_VERSION,
                "required": {"character_names": ["林深"]},
                "baseline_payload": {"summary": {"synopsis": ""}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    failures = check_fixture_contract(load_golden_fixture(path))
    assert failures
    assert failures[0].fixture_id == "broken-ch1"
    assert failures[0].field == "baseline_payload"


def test_golden_payload_persists_with_source_metadata(isolated_data_dir) -> None:
    fixture = load_golden_fixture(FIXTURE)
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, fixture.source["novel_title"])
            chapter = catalog.create_chapter(
                session,
                novel.id,
                body=fixture.chapter_body,
                original_label=fixture.source["original_label"],
                original_title=fixture.source["original_title"],
            )
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            assert canon.version_kind == fixture.source["version_kind"]
            row = persist_chapter_analysis(
                session,
                chapter,
                canon,
                payload=fixture.baseline_payload,
                **_trace(
                    analyzer_version=fixture.prompt_version,
                    prompt_version=fixture.prompt_version,
                ),
            )
            assert row.schema_version == fixture.schema_version
            assert row.prompt_version == fixture.prompt_version
            assert row.source_version_kind == "ORIGINAL"
    finally:
        engine.dispose()


def test_iter_skips_gpu_pending_record() -> None:
    fixtures = iter_golden_fixtures()
    assert [item.fixture_id for item in fixtures] == ["rain-alley-ch1"]


def test_cli_contract_exit_zero() -> None:
    assert run_cli([]) == 0
