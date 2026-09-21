from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.analysis import (
    CHAPTER_ANALYSIS_SCHEMA_VERSION,
    AnalysisError,
    require_supported_schema_version,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChapterSummary(StrictModel):
    synopsis: str = Field(min_length=1)
    core_events: str = ""
    mood: str = ""


class CharacterMention(StrictModel):
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    identity: str = ""
    personality: str = ""
    goal: str = ""
    secret: str = ""
    current_state: str = ""
    evidence: str = ""


class LocationMention(StrictModel):
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    description: str = ""


class EventRecord(StrictModel):
    summary: str = Field(min_length=1)
    participants: list[str] = Field(default_factory=list)
    location: str | None = None
    time_label: str | None = None
    importance: Literal["low", "medium", "high"] = "medium"
    cause: str = ""
    effect: str = ""


class RelationshipRecord(StrictModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    relation_type: str = Field(min_length=1)
    trust_or_conflict: str = ""
    current_state: str = ""


class TimelineEntry(StrictModel):
    order_key: int = Field(ge=0)
    summary: str = Field(min_length=1)
    explicit_time: str | None = None
    relative_time: str | None = None
    uncertainty: Literal["certain", "approximate", "unknown"] = "unknown"


class ForeshadowingItem(StrictModel):
    clue: str = Field(min_length=1)
    status: Literal["planted", "reinforced", "resolved", "abandoned"] = "planted"
    evidence: str = ""


class OpenQuestion(StrictModel):
    question: str = Field(min_length=1)
    urgency: Literal["low", "normal", "high"] = "normal"


class WorldFactItem(StrictModel):
    fact: str = Field(min_length=1)
    category: Literal[
        "location",
        "organization",
        "institution",
        "rule",
        "item",
        "ability",
        "other",
    ] = "other"
    inferred: bool = False
    evidence: str = ""


class StyleSignals(StrictModel):
    pov: str | None = None
    sentence_length: str | None = None
    dialogue_ratio: str | None = None
    description_bias: str | None = None
    pacing: str | None = None
    chapter_length: str | None = None
    transition_style: str | None = None


class ChapterAnalysisPayload(StrictModel):
    summary: ChapterSummary
    characters: list[CharacterMention]
    locations: list[LocationMention]
    events: list[EventRecord]
    relationships: list[RelationshipRecord]
    timeline: list[TimelineEntry]
    foreshadowing: list[ForeshadowingItem]
    open_questions: list[OpenQuestion]
    world_facts: list[WorldFactItem]
    style_signals: StyleSignals


class AnalysisResultDTO(BaseModel):
    id: str
    chapter_id: str
    source_version_id: str
    source_version_kind: Literal["ORIGINAL", "ACCEPTED"]
    schema_version: str
    analyzer_version: str
    model_profile_id: str
    model_ref: str | None
    payload: ChapterAnalysisPayload
    created_at: datetime


def parse_chapter_analysis_payload(data: object) -> ChapterAnalysisPayload:
    try:
        return ChapterAnalysisPayload.model_validate(data)
    except ValidationError as exc:
        raise AnalysisError(
            "analysis_schema_invalid",
            "Chapter analysis JSON failed schema validation.",
        ) from exc


def parse_stored_analysis_payload(
    payload: object, *, schema_version: str
) -> ChapterAnalysisPayload:
    require_supported_schema_version(schema_version)
    return parse_chapter_analysis_payload(payload)


CURRENT_SCHEMA_VERSION = CHAPTER_ANALYSIS_SCHEMA_VERSION
