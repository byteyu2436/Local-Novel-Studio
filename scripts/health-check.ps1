$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Checking FastAPI /health"
try {
    (Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing).Content
} catch {
    Write-Host "FastAPI is not reachable on 127.0.0.1:8000. Start scripts/dev-backend.ps1."
}

Write-Host "Checking Milvus healthz"
try {
    (Invoke-WebRequest -Uri "http://127.0.0.1:9091/healthz" -UseBasicParsing).Content
} catch {
    Write-Host "Milvus is not reachable. Run scripts/milvus-up.ps1. Vector index is rebuildable and is not Canon."
}

Write-Host "Checking Ollama tags"
try {
    (Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing).StatusCode
} catch {
    Write-Host "Ollama is not reachable on 127.0.0.1:11434."
}
