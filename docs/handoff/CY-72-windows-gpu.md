# CY-72 Windows GPU Handoff

This Issue is `SPLIT`. CPU_DEV completed Adapter / Mock / Contract tests only.

## Do not treat as passed

- Real non-stream chat
- Real stream chat
- Real cancel
- Installed `qwen3.5:9b` digest verification

Mock/CPU/MPS results are not GPU evidence.

## Preflight (Windows PowerShell, after switching to the RTX 5070 Ti machine)

```powershell
git checkout <COMMIT_SHA>
cd backend
uv sync --group dev
ollama --version
ollama list
# Only on WINDOWS_GPU, if the model is not installed:
# ollama pull qwen3.5:9b
$env:LNS_EXECUTION_PROFILE = "windows-gpu"
uv run pytest tests/test_ollama_adapter.py -k real_ollama
```

Record Ollama version, model name/tag/digest, peak VRAM, logs under `data/logs/`, and the commit SHA in the Linear Issue before closing GPU validation.
