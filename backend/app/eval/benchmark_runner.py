import time

from sqlalchemy.orm import Session

from app.adapters.embedding.types import EmbeddingProvider
from app.adapters.milvus.collections import MilvusCollectionClient
from app.eval.benchmark import (
    BenchmarkDataset,
    BenchmarkResult,
    load_benchmark_dataset,
    score_query,
    summarize,
)
from app.schemas.retrieval import QueryBuilderInput
from app.services import catalog
from app.services.retrieval import retrieve_evidence


async def run_benchmark(
    session: Session,
    client: MilvusCollectionClient,
    provider: EmbeddingProvider,
    novel_id: str,
    *,
    dataset: BenchmarkDataset | None = None,
    chapter_sequences: dict[str, int] | None = None,
) -> BenchmarkResult:
    """Score the fixed dataset through the same retrieval path the product uses."""

    started = time.perf_counter()
    loaded = dataset or load_benchmark_dataset()
    sequences = chapter_sequences or {
        chapter.id: chapter.sequence for chapter in catalog.list_chapters(session, novel_id)
    }
    scores = []
    last = None
    for query in loaded.queries:
        report = await retrieve_evidence(
            session,
            client,
            provider,
            QueryBuilderInput(
                novel_id=novel_id,
                chapter_goal=query.goal,
                characters=list(query.characters),
                locations=list(query.locations),
                events=list(query.events),
                foreshadowing=list(query.foreshadowing),
                previous_chapter_state=query.previous_chapter_state,
                top_n=10,
            ),
        )
        last = report
        evidence = [
            {
                "chapter_sequence": sequences.get(item.chapter_id, 0),
                "start_offset": item.provenance.start_offset,
                "end_offset": item.provenance.end_offset,
            }
            for item in report.result.evidence
        ]
        scores.append(score_query(query, evidence))
    result = summarize(
        loaded,
        scores,
        chunking_version="chunking.v1",
        embedding_profile_id=last.result.embedding_profile_id or "" if last else "",
        index_version=last.result.index_version or "" if last else "",
        scoring_profile_version=last.result.scoring_profile_version if last else "",
        collection_name=last.result.collection_name or "" if last else "",
    )
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
