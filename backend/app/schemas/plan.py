from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class NewCharacterPolicy(StrEnum):
    FORBID = "forbid"
    ALLOW = "allow"
    ALLOW_IF_NECESSARY = "allow_if_necessary"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    GENERATED = "generated"
    EDITED = "edited"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"


class ScenePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str = Field(min_length=1)
    order: int = Field(ge=1)
    goal: str = Field(min_length=1)
    pov: str = ""
    participants: list[str] = Field(default_factory=list)
    location: str = ""
    beats: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    expected_transition: str = ""


class ChapterPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_goal: str = Field(min_length=1)
    target_length: int = Field(default=2000, ge=1)
    pace: str = ""
    emotion: str = ""
    new_character_policy: NewCharacterPolicy = NewCharacterPolicy.FORBID
    scenes: list[ScenePlan] = Field(min_length=1)
    characters: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    character_changes: list[str] = Field(default_factory=list)
    foreshadowing_actions: list[str] = Field(default_factory=list)
    forbidden_items: list[str] = Field(default_factory=list)
    ending_hook: str = ""


def chapter_plan_json_schema() -> dict:
    schema = ChapterPlan.model_json_schema()
    return {"type": "json_schema", "json_schema": {"name": "chapter_plan", "schema": schema}}
