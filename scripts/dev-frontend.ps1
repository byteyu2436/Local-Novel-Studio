$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Push-Location frontend
if (-not (Test-Path "node_modules")) {
    pnpm install
}
pnpm dev
Pop-Location
