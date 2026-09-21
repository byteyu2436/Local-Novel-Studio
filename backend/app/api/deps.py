from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from app.adapters.sqlite.session import session_scope


def get_session(request: Request) -> Generator[Session, None, None]:
    """Yield a request-scoped SQLite session from the app lifespan factory."""

    yield from session_scope(request.app.state.session_factory)
