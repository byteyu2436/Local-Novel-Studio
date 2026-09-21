from collections.abc import Sequence
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionProfile(StrEnum):
    CPU_DEV = "cpu-dev"
    WINDOWS_GPU = "windows-gpu"


class SettingsError(Exception):
    """Raised when local configuration cannot be loaded or is unsafe to use."""


class Settings(BaseSettings):
    """Local-only process settings. Cloud API keys are intentionally unsupported."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8000
    lns_execution_profile: ExecutionProfile = ExecutionProfile.CPU_DEV
    data_dir: Path = Path("./data")
    sqlite_path: Path | None = None
    cors_origins: Sequence[str] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )
    sqlite_echo: bool = Field(default=False)

    @field_validator("app_host")
    @classmethod
    def app_host_must_be_local(cls, value: str) -> str:
        host = value.strip()
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError(
                f"APP_HOST must be 127.0.0.1 or localhost for this local-only tool, got {value!r}."
            )
        return host

    @model_validator(mode="after")
    def resolve_and_validate_paths(self) -> "Settings":
        data_dir = self.data_dir.expanduser()
        if not data_dir.is_absolute():
            data_dir = (Path.cwd() / data_dir).resolve()
        else:
            data_dir = data_dir.resolve()

        if data_dir.exists() and not data_dir.is_dir():
            raise ValueError(f"DATA_DIR must be a directory, got a file: {data_dir}")

        sqlite_path = self.sqlite_path
        if sqlite_path is None:
            sqlite_path = data_dir / "app.db"
        else:
            sqlite_path = sqlite_path.expanduser()
            if not sqlite_path.is_absolute():
                sqlite_path = (Path.cwd() / sqlite_path).resolve()
            else:
                sqlite_path = sqlite_path.resolve()

        if sqlite_path.exists() and sqlite_path.is_dir():
            raise ValueError(f"SQLITE_PATH must be a database file, got a directory: {sqlite_path}")

        self.data_dir = data_dir
        self.sqlite_path = sqlite_path
        return self

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def novels_dir(self) -> Path:
        return self.data_dir / "novels"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def database_url(self) -> str:
        if self.sqlite_path is None:
            raise SettingsError("SQLITE_PATH was not resolved.")
        return f"sqlite+pysqlite:///{self.sqlite_path.as_posix()}"


def _format_settings_error(exc: ValidationError) -> str:
    lines = ["Invalid Local Novel Studio configuration:"]
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ())) or "settings"
        env_name = location.upper()
        lines.append(f"- {env_name}: {error.get('msg', 'invalid value')}")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise SettingsError(_format_settings_error(exc)) from exc
