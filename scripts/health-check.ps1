$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Checking FastAPI /health"
try {
    (Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing).Content
} catch {
    Write-Host "FastAPI is not reachable on 127.0.0.1:8000. Start scripts/dev-backend.ps1."
}

Write-Host "Checking Milvus healthz (this project stack only)"
try {
    & "$PSScriptRoot\milvus-health.ps1"
} catch {
    Write-Host "Milvus health check failed. Vector index is rebuildable and is not Canon."
}

Write-Host "Checking Ollama tags"
try {
    (Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing).StatusCode
} catch {
    Write-Host "Ollama is not reachable on 127.0.0.1:11434."
}
