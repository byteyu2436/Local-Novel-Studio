import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

BENCHMARK_CATEGORIES = (
    "character",
    "relationship",
    "event",
    "location",
    "foreshadowing",
    "timeline",
)


class GoldSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_sequence: int = Field(ge=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    excerpt: str = Field(min_length=1)


class BenchmarkQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1)
    category: str
    goal: str = Field(min_length=1)
    characters: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    previous_chapter_state: str = ""
    expected_chapters: list[int] = Field(min_length=1)
    gold: list[GoldSource] = Field(min_length=1)

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        if value not in BENCHMARK_CATEGORIES:
            raise ValueError("unknown benchmark category")
        return value


class BenchmarkChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)


class BenchmarkDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    novel_fixture_id: str = Field(min_length=1)
    chapters: list[BenchmarkChapter] = Field(min_length=1)
    queries: list[BenchmarkQuery] = Field(min_length=1)


class QueryScore(BaseModel):
    query_id: str
    category: str
    recall_at_5: float
    recall_at_10: float
    source_hit: bool
    expected_chapters: list[int]
    actual_chapters: list[int]
    missing_chapters: list[int]


@dataclass
class BenchmarkResult:
    dataset_version: str
    novel_fixture_id: str
    chunking_version: str
    embedding_profile_id: str
    index_version: str
    scoring_profile_version: str
    collection_name: str
    recall_at_5: float
    recall_at_10: float
    source_hit_rate: float
    by_category: dict[str, dict[str, float]]
    queries: list[QueryScore] = field(default_factory=list)
    elapsed_ms: int = 0

    @property
    def failures(self) -> list[QueryScore]:
        return [item for item in self.queries if not item.source_hit or item.recall_at_10 < 1]


def dataset_path() -> Path:
    return Path(__file__).parent / "fixtures" / "retrieval_benchmark_v1.json"


def load_benchmark_dataset(path: Path | None = None) -> BenchmarkDataset:
    raw = json.loads((path or dataset_path()).read_text(encoding="utf-8"))
    dataset = BenchmarkDataset.model_validate(raw)
    _require_gold_in_canon(dataset)
    categories = {item.category for item in dataset.queries}
    missing = [name for name in BENCHMARK_CATEGORIES if name not in categories]
    if missing:
        raise ValueError(f"benchmark dataset misses categories: {', '.join(missing)}")
    return dataset


def recall_at_k(expected: list[int], actual: list[int], k: int) -> float:
    gold = set(expected)
    if not gold:
        return 1.0
    return len(gold & set(actual[:k])) / len(gold)


def source_hit(gold: list[GoldSource], evidence: list[dict]) -> bool:
    for item in gold:
        for row in evidence:
            if row.get("chapter_sequence") != item.chapter_sequence:
                continue
            start = int(row.get("start_offset") or 0)
            end = int(row.get("end_offset") or 0)
            if start < item.end_offset and end > item.start_offset:
                return True
    return False


def score_query(query: BenchmarkQuery, evidence: list[dict]) -> QueryScore:
    actual = [int(row["chapter_sequence"]) for row in evidence if "chapter_sequence" in row]
    expected = list(query.expected_chapters)
    return QueryScore(
        query_id=query.query_id,
        category=query.category,
        recall_at_5=recall_at_k(expected, actual, 5),
        recall_at_10=recall_at_k(expected, actual, 10),
        source_hit=source_hit(query.gold, evidence),
        expected_chapters=expected,
        actual_chapters=actual,
        missing_chapters=[item for item in expected if item not in actual],
    )


def summarize(
    dataset: BenchmarkDataset, scores: list[QueryScore], **profiles: str
) -> BenchmarkResult:
    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    by_category: dict[str, dict[str, float]] = {}
    for category in BENCHMARK_CATEGORIES:
        rows = [item for item in scores if item.category == category]
        by_category[category] = {
            "recall_at_5": _mean([item.recall_at_5 for item in rows]),
            "recall_at_10": _mean([item.recall_at_10 for item in rows]),
            "source_hit_rate": _mean([1.0 if item.source_hit else 0.0 for item in rows]),
        }
    return BenchmarkResult(
        dataset_version=dataset.version,
        novel_fixture_id=dataset.novel_fixture_id,
        chunking_version=profiles.get("chunking_version", ""),
        embedding_profile_id=profiles.get("embedding_profile_id", ""),
        index_version=profiles.get("index_version", ""),
        scoring_profile_version=profiles.get("scoring_profile_version", ""),
        collection_name=profiles.get("collection_name", ""),
        recall_at_5=_mean([item.recall_at_5 for item in scores]),
        recall_at_10=_mean([item.recall_at_10 for item in scores]),
        source_hit_rate=_mean([1.0 if item.source_hit else 0.0 for item in scores]),
        by_category=by_category,
        queries=scores,
    )


def _require_gold_in_canon(dataset: BenchmarkDataset) -> None:
    chapters = {item.sequence: item.body for item in dataset.chapters}
    for query in dataset.queries:
        for gold in query.gold:
            body = chapters.get(gold.chapter_sequence)
            if body is None:
                raise ValueError(f"{query.query_id} points at a missing chapter")
            if body[gold.start_offset : gold.end_offset] != gold.excerpt:
                raise ValueError(f"{query.query_id} gold excerpt is not in the fixture")
