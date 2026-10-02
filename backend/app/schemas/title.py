from pydantic import BaseModel, Field


class TitleCandidate(BaseModel):
    text: str = Field(min_length=1, max_length=32)
    confidence: float = Field(ge=0, le=1)
    reason: str = ""
    keywords: list[str] = Field(default_factory=list)


class TitleCandidateList(BaseModel):
    candidates: list[TitleCandidate] = Field(min_length=1, max_length=3)
