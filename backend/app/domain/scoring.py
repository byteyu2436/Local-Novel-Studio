from dataclasses import dataclass

from app.adapters.sqlite.chunks import CanonChunk
from app.schemas.retrieval import (
    SCORING_PROFILE_VERSION,
    MatchReason,
    RetrievalEvidence,
    RetrievalQuery,
    RetrievalResult,
)

IMPORTANCE_SCORES = {"low": 0.2, "medium": 0.6, "high": 1.0}


@dataclass(frozen=True)
class RetrievalScoringProfile:
    """Weights for one scoring version. Callers change weights here, not in rank code."""

    version: str = SCORING_PROFILE_VERSION
    dense: float = 0.40
    character_match: float = 0.20
    location_match: float = 0.10
    event_match: float = 0.10
    foreshadowing_match: float = 0.05
    recency: float = 0.10
    importance: float = 0.05

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("scoring profile version is required")
        for name in (
            "dense",
            "character_match",
            "location_match",
            "event_match",
            "foreshadowing_match",
            "recency",
            "importance",
        ):
            weight = getattr(self, name)
            if weight < 0:
                raise ValueError(f"{name} weight must be zero or positive")


def default_scoring_profile() -> RetrievalScoringProfile:
    return RetrievalScoringProfile()


def apply_scoring(
    result: RetrievalResult,
    query: RetrievalQuery,
    chunks: list[CanonChunk],
    profile: RetrievalScoringProfile | None = None,
) -> RetrievalResult:
    """Rank dense candidates. Does not drop, embed, or call Milvus."""

    resolved = profile or default_scoring_profile()
    by_id = {chunk.id: chunk for chunk in chunks}
    max_sequence = max((chunk.sequence for chunk in chunks), default=1)
    ranked: list[tuple[float, str, RetrievalEvidence]] = []
    for item in result.evidence:
        chunk = by_id.get(item.chunk_id)
        scored = _score_one(item, query, chunk, resolved, max_sequence)
        ranked.append((scored.final_score or 0.0, scored.chunk_id, scored))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return result.model_copy(
        update={
            "scoring_profile_version": resolved.version,
            "evidence": [row[2] for row in ranked],
        }
    )


def _score_one(
    item: RetrievalEvidence,
    query: RetrievalQuery,
    chunk: CanonChunk | None,
    profile: RetrievalScoringProfile,
    max_sequence: int,
) -> RetrievalEvidence:
    dense = _unit(item.dense_score)
    character = _ratio(query.characters, _labels(chunk, "characters"))
    location = _ratio(query.locations, _labels(chunk, "locations"))
    event_ids = _labels(chunk, "event_ids")
    event = _ratio(query.events, event_ids)
    foreshadowing = _ratio(query.foreshadowing, event_ids)
    recency = 0.0 if chunk is None else chunk.sequence / max_sequence
    importance = IMPORTANCE_SCORES.get(chunk.importance, 0.0) if chunk is not None else 0.0
    parts = {
        "dense": profile.dense * dense,
        "character_match": profile.character_match * character,
        "location_match": profile.location_match * location,
        "event_match": profile.event_match * event,
        "foreshadowing_match": profile.foreshadowing_match * foreshadowing,
        "recency": profile.recency * recency,
        "importance": profile.importance * importance,
    }
    final = sum(parts.values())
    business = final - parts["dense"]
    reasons = [reason for reason in item.match_reasons if reason.code != "business"]
    for code, contribution in parts.items():
        if contribution > 0:
            reasons.append(MatchReason(code=code, detail=f"{contribution:.6f}"))
    metadata = dict(item.metadata)
    metadata.update({code: f"{value:.6f}" for code, value in parts.items()})
    return item.model_copy(
        update={
            "business_score": business,
            "final_score": final,
            "match_reasons": reasons,
            "metadata": metadata,
            "scoring_profile_version": profile.version,
        }
    )


def _labels(chunk: CanonChunk | None, field: str) -> list[str]:
    if chunk is None:
        return []
    values = getattr(chunk, field) or []
    return [str(value) for value in values]


def _ratio(hints: list[str], values: list[str]) -> float:
    wanted = [hint.strip() for hint in hints if hint.strip()]
    if not wanted:
        return 0.0
    found = set(values)
    return sum(1 for hint in wanted if hint in found) / len(wanted)


def _unit(score: float | None) -> float:
    if score is None or score <= 0:
        return 0.0
    if score >= 1:
        return 1.0
    return score
