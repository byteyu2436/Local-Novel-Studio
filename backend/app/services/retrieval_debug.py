import logging

from app.domain.evidence_selection import RejectedEvidence
from app.schemas.retrieval import RetrievalQuery, RetrievalResult
from app.schemas.retrieval_debug import DebugCandidate, RetrievalDebugTrace

logger = logging.getLogger("app.retrieval")
_EXCERPT = 40


def build_debug_trace(
    *,
    query: RetrievalQuery,
    filter_expr: str,
    scored: RetrievalResult,
    rejected: list[RejectedEvidence],
    skipped: list[dict],
    selection_version: str,
    final_ids: list[str],
) -> RetrievalDebugTrace:
    candidates: list[DebugCandidate] = []
    for item in scored.evidence:
        if item.chunk_id in final_ids:
            status = "selected"
            reason = "selected"
            kept_id = None
        else:
            match = next((row for row in rejected if row.evidence.chunk_id == item.chunk_id), None)
            status = "rejected"
            reason = match.reason if match is not None else "evidence_limit"
            kept_id = match.kept_chunk_id if match is not None else None
        candidates.append(
            DebugCandidate(
                chunk_id=item.chunk_id,
                chapter_id=item.chapter_id,
                source_version_id=item.provenance.source_version_id,
                dense_score=item.dense_score,
                business_score=item.business_score,
                final_score=item.final_score,
                match_reasons=[reason_row.code for reason_row in item.match_reasons],
                score_breakdown=dict(item.metadata),
                status=status,  # type: ignore[arg-type]
                reason=reason,
                kept_chunk_id=kept_id,
                excerpt=item.evidence_text[:_EXCERPT],
            )
        )
    for row in skipped:
        candidates.append(
            DebugCandidate(
                chunk_id=str(row.get("chunk_id") or "unknown"),
                chapter_id=str(row.get("chapter_id") or ""),
                dense_score=row.get("dense_score"),
                status="filtered",
                reason=str(row.get("reason") or "filtered"),
            )
        )
    dense_count = len(scored.evidence) + len(skipped)
    stages = {
        "query": "ok" if query.semantic_query_text.strip() else "empty",
        "filter": "ok" if query.novel_id in filter_expr else "empty",
        "dense": "ok" if dense_count else "empty",
        "scoring": "ok" if scored.evidence else "empty",
        "selection": "ok" if final_ids else "empty",
    }
    return RetrievalDebugTrace(
        query=query,
        filter_expr=filter_expr,
        query_builder_version=query.query_builder_version,
        scoring_profile_version=scored.scoring_profile_version,
        selection_version=selection_version,
        embedding_profile_id=scored.embedding_profile_id,
        index_version=scored.index_version,
        collection_name=scored.collection_name,
        stages=stages,
        candidates=candidates,
        final_evidence_ids=list(final_ids),
    )


def retrieval_log_payload(result: RetrievalResult, *, elapsed_ms: int) -> dict[str, object]:
    """Ordinary logs keep ids and counts. They do not keep prose or vectors."""

    return {
        "novel_id": result.novel_id,
        "evidence_ids": [item.chunk_id for item in result.evidence],
        "evidence_count": len(result.evidence),
        "elapsed_ms": elapsed_ms,
    }


def log_retrieval(result: RetrievalResult, *, elapsed_ms: int) -> None:
    logger.info("retrieval %s", retrieval_log_payload(result, elapsed_ms=elapsed_ms))
