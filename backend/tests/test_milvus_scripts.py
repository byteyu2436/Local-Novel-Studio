from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


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
