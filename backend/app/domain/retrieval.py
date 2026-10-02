from app.adapters.sqlite.chunks import CanonChunk
from app.schemas.retrieval import (
    EvidenceProvenance,
    MatchReason,
    RetrievalEvidence,
)


class RetrievalContractError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def evidence_from_chunk(
    chunk: CanonChunk,
    *,
    scoring_profile_version: str,
    dense_score: float | None = None,
    business_score: float | None = None,
    final_score: float | None = None,
    match_reasons: list[MatchReason] | None = None,
    embedding_profile_id: str | None = None,
    index_version: str | None = None,
) -> RetrievalEvidence:
    """Map one active Canon chunk to evidence a Reader chapter can open."""

    if chunk.canon_status != "active":
        raise RetrievalContractError(
            "chunk_not_active",
            "Only an active Canon chunk can become retrieval evidence.",
        )
    if chunk.source_version_kind not in {"ORIGINAL", "ACCEPTED"}:
        raise RetrievalContractError(
            "draft_cannot_be_canon_evidence",
            "Draft text cannot enter the default Canon retrieval result.",
        )
    return RetrievalEvidence(
        chunk_id=chunk.id,
        chapter_id=chunk.chapter_id,
        novel_id=chunk.novel_id,
        evidence_text=chunk.text,
        dense_score=dense_score,
        business_score=business_score,
        final_score=final_score,
        match_reasons=list(match_reasons or []),
        metadata={
            "chunking_version": chunk.chunking_version,
            "importance": chunk.importance,
        },
        provenance=EvidenceProvenance(
            novel_id=chunk.novel_id,
            chapter_id=chunk.chapter_id,
            chunk_id=chunk.id,
            source_version_id=chunk.source_version_id,
            source_version_kind=chunk.source_version_kind,
            chunking_version=chunk.chunking_version,
            text_checksum=chunk.text_checksum,
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            sequence=chunk.sequence,
        ),
        scoring_profile_version=scoring_profile_version,
        embedding_profile_id=embedding_profile_id or chunk.embedding_profile_id,
        index_version=index_version,
    )
