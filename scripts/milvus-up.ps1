$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$compose = Join-Path $PWD "infra\milvus\docker-compose.yml"
docker compose -f $compose up -d
Write-Host "Milvus Standalone is starting. Health endpoint: http://127.0.0.1:9091/healthz"
