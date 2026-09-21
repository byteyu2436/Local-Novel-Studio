from __future__ import annotations

import csv
import ctypes
import shutil
import subprocess
import sys
from collections.abc import Callable
from io import StringIO
from pathlib import Path

from app.adapters.hardware.types import GpuSnapshot, RamSnapshot

GPU_PROBE_TIMEOUT_SEC = 5
NVIDIA_SMI_QUERY = [
    "--query-gpu=name,memory.total,memory.used,memory.free",
    "--format=csv,noheader,nounits",
]

RunFn = Callable[..., subprocess.CompletedProcess[str]]
WhichFn = Callable[[str], str | None]


class HardwareProbe:
    """Optional RAM/GPU facts for Diagnostics. Failures never raise to the app."""

    def __init__(
        self,
        *,
        run: RunFn | None = None,
        which: WhichFn | None = None,
        ram_reader: Callable[[], RamSnapshot] | None = None,
        timeout: float = GPU_PROBE_TIMEOUT_SEC,
    ) -> None:
        self._run = run or subprocess.run
        self._which = which or shutil.which
        self._ram_reader = ram_reader or read_ram
        self._timeout = timeout

    def ram(self) -> RamSnapshot:
        try:
            return self._ram_reader()
        except Exception as exc:
            return RamSnapshot(ok=False, message=f"RAM probe failed: {exc.__class__.__name__}")

    def gpu(self) -> GpuSnapshot:
        nvidia_smi = self._which("nvidia-smi")
        if nvidia_smi is None:
            return GpuSnapshot(
                presence="absent",
                message="nvidia-smi was not found; treating this host as having no NVIDIA GPU.",
            )
        try:
            result = self._run(
                [nvidia_smi, *NVIDIA_SMI_QUERY],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return GpuSnapshot(
                presence="probe_failed",
                message=f"nvidia-smi timed out after {self._timeout:.0f}s.",
            )
        except OSError:
            return GpuSnapshot(
                presence="probe_failed",
                message="nvidia-smi could not be executed.",
            )
        if result.returncode != 0:
            return GpuSnapshot(
                presence="probe_failed",
                message="nvidia-smi returned a non-zero exit code.",
            )
        return parse_nvidia_smi(result.stdout or "")


def read_ram() -> RamSnapshot:
    if sys.platform == "win32":
        return _ram_windows()
    return _ram_posix()


def parse_nvidia_smi(stdout: str) -> GpuSnapshot:
    line = next((item.strip() for item in stdout.splitlines() if item.strip()), "")
    if not line:
        return GpuSnapshot(presence="probe_failed", message="nvidia-smi returned empty output.")
    try:
        row = next(csv.reader(StringIO(line)))
        name, total, used, free = (item.strip() for item in row[:4])
        return GpuSnapshot(
            presence="ok",
            name=name,
            memory_total_mib=int(total),
            memory_used_mib=int(used),
            memory_free_mib=int(free),
            message=f"{name}: {used} / {total} MiB used, {free} MiB free",
        )
    except (ValueError, StopIteration, IndexError):
        return GpuSnapshot(
            presence="probe_failed", message="nvidia-smi output could not be parsed."
        )


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _ram_windows() -> RamSnapshot:
    stat = _MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)) == 0:
        raise OSError("GlobalMemoryStatusEx failed")
    return RamSnapshot(
        ok=True,
        total_bytes=int(stat.ullTotalPhys),
        available_bytes=int(stat.ullAvailPhys),
        message=_ram_message(int(stat.ullTotalPhys), int(stat.ullAvailPhys)),
    )


def _ram_posix() -> RamSnapshot:
    values: dict[str, int] = {}
    for raw in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, _, rest = raw.partition(":")
        number = rest.strip().split()[0]
        if key in {"MemTotal", "MemAvailable"}:
            values[key] = int(number) * 1024
    total = values["MemTotal"]
    available = values["MemAvailable"]
    return RamSnapshot(
        ok=True,
        total_bytes=total,
        available_bytes=available,
        message=_ram_message(total, available),
    )


def _ram_message(total_bytes: int, available_bytes: int) -> str:
    total_gib = total_bytes / (1024**3)
    available_gib = available_bytes / (1024**3)
    return f"{available_gib:.1f} / {total_gib:.1f} GiB available"
