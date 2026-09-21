import pytest
from app.adapters.sqlite import AppSetting, bootstrap_local_runtime, session_scope
from fastapi.testclient import TestClient


def test_sqlite_ready_uses_session_dependency(client: TestClient) -> None:
    response = client.get("/sqlite")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "canon": "sqlite"}


def test_session_scope_commits(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            session.add(AppSetting(key="theme", value="dark"))
        with factory() as session:
            stored = session.get(AppSetting, "theme")
            assert stored is not None
            assert stored.value == "dark"
    finally:
        engine.dispose()


def test_session_scope_rollbacks_on_error(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        with pytest.raises(RuntimeError, match="boom"):
            for session in session_scope(factory):
                session.add(AppSetting(key="theme", value="dark"))
                raise RuntimeError("boom")
        with factory() as session:
            assert session.get(AppSetting, "theme") is None
    finally:
        engine.dispose()
