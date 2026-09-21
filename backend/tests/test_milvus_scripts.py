import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
ROOT = SCRIPTS.parent


def _read(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def test_milvus_scripts_target_this_compose_project_only() -> None:
    for name in (
        "milvus-up.ps1",
        "milvus-down.ps1",
        "milvus-health.ps1",
        "milvus-up.sh",
        "milvus-down.sh",
        "milvus-health.sh",
    ):
        text = _read(name)
        assert "infra" in text and "milvus" in text and "docker-compose.yml" in text
        assert "local-novel-studio-milvus" in text
        assert "docker stop" not in text
        assert "docker kill" not in text


def test_milvus_health_scripts_distinguish_failure_modes() -> None:
    for name in ("milvus-health.ps1", "milvus-health.sh"):
        text = _read(name)
        assert "Docker is not available" in text
        assert "Docker Engine is not running" in text
        assert "exit 7" in text
        assert "not started" in text
        assert "9091" in text
        assert "not ready" in text
        assert "not Canon" in text


def test_milvus_up_scripts_check_docker_and_port_conflict() -> None:
    for name in ("milvus-up.ps1", "milvus-up.sh"):
        text = _read(name)
        assert "Docker is not available" in text
        assert "19530" in text
        assert "already in use" in text
        assert "docker compose up failed" in text


@pytest.mark.skipif(os.name != "nt", reason="PowerShell health script")
def test_milvus_health_ps1_shim_reports_engine_not_running(tmp_path: Path) -> None:
    shim = tmp_path / "docker.cmd"
    shim.write_text(
        '@echo off\r\nif /I "%1"=="info" exit /b 1\r\nexit /b 0\r\n',
        encoding="ascii",
    )
    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env["PATH"]
    result = subprocess.run(
        ["powershell", "-NoProfile", "-File", str(SCRIPTS / "milvus-health.ps1")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 7
    assert "Docker Engine is not running" in (result.stdout + result.stderr)


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not installed")
def test_milvus_health_ps1_live_engine_is_not_exit_7() -> None:
    probe = subprocess.run(
        ["docker", "info"],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip("Docker Engine is not running on this host")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-File", str(SCRIPTS / "milvus-health.ps1")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode in {0, 4, 5, 6}
    assert result.returncode != 7
