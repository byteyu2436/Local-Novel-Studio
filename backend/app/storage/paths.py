from pathlib import Path

from app.settings import Settings


def required_data_directories(settings: Settings) -> tuple[Path, ...]:
    return (
        settings.data_dir,
        settings.logs_dir,
        settings.novels_dir,
        settings.cache_dir,
        settings.sqlite_path.parent if settings.sqlite_path is not None else settings.data_dir,
    )


def ensure_data_layout(settings: Settings) -> None:
    """Create the local data directories without touching existing SQLite files."""

    for directory in required_data_directories(settings):
        directory.mkdir(parents=True, exist_ok=True)
