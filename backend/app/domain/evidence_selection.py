from dataclasses import dataclass

from app.adapters.sqlite.chunks import CanonChunk
from app.schemas.retrieval import RetrievalEvidence, RetrievalResult

SELECTION_VERSION = "evidence-selection.v1"


@dataclass(frozen=True)
class EvidenceSelectionProfile:
    """How many ranked candidates become evidence. Weights stay in the scoring profile."""

    version: str = SELECTION_VERSION
    candidate_limit: int = 24
    evidence_limit: int = 6
    overlap_ratio: float = 0.5

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("selection version is required")
        if self.candidate_limit < 1 or self.evidence_limit < 1:
            raise ValueError("selection limits must be positive")
        if self.evidence_limit > self.candidate_limit:
            raise ValueError("evidence_limit cannot exceed candidate_limit")
        if not 0 <= self.overlap_ratio <= 1:
            raise ValueError("overlap_ratio must be between 0 and 1")


@dataclass(frozen=True)
class RejectedEvidence:
    evidence: RetrievalEvidence
    reason: str
    kept_chunk_id: str | None = None


@dataclass(frozen=True)
class EvidenceSelection:
    result: RetrievalResult
    rejected: list[RejectedEvidence]
    version: str
    candidate_limit: int
    evidence_limit: int


def select_top_evidence(
    result: RetrievalResult,
    chunks: list[CanonChunk],
    profile: EvidenceSelectionProfile | None = None,
) -> EvidenceSelection:
    """Keep the highest-scoring non-overlapping evidence. Provenance stays intact."""

    resolved = profile or EvidenceSelectionProfile()
    by_id = {chunk.id: chunk for chunk in chunks}
    ordered = sorted(
        result.evidence,
        key=lambda item: (-(item.final_score or 0.0), item.chunk_id),
    )
    window = ordered[: resolved.candidate_limit]
    kept: list[RetrievalEvidence] = []
    rejected: list[RejectedEvidence] = []
    for item in window:
        reason, kept_id = _rejection(item, kept, by_id, resolved.overlap_ratio)
        if reason is not None:
            rejected.append(RejectedEvidence(item, reason, kept_id))
            continue
        if len(kept) >= resolved.evidence_limit:
            rejected.append(RejectedEvidence(item, "evidence_limit", None))
            continue
        kept.append(item)
    for item in ordered[resolved.candidate_limit :]:
        rejected.append(RejectedEvidence(item, "candidate_limit", None))
    return EvidenceSelection(
        result=result.model_copy(update={"evidence": kept}),
        rejected=rejected,
        version=resolved.version,
        candidate_limit=resolved.candidate_limit,
        evidence_limit=resolved.evidence_limit,
    )


def _rejection(
    item: RetrievalEvidence,
    kept: list[RetrievalEvidence],
    chunks: dict[str, CanonChunk],
    overlap_ratio: float,
) -> tuple[str | None, str | None]:
    current = chunks.get(item.chunk_id)
    for chosen in kept:
        other = chunks.get(chosen.chunk_id)
        if current is None or other is None:
            continue
        if current.chapter_id != other.chapter_id:
            continue
        if current.text_checksum == other.text_checksum:
            return "duplicate_checksum", chosen.chunk_id
        shared = _overlap_ratio(current, other)
        if shared >= overlap_ratio:
            return "overlap", chosen.chunk_id
        if abs(current.chunk_index - other.chunk_index) == 1 and shared > 0:
            return "adjacent_overlap", chosen.chunk_id
    return None, None


def _overlap_ratio(left: CanonChunk, right: CanonChunk) -> float:
    start = max(left.start_offset, right.start_offset)
    end = min(left.end_offset, right.end_offset)
    if end <= start:
        return 0.0
    shorter = min(left.end_offset - left.start_offset, right.end_offset - right.start_offset)
    if shorter <= 0:
        return 0.0
    return (end - start) / shorter
