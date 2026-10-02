import math
import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.adapters.embedding.errors import EmbeddingError
from app.adapters.embedding.types import EmbeddingProvider
from app.adapters.milvus.collections import MilvusCollectionClient
from app.domain.catalog import CatalogError
from app.domain.evidence_selection import (
    EvidenceSelectionProfile,
    RejectedEvidence,
    select_top_evidence,
)
from app.domain.milvus_collection import MilvusCollectionError
from app.domain.scoring import RetrievalScoringProfile, apply_scoring, default_scoring_profile
from app.schemas.retrieval import QueryBuilderInput, RetrievalResult
from app.schemas.retrieval_debug import RetrievalDebugTrace
from app.services import catalog
from app.services.canon_chunks import list_canon_chunks
from app.services.dense_retrieval import DenseRetrievalError, dense_retrieve
from app.services.index_registry import IndexRegistryError
from app.services.milvus_vectors import retrieval_filter
from app.services.query_builder import build_retrieval_query, load_memory_hints
from app.services.retrieval_debug import build_debug_trace, log_retrieval


class RetrievalServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RetrievalReport:
    result: RetrievalResult
    rejected: list[RejectedEvidence]
    query_builder_version: str
    selection_version: str
    elapsed_ms: int
    trace: RetrievalDebugTrace | None = field(default=None)

    @property
    def empty(self) -> bool:
        return not self.result.evidence


async def retrieve_evidence(
    session: Session,
    client: MilvusCollectionClient,
    provider: EmbeddingProvider,
    context: QueryBuilderInput,
    *,
    scoring: RetrievalScoringProfile | None = None,
    selection: EvidenceSelectionProfile | None = None,
    debug: bool = False,
) -> RetrievalReport:
    """Run query, dense recall, scoring, and top-evidence selection once."""

    started = time.perf_counter()
    scoring_profile = scoring or default_scoring_profile()
    selection_profile = selection or EvidenceSelectionProfile()
    try:
        catalog.require_novel(session, context.novel_id)
        query = build_retrieval_query(context, load_memory_hints(session, context.novel_id))
        skipped: list[dict] = []
        dense = await dense_retrieve(
            session,
            client,
            provider,
            query,
            candidate_limit=selection_profile.candidate_limit,
            skipped=skipped,
        )
    except CatalogError as exc:
        raise RetrievalServiceError(exc.code, exc.message) from exc
    except IndexRegistryError as exc:
        raise RetrievalServiceError(exc.code, exc.message) from exc
    except EmbeddingError as exc:
        raise RetrievalServiceError(exc.code, str(exc)) from exc
    except DenseRetrievalError as exc:
        raise RetrievalServiceError(exc.code, exc.message) from exc
    except MilvusCollectionError as exc:
        raise RetrievalServiceError(exc.code, exc.message) from exc
    chunks = list_canon_chunks(session, context.novel_id)
    scored = apply_scoring(dense, query, chunks, scoring_profile)
    chosen = select_top_evidence(scored, chunks, selection_profile)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    final_ids = [item.chunk_id for item in chosen.result.evidence]
    trace = None
    if debug:
        trace = build_debug_trace(
            query=query,
            filter_expr=retrieval_filter(
                novel_id=query.novel_id,
                characters=list(query.metadata_hints.characters),
                locations=list(query.metadata_hints.locations),
            ),
            scored=scored,
            rejected=chosen.rejected,
            skipped=skipped,
            selection_version=chosen.version,
            final_ids=final_ids,
        )
    log_retrieval(chosen.result, elapsed_ms=elapsed_ms)
    return RetrievalReport(
        result=chosen.result,
        rejected=chosen.rejected,
        query_builder_version=query.query_builder_version,
        selection_version=chosen.version,
        elapsed_ms=elapsed_ms,
        trace=trace,
    )


def summarize_latency(samples_ms: list[int]) -> dict[str, int]:
    """Nearest-rank P50/P95 for local observation. Not a performance gate."""

    if not samples_ms:
        raise RetrievalServiceError("latency_empty", "Latency summary needs at least one sample.")
    ordered = sorted(samples_ms)
    return {
        "p50": _nearest_rank(ordered, 0.50),
        "p95": _nearest_rank(ordered, 0.95),
        "n": len(ordered),
    }


def _nearest_rank(ordered: list[int], fraction: float) -> int:
    index = math.ceil(fraction * len(ordered)) - 1
    return ordered[min(max(index, 0), len(ordered) - 1)]
