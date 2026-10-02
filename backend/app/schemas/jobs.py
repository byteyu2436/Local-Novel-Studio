from pydantic import BaseModel


class AnalysisJobProgressDTO(BaseModel):
    job_id: str
    novel_id: str | None
    state: str
    total: int
    completed: int
    failed_chapter_ids: list[str]
    current_chapter_id: str | None
    recommended_action: str


class AnalysisRecoveryItemDTO(BaseModel):
    job_id: str
    novel_id: str | None
    state: str
    recommended_action: str
    interrupted_chapter_ids: list[str]
    completed: int
    total: int


class AnalysisRecoveryReportDTO(BaseModel):
    jobs: list[AnalysisRecoveryItemDTO]


class JobErrorDTO(BaseModel):
    code: str
    message: str
