$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$compose = Join-Path $PWD "infra\milvus\docker-compose.yml"
$project = "local-novel-studio-milvus"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker is not available; nothing to stop for this project's Milvus stack."
    exit 0
}

docker compose -f $compose -p $project down
Write-Host "Stopped only compose project '$project'. Other containers were not touched."
