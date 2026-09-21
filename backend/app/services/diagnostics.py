from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.adapters.hardware import GpuSnapshot, HardwareProbe, RamSnapshot
from app.adapters.llm.types import RuntimeHealth
from app.adapters.milvus.types import MilvusHealth
from app.schemas.diagnostics import CheckStatus, DiagnosticCheck, DiagnosticsResponse
from app.settings import Settings


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def _worst(*statuses: CheckStatus) -> CheckStatus:
    if "error" in statuses:
        return "error"
    if "warning" in statuses:
        return "warning"
    return "ok"


def _python_check() -> DiagnosticCheck:
    version = platform.python_version()
    status: CheckStatus = "ok" if sys.version_info >= (3, 12) else "error"
    return DiagnosticCheck(
        id="python",
        label="Python",
        status=status,
        summary=f"Python {version} ({platform.system()})",
        hint=None if status == "ok" else "Install Python 3.12+.",
    )


def _node_check() -> DiagnosticCheck:
    node = shutil.which("node")
    if node is None:
        return DiagnosticCheck(
            id="node",
            label="Node.js",
            status="warning",
            summary="node is not on PATH.",
            hint="Install Node.js LTS to run the Vite frontend.",
        )
    result = subprocess.run(
        ["node", "--version"], capture_output=True, text=True, timeout=5, check=False
    )
    version = (result.stdout or result.stderr).strip()
    return DiagnosticCheck(
        id="node",
        label="Node.js",
        status="ok" if result.returncode == 0 else "warning",
        summary=version or "node found",
    )


def _data_dir_check(settings: Settings) -> DiagnosticCheck:
    missing = [
        name
        for name, path in {
            "data": settings.data_dir,
            "logs": settings.logs_dir,
            "novels": settings.novels_dir,
        }.items()
        if not path.is_dir()
    ]
    if missing:
        return DiagnosticCheck(
            id="data_dir",
            label="Data directories",
            status="error",
            summary=f"Missing directories: {', '.join(missing)}",
            hint="Restart the backend so it can create DATA_DIR, logs, and novels.",
        )
    return DiagnosticCheck(
        id="data_dir",
        label="Data directories",
        status="ok",
        summary=f"Using {_display_path(settings.data_dir)} (logs/novels/cache present)",
    )


def _sqlite_check(settings: Settings, engine: Engine) -> DiagnosticCheck:
    sqlite_path = settings.sqlite_path
    if sqlite_path is None or not sqlite_path.is_file():
        return DiagnosticCheck(
            id="sqlite",
            label="SQLite",
            status="error",
            summary="SQLite file is missing.",
            hint="Restart the backend to run Alembic migrations.",
        )
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:
        return DiagnosticCheck(
            id="sqlite",
            label="SQLite",
            status="error",
            summary="SQLite is present but schema version could not be read.",
            hint=str(exc.__class__.__name__),
        )
    return DiagnosticCheck(
        id="sqlite",
        label="SQLite",
        status="ok",
        summary=f"{_display_path(sqlite_path)} @ {version}",
    )


def _ollama_check(health: RuntimeHealth) -> DiagnosticCheck:
    if not health.reachable:
        return DiagnosticCheck(
            id="ollama",
            label="Ollama",
            status="error",
            summary=health.message or "Ollama is not reachable.",
            hint="Start Ollama locally. Do not pull large models from CPU_DEV.",
        )
    if not health.default_model_installed:
        return DiagnosticCheck(
            id="ollama",
            label="Ollama",
            status="warning",
            summary=health.message or f"{health.default_model} is not installed.",
            hint="Pull the configured writer model only on the Windows GPU machine.",
        )
    return DiagnosticCheck(
        id="ollama",
        label="Ollama",
        status="ok",
        summary=f"Ollama {health.version or 'ok'}; {health.default_model} installed",
    )


def _milvus_check(health: MilvusHealth) -> DiagnosticCheck:
    status: CheckStatus = "ok" if health.reachable else "warning"
    return DiagnosticCheck(
        id="milvus",
        label="Milvus",
        status=status,
        summary=health.message,
        hint=health.hint or None,
    )


def _ram_check(snapshot: RamSnapshot) -> DiagnosticCheck:
    if not snapshot.ok:
        return DiagnosticCheck(
            id="ram",
            label="RAM",
            status="warning",
            summary=snapshot.message or "RAM probe failed.",
            hint="Diagnostics continues without RAM details.",
            code="ram_unavailable",
        )
    return DiagnosticCheck(
        id="ram",
        label="RAM",
        status="ok",
        summary=snapshot.message,
        code="ram_ok",
    )


def _gpu_check(snapshot: GpuSnapshot) -> DiagnosticCheck:
    if snapshot.presence == "absent":
        return DiagnosticCheck(
            id="gpu",
            label="GPU",
            status="warning",
            summary=snapshot.message,
            hint="Expected on CPU-only hosts. This is not a probe failure.",
            code="gpu_absent",
        )
    if snapshot.presence == "probe_failed":
        return DiagnosticCheck(
            id="gpu",
            label="GPU",
            status="warning",
            summary=snapshot.message,
            hint="GPU detection failed; other diagnostics are unchanged.",
            code="gpu_probe_failed",
        )
    return DiagnosticCheck(
        id="gpu",
        label="GPU",
        status="ok",
        summary=snapshot.message,
        hint="Informational only. Not a VRAM budget or scheduler.",
        code="gpu_ok",
    )


def build_copy_summary(checks: list[DiagnosticCheck], overall: CheckStatus) -> str:
    lines = [
        "Local Novel Studio diagnostics",
        f"overall={overall}",
        f"pid={os.getpid()}",
    ]
    for check in checks:
        extra = f" [{check.code}]" if check.code else ""
        lines.append(f"{check.id}: {check.status}{extra} — {check.summary}")
        if check.hint:
            lines.append(f"  hint: {check.hint}")
    return "\n".join(lines)


async def collect_diagnostics(
    *,
    settings: Settings,
    engine: Engine,
    ollama_health: RuntimeHealth,
    milvus_health: MilvusHealth,
    hardware: HardwareProbe | None = None,
) -> DiagnosticsResponse:
    probe = hardware or HardwareProbe()
    checks = [
        _python_check(),
        _node_check(),
        _data_dir_check(settings),
        _sqlite_check(settings, engine),
        _ollama_check(ollama_health),
        _milvus_check(milvus_health),
        _ram_check(probe.ram()),
        _gpu_check(probe.gpu()),
    ]
    overall = _worst(*(check.status for check in checks))
    return DiagnosticsResponse(
        generated_at=datetime.now(UTC),
        overall_status=overall,
        checks=checks,
        copy_summary=build_copy_summary(checks, overall),
    )
