$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host ">> backend pytest"
Push-Location backend
uv run pytest
Pop-Location

Write-Host ">> frontend build"
Push-Location frontend
pnpm build
Pop-Location
