from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SECTION_TYPES = (
    "writing_rules",
    "locked_facts",
    "character_state",
    "relationship",
    "global_summary",
    "open_foreshadowing",
    "retrieved_evidence",
    "recent_text",
    "plan",
    "current_goal",
)
SOURCE_TYPES = ("canon", "memory", "retrieval", "draft", "user", "system")
SectionType = Literal[
    "writing_rules",
    "locked_facts",
    "character_state",
    "relationship",
    "global_summary",
    "open_foreshadowing",
    "retrieved_evidence",
    "recent_text",
    "plan",
    "current_goal",
]
SourceType = Literal["canon", "memory", "retrieval", "draft", "user", "system"]


class ContextSection(BaseModel):
    """One explainable slice of model context. Draft never uses a Canon source type."""

    model_config = ConfigDict(extra="forbid")

    section_type: SectionType
    source_type: SourceType
    source_id: str = Field(min_length=1)
    priority: int = 0
    token_estimate: int = Field(ge=0)
    locked: bool = False
    included: bool = True
    trimmed_reason: str = ""
    text: str = ""
    checksum: str = ""
    version: str = ""
    score: float | None = None
    recency: int = 0
    compressed_text: str = ""
    before_tokens: int | None = None
    after_tokens: int | None = None


class ContextManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    builder_version: str
    profile_id: str
    estimator_version: str
    max_context_tokens: int
    input_budget: int
    output_reserve: int
    safety_margin: int
    total_tokens: int
    degraded: list[str] = Field(default_factory=list)
    sections: list[ContextSection]
    omitted: list[ContextSection] = Field(default_factory=list)
