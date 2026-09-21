$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host ">> backend pytest"
Push-Location backend
uv run pytest
Pop-Location

Write-Host ">> frontend test and build"
Push-Location frontend
pnpm test
pnpm build
Pop-Location
