from app.adapters.hardware import HardwareProbe
from app.adapters.llm.types import RuntimeHealth
from app.adapters.milvus.types import MilvusHealth
from app.services.diagnostics import collect_diagnostics, redact_local_paths


def test_redact_local_paths_hides_home_directories() -> None:
    text = redact_local_paths(r"db=D:\Users\admin\AppData\app.db extra=/home/alice/.cache/lns")
    assert "admin" not in text
    assert "alice" not in text
    assert "<redacted-path>" in text
    health = redact_local_paths("health http://127.0.0.1:9091/healthz")
    assert "127.0.0.1:9091" in health


def test_diagnostics_api_returns_checks(client) -> None:
    response = client.get("/api/system/diagnostics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] in {"ok", "warning", "error"}
    ids = {item["id"] for item in payload["checks"]}
    assert {"python", "node", "data_dir", "sqlite", "ollama", "milvus", "ram", "gpu"} <= ids
    gpu = next(item for item in payload["checks"] if item["id"] == "gpu")
    ram = next(item for item in payload["checks"] if item["id"] == "ram")
    assert gpu["code"] in {"gpu_ok", "gpu_absent", "gpu_probe_failed"}
    assert ram["code"] in {"ram_ok", "ram_unavailable"}
    assert "copy_summary" in payload
    assert payload["copy_summary"].startswith("Local Novel Studio v0.1.0")
    assert "THE SECRET NOVEL BODY" not in payload["copy_summary"]
    assert "You are a novelist" not in payload["copy_summary"]


def test_diagnostics_summary_does_not_read_novel_files(client, isolated_data_dir) -> None:
    secret = isolated_data_dir / "novels" / "secret.txt"
    secret.write_text("THE SECRET NOVEL BODY " * 20, encoding="utf-8")
    (isolated_data_dir / "novels" / "prompt.txt").write_text(
        "You are a novelist. Write chapter 1: THE SECRET PROMPT", encoding="utf-8"
    )
    response = client.get("/api/system/diagnostics")
    summary = response.json()["copy_summary"]
    assert "THE SECRET NOVEL BODY" not in summary
    assert "THE SECRET PROMPT" not in summary
    assert "You are a novelist" not in summary
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


def test_collect_diagnostics_distinguishes_gpu_absence_from_probe_failure(
    client,
) -> None:
    import asyncio
    import subprocess

    settings = client.app.state.settings
    engine = client.app.state.engine
    absent = asyncio.run(
        collect_diagnostics(
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
            hardware=HardwareProbe(which=lambda _name: None),
        )
    )
    gpu_absent = next(check for check in absent.checks if check.id == "gpu")
    assert gpu_absent.code == "gpu_absent"

    def run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5)

    failed = asyncio.run(
        collect_diagnostics(
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
            hardware=HardwareProbe(which=lambda _name: "nvidia-smi", run=run),
        )
    )
    gpu_failed = next(check for check in failed.checks if check.id == "gpu")
    assert gpu_failed.code == "gpu_probe_failed"
    assert gpu_absent.code != gpu_failed.code
