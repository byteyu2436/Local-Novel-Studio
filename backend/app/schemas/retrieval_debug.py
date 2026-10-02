from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.retrieval import RetrievalQuery

CandidateStatus = Literal["selected", "rejected", "filtered"]


class DebugCandidate(BaseModel):
    """One recall row. Vectors and full chapter text stay out of this payload."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1)
    chapter_id: str = ""
    source_version_id: str | None = None
    dense_score: float | None = None
    business_score: float | None = None
    final_score: float | None = None
    match_reasons: list[str] = Field(default_factory=list)
    score_breakdown: dict[str, str] = Field(default_factory=dict)
    status: CandidateStatus
    reason: str = Field(min_length=1)
    kept_chunk_id: str | None = None
    excerpt: str = ""


class RetrievalDebugTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: RetrievalQuery
    filter_expr: str
    query_builder_version: str
    scoring_profile_version: str
    selection_version: str
    embedding_profile_id: str | None = None
    index_version: str | None = None
    collection_name: str | None = None
    stages: dict[str, str]
    candidates: list[DebugCandidate]
    final_evidence_ids: list[str]
