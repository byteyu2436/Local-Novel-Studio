from sqlalchemy.orm import Session

from app.adapters.embedding.types import EmbeddingProvider
from app.adapters.milvus.collections import MilvusCollectionClient
from app.domain.retrieval import evidence_from_chunk
from app.schemas.retrieval import MatchReason, RetrievalQuery, RetrievalResult, result_for_query
from app.services.canon_chunks import list_canon_chunks
from app.services.embedding_batches import embed_query_text
from app.services.embedding_profiles import require_active_embedding_profile
from app.services.index_registry import require_serving_index
from app.services.milvus_vectors import retrieval_filter

DENSE_CANDIDATE_LIMIT = 24
_OUTPUT_FIELDS = [
    "chunk_id",
    "novel_id",
    "chapter_id",
    "text_hash",
    "canon_status",
]


class DenseRetrievalError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def dense_retrieve(
    session: Session,
    client: MilvusCollectionClient,
    provider: EmbeddingProvider,
    query: RetrievalQuery,
    *,
    candidate_limit: int | None = None,
    skipped: list[dict] | None = None,
) -> RetrievalResult:
    """Recall Canon chunks from the active index. Later stages rank and trim."""

    limit = DENSE_CANDIDATE_LIMIT if candidate_limit is None else candidate_limit
    if limit < 1 or limit > 100:
        raise DenseRetrievalError(
            "candidate_limit_invalid",
            "Dense candidate limit must be between 1 and 100.",
        )
    profile = require_active_embedding_profile(session)
    index = require_serving_index(session)
    if index.embedding_profile_id != profile.id or index.index_version != profile.index_version:
        raise DenseRetrievalError(
            "index_profile_mismatch",
            "The active index does not match the active embedding profile.",
        )
    if query.corpus != "canon" or query.include_draft:
        raise DenseRetrievalError(
            "draft_retrieval_unsupported",
            "Dense retrieval reads the official Canon index only.",
        )
    text = query.semantic_query_text.strip() or query.chapter_goal.strip()
    if not text:
        raise DenseRetrievalError(
            "query_text_empty",
            "Dense retrieval needs a semantic query or a chapter goal.",
        )
    vector = await embed_query_text(session, provider, text, profile_id=profile.id)
    hits = await client.search(
        index.collection_name,
        vector,
        filter_expr=retrieval_filter(
            novel_id=query.novel_id,
            characters=list(query.metadata_hints.characters),
            locations=list(query.metadata_hints.locations),
        ),
        limit=limit,
        output_fields=list(_OUTPUT_FIELDS),
    )
    chunks = {chunk.id: chunk for chunk in list_canon_chunks(session, query.novel_id)}
    evidence = []
    for hit in hits:
        chunk = chunks.get(hit.chunk_id)
        if chunk is None:
            _skip(skipped, hit, "not_in_canon")
            continue
        if chunk.novel_id != query.novel_id or hit.novel_id != query.novel_id:
            _skip(skipped, hit, "cross_novel")
            continue
        if hit.canon_status != "active":
            _skip(skipped, hit, "inactive")
            continue
        if hit.text_hash and hit.text_hash != chunk.text_checksum:
            _skip(skipped, hit, "stale_chunk")
            continue
        evidence.append(
            evidence_from_chunk(
                chunk,
                scoring_profile_version=query.scoring_profile_version,
                dense_score=hit.score,
                match_reasons=[MatchReason(code="dense", detail="milvus_cosine")],
                embedding_profile_id=profile.id,
                index_version=index.index_version,
            )
        )
    return result_for_query(
        query,
        evidence,
        embedding_profile_id=profile.id,
        index_version=index.index_version,
        collection_name=index.collection_name,
    )


def _skip(skipped: list[dict] | None, hit, reason: str) -> None:
    if skipped is None:
        return
    skipped.append(
        {
            "chunk_id": hit.chunk_id,
            "chapter_id": hit.chapter_id,
            "novel_id": hit.novel_id,
            "dense_score": hit.score,
            "reason": reason,
        }
    )
