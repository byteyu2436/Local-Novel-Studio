from pathlib import Path

import pytest
from app.adapters.sqlite import bootstrap_local_runtime, upgrade_head
from app.settings import SettingsError, get_settings
from sqlalchemy import inspect, text


def test_bootstrap_creates_directories_and_sqlite(isolated_data_dir: Path) -> None:
    settings, engine, _session_factory = bootstrap_local_runtime()

    assert isolated_data_dir.is_dir()
    assert (isolated_data_dir / "logs").is_dir()
    assert (isolated_data_dir / "novels").is_dir()
    assert (isolated_data_dir / "cache").is_dir()
    assert (isolated_data_dir / "imports").is_dir()
    assert settings.sqlite_path is not None
    assert settings.sqlite_path.is_file()

    inspector = inspect(engine)
    assert "app_settings" in inspector.get_table_names()
    assert "memory_facts" not in inspector.get_table_names()
    engine.dispose()


def test_alembic_upgrade_is_idempotent(isolated_data_dir: Path) -> None:
    settings, engine, _session_factory = bootstrap_local_runtime()
    upgrade_head(settings)
    upgrade_head(settings)

    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0004_novels_chapters"
    engine.dispose()


def test_sqlite_path_can_be_overridden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "custom" / "studio.db"))
    get_settings.cache_clear()

    settings, engine, _session_factory = bootstrap_local_runtime()
    assert settings.sqlite_path == (tmp_path / "custom" / "studio.db").resolve()
    assert (tmp_path / "custom" / "studio.db").is_file()
    engine.dispose()


def test_data_dir_file_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    not_a_dir = tmp_path / "not-a-dir"
    not_a_dir.write_text("nope", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(not_a_dir))
    get_settings.cache_clear()

    with pytest.raises(SettingsError, match="DATA_DIR"):
        get_settings()


def test_invalid_execution_profile_is_rejected(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LNS_EXECUTION_PROFILE", "metal")
    get_settings.cache_clear()

    with pytest.raises(SettingsError, match="LNS_EXECUTION_PROFILE"):
        get_settings()


def test_app_startup_uses_isolated_sqlite(client, isolated_data_dir: Path) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert (isolated_data_dir / "app.db").is_file()
