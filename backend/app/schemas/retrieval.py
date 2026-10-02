from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QUERY_PROFILE_VERSION = "retrieval-query.v1"
FILTER_PROFILE_VERSION = "retrieval-filter.v1"
SCORING_PROFILE_VERSION = "retrieval-scoring.v1"
QUERY_BUILDER_VERSION = "query-builder.v1"

CorpusScope = Literal["canon", "draft"]
SourceVersionKind = Literal["ORIGINAL", "ACCEPTED"]


class MetadataHints(BaseModel):
    """Exact entity names for a later metadata filter. Not a Milvus expression."""

    model_config = ConfigDict(extra="forbid")

    characters: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)


class RetrievalFilters(BaseModel):
    """Canon filters only. Draft text is not a filter value on this object."""

    model_config = ConfigDict(extra="forbid")

    canon_status: Literal["active"] = "active"
    source_version_kinds: list[SourceVersionKind] = Field(
        default_factory=lambda: ["ORIGINAL", "ACCEPTED"]
    )
    chapter_ids: list[str] = Field(default_factory=list)


class QueryBuilderInput(BaseModel):
    """Chapter-planning context. Missing fields stay empty and the builder degrades."""

    model_config = ConfigDict(extra="forbid")

    novel_id: str = Field(min_length=1)
    chapter_goal: str = ""
    current_scene: str = ""
    characters: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    previous_chapter_state: str = ""
    top_n: int = Field(default=8, ge=1, le=100)


class RetrievalQuery(BaseModel):
    """Structured retrieval request. Embedding and search happen later."""

    model_config = ConfigDict(extra="forbid")

    novel_id: str = Field(min_length=1)
    chapter_goal: str = ""
    current_scene: str = ""
    characters: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    previous_chapter_state: str = ""
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    top_n: int = Field(default=8, ge=1, le=100)
    query_profile_version: str = Field(default=QUERY_PROFILE_VERSION, min_length=1)
    filter_profile_version: str = Field(default=FILTER_PROFILE_VERSION, min_length=1)
    scoring_profile_version: str = Field(default=SCORING_PROFILE_VERSION, min_length=1)
    semantic_query_text: str = ""
    metadata_hints: MetadataHints = Field(default_factory=MetadataHints)
    query_builder_version: str = Field(default=QUERY_BUILDER_VERSION, min_length=1)
    corpus: CorpusScope = "canon"
    include_draft: bool = False

    @model_validator(mode="after")
    def draft_query_is_explicit(self) -> "RetrievalQuery":
        if self.corpus == "draft" and not self.include_draft:
            raise ValueError("draft_query_must_be_explicit")
        if self.include_draft and self.corpus != "draft":
            raise ValueError("draft_query_must_set_corpus")
        return self


class MatchReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    detail: str = ""


class EvidenceProvenance(BaseModel):
    """Locates one evidence span in a Canon chunk and its Reader chapter."""

    model_config = ConfigDict(extra="forbid")

    novel_id: str = Field(min_length=1)
    chapter_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    source_version_id: str = Field(min_length=1)
    source_version_kind: SourceVersionKind
    chunking_version: str = Field(min_length=1)
    text_checksum: str = Field(min_length=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    sequence: int = Field(ge=1)

    @model_validator(mode="after")
    def offsets_span_the_evidence(self) -> "EvidenceProvenance":
        if self.end_offset <= self.start_offset:
            raise ValueError("evidence_offsets_invalid")
        return self


class RetrievalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1)
    chapter_id: str = Field(min_length=1)
    novel_id: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    dense_score: float | None = None
    business_score: float | None = None
    final_score: float | None = None
    match_reasons: list[MatchReason] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    provenance: EvidenceProvenance
    scoring_profile_version: str = Field(min_length=1)
    embedding_profile_id: str | None = None
    index_version: str | None = None

    @model_validator(mode="after")
    def provenance_matches_evidence(self) -> "RetrievalEvidence":
        same_chunk = self.provenance.chunk_id == self.chunk_id
        same_chapter = self.provenance.chapter_id == self.chapter_id
        same_novel = self.provenance.novel_id == self.novel_id
        if not (same_chunk and same_chapter and same_novel):
            raise ValueError("evidence_provenance_mismatch")
        return self


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str = Field(min_length=1)
    query_profile_version: str = Field(min_length=1)
    filter_profile_version: str = Field(min_length=1)
    scoring_profile_version: str = Field(min_length=1)
    embedding_profile_id: str | None = None
    index_version: str | None = None
    collection_name: str | None = None
    corpus: CorpusScope = "canon"
    include_draft: bool = False
    evidence: list[RetrievalEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def evidence_stays_inside_the_query_scope(self) -> "RetrievalResult":
        if self.corpus == "draft" and not self.include_draft:
            raise ValueError("draft_result_must_be_explicit")
        if self.include_draft and self.corpus != "draft":
            raise ValueError("draft_result_must_set_corpus")
        for item in self.evidence:
            if item.novel_id != self.novel_id:
                raise ValueError("evidence_novel_mismatch")
            if item.scoring_profile_version != self.scoring_profile_version:
                raise ValueError("scoring_profile_mismatch")
        return self


def result_for_query(
    query: RetrievalQuery,
    evidence: list[RetrievalEvidence],
    *,
    embedding_profile_id: str | None = None,
    index_version: str | None = None,
    collection_name: str | None = None,
) -> RetrievalResult:
    """Assemble a typed result. Ranking and search stay outside this contract."""

    return RetrievalResult(
        novel_id=query.novel_id,
        query_profile_version=query.query_profile_version,
        filter_profile_version=query.filter_profile_version,
        scoring_profile_version=query.scoring_profile_version,
        embedding_profile_id=embedding_profile_id,
        index_version=index_version,
        collection_name=collection_name,
        corpus=query.corpus,
        include_draft=query.include_draft,
        evidence=evidence,
    )
