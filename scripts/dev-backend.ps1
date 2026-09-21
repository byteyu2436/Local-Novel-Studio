$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Push-Location backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
Pop-Location
