import json
from pathlib import Path

from app.eval.benchmark import BENCHMARK_CATEGORIES, BenchmarkResult


def result_payload(result: BenchmarkResult) -> dict:
    return {
        "dataset_version": result.dataset_version,
        "novel_fixture_id": result.novel_fixture_id,
        "chunking_version": result.chunking_version,
        "embedding_profile_id": result.embedding_profile_id,
        "index_version": result.index_version,
        "scoring_profile_version": result.scoring_profile_version,
        "collection_name": result.collection_name,
        "elapsed_ms": result.elapsed_ms,
        "recall_at_5": result.recall_at_5,
        "recall_at_10": result.recall_at_10,
        "source_hit_rate": result.source_hit_rate,
        "by_category": result.by_category,
        "failures": [
            {
                "query_id": item.query_id,
                "category": item.category,
                "expected_chapters": item.expected_chapters,
                "actual_chapters": item.actual_chapters,
                "missing_chapters": item.missing_chapters,
                "source_hit": item.source_hit,
            }
            for item in result.failures
        ],
    }


def write_benchmark_report(result: BenchmarkResult, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    payload = result_payload(result)
    json_path = directory / "benchmark.json"
    md_path = directory / "benchmark.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return json_path, md_path


def compare_reports(before: dict, after: dict) -> dict:
    keys = ("chunking_version", "embedding_profile_id", "index_version", "scoring_profile_version")
    changed = [key for key in keys if before.get(key) != after.get(key)]
    deltas = {
        name: float(after.get(name) or 0) - float(before.get(name) or 0)
        for name in ("recall_at_5", "recall_at_10", "source_hit_rate")
    }
    category_deltas = {}
    for category in BENCHMARK_CATEGORIES:
        left = (before.get("by_category") or {}).get(category) or {}
        right = (after.get("by_category") or {}).get(category) or {}
        category_deltas[category] = {
            "recall_at_5": float(right.get("recall_at_5") or 0)
            - float(left.get("recall_at_5") or 0)
        }
    return {
        "comparable": not changed,
        "profile_changes": changed,
        "warning": "profile_mismatch" if changed else "",
        "deltas": deltas,
        "category_deltas": category_deltas,
    }


def _markdown(payload: dict) -> str:
    lines = [
        "# Retrieval benchmark",
        "",
        f"- dataset: {payload['dataset_version']}",
        f"- chunking: {payload['chunking_version']}",
        f"- embedding profile: {payload['embedding_profile_id']}",
        f"- index: {payload['index_version']}",
        f"- scoring: {payload['scoring_profile_version']}",
        f"- collection: {payload['collection_name']}",
        f"- Recall@5: {payload['recall_at_5']}",
        f"- Recall@10: {payload['recall_at_10']}",
        f"- source hit rate: {payload['source_hit_rate']}",
        "",
        "## Failures",
    ]
    failures = payload["failures"]
    if not failures:
        lines.append("- none")
    for item in failures:
        lines.append(
            f"- {item['query_id']}: expected {item['expected_chapters']}, "
            f"actual {item['actual_chapters']}, missing {item['missing_chapters']}"
        )
    return "\n".join(lines) + "\n"
