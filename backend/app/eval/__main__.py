"""CPU_DEV: python -m app.eval.analysis_golden

Live Ollama is not GPU evidence:
$env:LNS_OLLAMA_SMOKE='1'; python -m app.eval.analysis_golden --live
"""

from app.eval.analysis_golden import run_cli

if __name__ == "__main__":
    raise SystemExit(run_cli())
