$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$compose = Join-Path $PWD "infra\milvus\docker-compose.yml"
docker compose -f $compose down
