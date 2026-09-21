from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from app.settings import Settings


def create_sqlite_engine(settings: Settings) -> Engine:
    engine = create_engine(
        settings.database_url,
        future=True,
        echo=settings.sqlite_echo,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        connection.commit()

    return engine
