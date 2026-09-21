import subprocess

import pytest
from app.adapters.hardware import HardwareProbe, parse_nvidia_smi, read_ram
from app.settings import get_settings


def _windows_gpu() -> bool:
    get_settings.cache_clear()
    return get_settings().lns_execution_profile.value == "windows-gpu"


def test_parse_nvidia_smi_ok() -> None:
    snapshot = parse_nvidia_smi("Mock GPU, 8192, 1024, 7168\n")
    assert snapshot.presence == "ok"
    assert snapshot.name == "Mock GPU"
    assert snapshot.memory_total_mib == 8192
    assert snapshot.memory_used_mib == 1024
    assert snapshot.memory_free_mib == 7168


def test_gpu_absent_when_nvidia_smi_missing() -> None:
    probe = HardwareProbe(which=lambda _name: None)
    snapshot = probe.gpu()
    assert snapshot.presence == "absent"
    assert "not found" in snapshot.message


def test_gpu_probe_failed_on_nonzero_exit() -> None:
    def run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=1, stdout="", stderr="err"
        )

    probe = HardwareProbe(which=lambda _name: "nvidia-smi", run=run)
    snapshot = probe.gpu()
    assert snapshot.presence == "probe_failed"
    assert "non-zero" in snapshot.message


def test_gpu_probe_failed_on_timeout() -> None:
    def run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5)

    probe = HardwareProbe(which=lambda _name: "nvidia-smi", run=run)
    snapshot = probe.gpu()
    assert snapshot.presence == "probe_failed"
    assert "timed out" in snapshot.message


def test_gpu_probe_failed_on_oserror() -> None:
    def run(*_args, **_kwargs):
        raise OSError("denied")

    probe = HardwareProbe(which=lambda _name: "nvidia-smi", run=run)
    snapshot = probe.gpu()
    assert snapshot.presence == "probe_failed"


def test_gpu_probe_failed_on_garbage_output() -> None:
    def run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout="not-a-csv", stderr=""
        )

    probe = HardwareProbe(which=lambda _name: "nvidia-smi", run=run)
    snapshot = probe.gpu()
    assert snapshot.presence == "probe_failed"


def test_ram_smoke_returns_positive_totals() -> None:
    snapshot = read_ram()
    assert snapshot.ok is True
    assert snapshot.total_bytes is not None and snapshot.total_bytes > 0
    assert snapshot.available_bytes is not None and snapshot.available_bytes > 0


def test_ram_probe_swallows_reader_errors() -> None:
    def boom():
        raise RuntimeError("boom")

    probe = HardwareProbe(ram_reader=boom)
    snapshot = probe.ram()
    assert snapshot.ok is False
    assert "RuntimeError" in snapshot.message


@pytest.mark.skipif(
    not _windows_gpu(),
    reason="Real RTX 5070 Ti nvidia-smi evidence is deferred to WINDOWS_GPU.",
)
def test_real_nvidia_smi_on_windows_gpu() -> None:
    snapshot = HardwareProbe().gpu()
    assert snapshot.presence == "ok"
    assert snapshot.name is not None
    assert "5070 Ti" in snapshot.name
    assert snapshot.memory_total_mib is not None
    assert 15000 <= snapshot.memory_total_mib <= 18000
