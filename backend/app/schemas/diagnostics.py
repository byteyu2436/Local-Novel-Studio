from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CheckStatus = Literal["ok", "warning", "error"]


class DiagnosticCheck(BaseModel):
    id: str
    label: str
    status: CheckStatus
    summary: str
    hint: str | None = None
    code: str | None = Field(
        default=None,
        description="Stable reason code, e.g. gpu_absent vs gpu_probe_failed.",
    )


class DiagnosticsResponse(BaseModel):
    generated_at: datetime
    overall_status: CheckStatus
    checks: list[DiagnosticCheck]
    copy_summary: str = Field(description="Clipboard-safe summary. Never includes novel body text.")
