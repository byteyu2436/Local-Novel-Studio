from app.adapters.llm.types import RuntimeHealth
from app.adapters.milvus.types import MilvusHealth
from app.services.diagnostics import collect_diagnostics


def test_diagnostics_api_returns_checks(client) -> None:
    response = client.get("/api/system/diagnostics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] in {"ok", "warning", "error"}
    ids = {item["id"] for item in payload["checks"]}
    assert {"python", "node", "data_dir", "sqlite", "ollama", "milvus", "gpu"} <= ids
    assert "copy_summary" in payload
    assert "THE SECRET NOVEL BODY" not in payload["copy_summary"]


def test_diagnostics_summary_does_not_read_novel_files(client, isolated_data_dir) -> None:
    secret = isolated_data_dir / "novels" / "secret.txt"
    secret.write_text("THE SECRET NOVEL BODY " * 20, encoding="utf-8")
    response = client.get("/api/system/diagnostics")
    assert "THE SECRET NOVEL BODY" not in response.json()["copy_summary"]
    assert "THE SECRET NOVEL BODY" not in response.text


async def _sample_collect(engine, settings):
    return await collect_diagnostics(
        settings=settings,
        engine=engine,
        ollama_health=RuntimeHealth(
            runtime="ollama",
            reachable=False,
            status="unavailable",
            default_model=settings.writer_model,
            message="Ollama is not reachable.",
        ),
        milvus_health=MilvusHealth(
            reachable=False,
            status="unavailable",
            host=settings.milvus_host,
            port=settings.milvus_port,
            health_url="http://127.0.0.1:9091/healthz",
            message="Milvus is not reachable.",
            hint="Start scripts/milvus-up.ps1.",
        ),
    )


def test_collect_diagnostics_marks_missing_providers(client) -> None:
    import asyncio

    settings = client.app.state.settings
    engine = client.app.state.engine
    result = asyncio.run(_sample_collect(engine, settings))
    ollama = next(check for check in result.checks if check.id == "ollama")
    milvus = next(check for check in result.checks if check.id == "milvus")
    assert ollama.status == "error"
    assert milvus.status == "warning"
    assert result.overall_status in {"error", "warning"}
