$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host ">> backend ruff format"
Push-Location backend
uv run ruff format .
Pop-Location

Write-Host ">> frontend format"
Push-Location frontend
pnpm format
Pop-Location
