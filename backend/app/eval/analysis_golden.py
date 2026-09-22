from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.analysis import CHAPTER_ANALYSIS_SCHEMA_VERSION, AnalysisError
from app.prompts.chapter_analyzer import CHAPTER_ANALYZER_PROMPT_VERSION
from app.schemas.analysis import ChapterAnalysisPayload, parse_chapter_analysis_payload

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "analysis"


@dataclass(frozen=True)
class GoldenFailure:
    fixture_id: str
    field: str
    message: str

    def report(self) -> str:
        return f"{self.fixture_id}:{self.field}: {self.message}"


@dataclass(frozen=True)
class GoldenFixture:
    fixture_id: str
    chapter_body: str
    source: dict[str, Any]
    schema_version: str
    prompt_version: str
    required: dict[str, Any]
    baseline_payload: dict[str, Any]


def load_golden_fixture(path: Path) -> GoldenFixture:
    data = json.loads(path.read_text(encoding="utf-8"))
    return GoldenFixture(
        fixture_id=str(data["fixture_id"]),
        chapter_body=str(data["chapter_body"]),
        source=dict(data["source"]),
        schema_version=str(data["schema_version"]),
        prompt_version=str(data["prompt_version"]),
        required=dict(data["required"]),
        baseline_payload=dict(data["baseline_payload"]),
    )


def iter_golden_fixtures(directory: Path = FIXTURES_DIR) -> list[GoldenFixture]:
    return [
        load_golden_fixture(path)
        for path in sorted(directory.glob("*.json"))
        if path.name != "gpu_pending_record.json"
    ]


def _contains(haystack: str, needle: str) -> bool:
    return needle.casefold() in haystack.casefold()


def compare_key_facts(
    payload: ChapterAnalysisPayload, required: dict[str, Any], *, fixture_id: str
) -> list[GoldenFailure]:
    """Structure/key-fact checks. Synopsis wording is allowed to drift."""

    failures: list[GoldenFailure] = []
    names = {item.name for item in payload.characters}
    for name in required.get("character_names", []):
        if name not in names:
            failures.append(GoldenFailure(fixture_id, "characters.name", f"missing {name!r}"))
    locations = {item.name for item in payload.locations}
    for name in required.get("location_names", []):
        if name not in locations:
            failures.append(GoldenFailure(fixture_id, "locations.name", f"missing {name!r}"))
    event_blob = " ".join(item.summary for item in payload.events)
    for keyword in required.get("event_keywords", []):
        if not _contains(event_blob, keyword):
            failures.append(
                GoldenFailure(fixture_id, "events.summary", f"missing keyword {keyword!r}")
            )
    pairs = {(item.source, item.target) for item in payload.relationships}
    for source, target in required.get("relationship_pairs", []):
        if (source, target) not in pairs and (target, source) not in pairs:
            failures.append(
                GoldenFailure(
                    fixture_id,
                    "relationships",
                    f"missing pair {source!r}-{target!r}",
                )
            )
    minimum = int(required.get("timeline_min_entries", 0))
    if len(payload.timeline) < minimum:
        failures.append(
            GoldenFailure(
                fixture_id,
                "timeline",
                f"expected at least {minimum} entries, got {len(payload.timeline)}",
            )
        )
    statuses = {item.status for item in payload.foreshadowing}
    for status in required.get("foreshadowing_statuses", []):
        if status not in statuses:
            failures.append(
                GoldenFailure(fixture_id, "foreshadowing.status", f"missing {status!r}")
            )
    fact_blob = " ".join(item.fact for item in payload.world_facts)
    for keyword in required.get("world_fact_keywords", []):
        if not _contains(fact_blob, keyword):
            failures.append(
                GoldenFailure(fixture_id, "world_facts.fact", f"missing keyword {keyword!r}")
            )
    pov = payload.style_signals.pov or ""
    tokens = list(required.get("style_pov_tokens", []))
    if tokens and not any(_contains(pov, token) for token in tokens):
        failures.append(
            GoldenFailure(fixture_id, "style_signals.pov", f"expected one of {tokens}")
        )
    return failures


def check_fixture_contract(fixture: GoldenFixture) -> list[GoldenFailure]:
    failures: list[GoldenFailure] = []
    if fixture.schema_version != CHAPTER_ANALYSIS_SCHEMA_VERSION:
        failures.append(
            GoldenFailure(
                fixture.fixture_id,
                "schema_version",
                f"expected {CHAPTER_ANALYSIS_SCHEMA_VERSION}",
            )
        )
    if fixture.prompt_version != CHAPTER_ANALYZER_PROMPT_VERSION:
        failures.append(
            GoldenFailure(
                fixture.fixture_id,
                "prompt_version",
                f"expected {CHAPTER_ANALYZER_PROMPT_VERSION}",
            )
        )
    if fixture.source.get("version_kind") not in {"ORIGINAL", "ACCEPTED"}:
        failures.append(
            GoldenFailure(
                fixture.fixture_id,
                "source.version_kind",
                "official analysis source must be ORIGINAL or ACCEPTED",
            )
        )
    try:
        payload = parse_chapter_analysis_payload(fixture.baseline_payload)
    except AnalysisError as exc:
        failures.append(
            GoldenFailure(fixture.fixture_id, "baseline_payload", exc.message)
        )
        return failures
    failures.extend(compare_key_facts(payload, fixture.required, fixture_id=fixture.fixture_id))
    return failures


def format_failures(failures: list[GoldenFailure]) -> str:
    if not failures:
        return "ok"
    return "\n".join(item.report() for item in failures)


def run_cli(argv: list[str] | None = None) -> int:
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(description="Chapter analysis golden contract")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call local Analyzer. Not Windows GPU evidence.",
    )
    args = parser.parse_args(argv)
    fixtures = iter_golden_fixtures()
    failures: list[GoldenFailure] = []
    for fixture in fixtures:
        failures.extend(check_fixture_contract(fixture))
    if failures:
        print(format_failures(failures), file=sys.stderr)
        return 1
    print(f"golden contract ok ({len(fixtures)} fixtures)")
    if not args.live:
        return 0
    if os.getenv("LNS_OLLAMA_SMOKE") != "1":
        print("skip live: set LNS_OLLAMA_SMOKE=1; not verification:gpu evidence")
        return 0
    import asyncio

    from app.adapters.ollama.adapter import OllamaAdapter
    from app.services.chapter_analyzer import analyze_chapter_text
    from app.settings import get_settings

    settings = get_settings()
    adapter = OllamaAdapter(settings)

    async def _run() -> int:
        health = await adapter.health()
        if not health.reachable or not health.default_model_installed:
            print("skip live: local Ollama/model unavailable; not GPU evidence")
            await adapter.aclose()
            return 0
        live_failures: list[GoldenFailure] = []
        for fixture in fixtures:
            result = await analyze_chapter_text(adapter, fixture.chapter_body)
            live_failures.extend(
                compare_key_facts(result.payload, fixture.required, fixture_id=fixture.fixture_id)
            )
        await adapter.aclose()
        if live_failures:
            print(format_failures(live_failures), file=sys.stderr)
            return 1
        print("live contract ok (CPU/local smoke, not WINDOWS_GPU evidence)")
        return 0

    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(run_cli())
