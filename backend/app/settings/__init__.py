from collections.abc import Sequence

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Minimal process settings for the v0.1 skeleton.

    Data directory, SQLite path, and Alembic live in a later Issue.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8000
    lns_execution_profile: str = "cpu-dev"
    cors_origins: Sequence[str] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )


def get_settings() -> Settings:
    return Settings()
