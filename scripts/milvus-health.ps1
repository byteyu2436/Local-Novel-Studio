$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
$compose = Join-Path $PWD "infra\milvus\docker-compose.yml"
$project = "local-novel-studio-milvus"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker is not available. Install Docker Desktop (Windows/WSL2) or Docker Engine before starting Milvus."
    exit 2
}

docker info | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker Engine is not running. Start Docker Desktop (Windows/WSL2) or the Docker daemon, then retry."
    exit 7
}

$names = docker compose -f $compose -p $project ps --format "{{.Name}}"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker Engine is not running or Compose cannot talk to the daemon. Start Docker Desktop/Engine, then retry."
    exit 7
}
if (-not $names) {
    Write-Host "This project's Milvus containers are not started. Run scripts/milvus-up.ps1 (Windows) or scripts/milvus-up.sh (Linux)."
    exit 4
}

try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect("127.0.0.1", 9091)
    $client.Close()
} catch {
    Write-Host "Port 9091 is not reachable. The container exists but the health port is closed; wait for startup or inspect docker compose logs."
    exit 5
}

try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:9091/healthz" -UseBasicParsing -TimeoutSec 5
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
        Write-Host "Milvus healthz OK. Vector index is rebuildable and is not Canon."
        exit 0
    }
    Write-Host "Milvus healthz returned HTTP $($response.StatusCode). Container is up but not ready."
    exit 6
} catch {
    Write-Host "Milvus is not ready yet (healthz failed). Wait for the standalone healthcheck, then retry."
    exit 6
}
