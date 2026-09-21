# CY-72 Windows GPU Handoff

## Status

WINDOWS_GPU validation passed on 2026-09-21 against the RTX 5070 Ti.

CPU_DEV previously completed Adapter / Mock / Contract tests only. Mock/CPU/MPS results were not used as GPU evidence.

## Evidence

- Host: Windows, NVIDIA GeForce RTX 5070 Ti, driver 616.64, 16303 MiB
- Ollama: 0.33.2 at `http://127.0.0.1:11434`
- Model: `qwen3.5:9b` (9.7B parameters, Q4_K_M, GGUF)
- Digest: `sha256:6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- Size: 6,594,474,711 bytes (6.6 GB)
- Peak VRAM observed after smoke: 8788 MiB / 16303 MiB (`llama-server.exe` resident)
- Real smoke: health + non-stream chat + stream chat + mid-stream cancel
- `LNS_EXECUTION_PROFILE=windows-gpu`: `tests/test_ollama_adapter.py` + `tests/test_diagnostics.py` → 9 passed in 16.80s
- `LNS_EXECUTION_PROFILE=cpu-dev`: full backend suite → 21 passed, 1 skipped (real smoke skipped)
- Local log (gitignored): `data/logs/CY-72-windows-gpu-smoke.txt`

## Commands used

```powershell
ollama --version
ollama pull qwen3.5:9b
$env:LNS_EXECUTION_PROFILE = "windows-gpu"
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_ollama_adapter.py tests/test_diagnostics.py -q
```
