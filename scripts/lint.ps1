$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host ">> backend ruff check"
Push-Location backend
uv run ruff check .
Pop-Location

Write-Host ">> frontend lint"
Push-Location frontend
pnpm lint
Pop-Location
