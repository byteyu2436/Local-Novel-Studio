from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_session

router = APIRouter(tags=["system"])


class SqliteReadyResponse(BaseModel):
    status: str
    canon: str = "sqlite"


@router.get("/sqlite", response_model=SqliteReadyResponse)
def sqlite_ready(session: Annotated[Session, Depends(get_session)]) -> SqliteReadyResponse:
    session.execute(text("SELECT 1"))
    return SqliteReadyResponse(status="ok")
