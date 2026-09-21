from pathlib import Path

from alembic import command
from alembic.config import Config

from app.settings import Settings

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def alembic_config(settings: Settings) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def upgrade_head(settings: Settings) -> None:
    """Apply Alembic migrations. Never drops or recreates the database file."""

    command.upgrade(alembic_config(settings), "head")
