# CY-127 Windows GPU hardware probe

Mock/CPU nvidia-smi fixtures are not GPU evidence.

## Real probe (2026-09-21)

```powershell
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free --format=csv,noheader,nounits
```

Output:

```text
NVIDIA GeForce RTX 5070 Ti, 16303, 1661, 14335
```

- Host: Windows, NVIDIA GeForce RTX 5070 Ti
- Total VRAM: 16303 MiB
- Used / free at adapter probe: 1661 / 14335 MiB
- RAM: 10.1 / 31.8 GiB available (`GlobalMemoryStatusEx`)
- `LNS_EXECUTION_PROFILE=cpu-dev`: hardware mock tests passed; real nvidia-smi test skipped
- `LNS_EXECUTION_PROFILE=windows-gpu`: `tests/test_hardware_probe.py` 9 passed, including `test_real_nvidia_smi_on_windows_gpu`

Codes exposed to the frontend: `gpu_ok` / `gpu_absent` / `gpu_probe_failed`.
