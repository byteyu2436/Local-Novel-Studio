$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$compose = Join-Path $PWD "infra\milvus\docker-compose.yml"
$project = "local-novel-studio-milvus"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker is not available. Install Docker Desktop (Windows/WSL2) or Docker Engine, then retry."
    exit 2
}

docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker Compose is not available. Enable the Compose plugin, then retry."
    exit 2
}

function Test-PortOpen([int]$Port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $Port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

$running = docker compose -f $compose -p $project ps --status running --format "{{.Name}}" 2>$null
$ours = $running -match "lns-milvus-standalone"
if ((Test-PortOpen 19530) -and -not $ours) {
    Write-Host "Port 19530 is already in use by another process. Stop that listener or choose a free port before starting this project's Milvus stack."
    exit 3
}

docker compose -f $compose -p $project up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "docker compose up failed. If registry mirrors (for example USTC) return EOF, retry the pull or use a working Hub mirror, then run this script again."
    exit 1
}
Write-Host "Milvus Standalone is starting (stack: $project). Health: http://127.0.0.1:9091/healthz"
Write-Host "Repeatable: running this script again is safe. Stop with scripts/milvus-down.ps1"
