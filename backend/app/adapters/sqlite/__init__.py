from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.sqlite.base import Base
from app.adapters.sqlite.engine import create_sqlite_engine
from app.adapters.sqlite.import_sources import (
    create_paste_source,
    create_txt_source,
    get_import_source,
    set_parse_status,
    upsert_normalized_text,
)
from app.adapters.sqlite.migrate import upgrade_head
from app.adapters.sqlite.models import AppSetting, ImportSource, ImportSourceNormalizedText
from app.adapters.sqlite.session import create_session_factory, session_scope
from app.settings import Settings, get_settings
from app.storage.paths import ensure_data_layout


def bootstrap_local_runtime(
    settings: Settings | None = None,
) -> tuple[Settings, Engine, sessionmaker[Session]]:
    """Create data directories, open SQLite, and upgrade schema in place."""

    resolved = settings or get_settings()
    ensure_data_layout(resolved)
    upgrade_head(resolved)
    engine = create_sqlite_engine(resolved)
    return resolved, engine, create_session_factory(engine)


__all__ = [
    "AppSetting",
    "Base",
    "ImportSource",
    "ImportSourceNormalizedText",
    "bootstrap_local_runtime",
    "create_paste_source",
    "create_session_factory",
    "create_sqlite_engine",
    "create_txt_source",
    "get_import_source",
    "session_scope",
    "set_parse_status",
    "upgrade_head",
    "upsert_normalized_text",
]
