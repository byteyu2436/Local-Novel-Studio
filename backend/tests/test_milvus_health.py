import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from app.adapters.milvus import MilvusHealthAdapter
from app.settings import get_settings

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "infra" / "milvus" / "docker-compose.yml"


def test_compose_file_pins_versions_and_avoids_latest() -> None:
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    assert "latest" not in text
    assert "milvusdb/milvus:v2.5.4" in text
    assert "quay.io/coreos/etcd:v3.5.16" in text
    assert "minio/minio:RELEASE.2024-12-18T13-15-44Z" in text
    assert "19530:19530" in text
    assert "9091:9091" in text


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not installed")
def test_docker_compose_config_validates() -> None:
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "config"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_milvus_health_is_unavailable_without_container() -> None:
    settings = get_settings()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=1)
    adapter = MilvusHealthAdapter(settings, client=client)
    import asyncio

    health = asyncio.run(adapter.health())
    assert health.reachable is False
    assert health.status == "unavailable"
    assert "rebuild" in health.hint.lower()
    asyncio.run(client.aclose())


def test_milvus_health_ok_from_healthz() -> None:
    settings = get_settings()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/healthz")
        return httpx.Response(200, text="OK")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=1)
    adapter = MilvusHealthAdapter(settings, client=client)
    import asyncio

    health = asyncio.run(adapter.health())
    assert health.reachable is True
    assert health.status == "ok"
    asyncio.run(client.aclose())
