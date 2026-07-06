# Machine B: MinIO prefix setup (no MySQL / no app)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .env)) {
    Copy-Item .env.storage.example .env
    Write-Host "Created .env from .env.storage.example — edit MINIO_* keys, MACHINE_A_HOSTS, then run again."
    exit 0
}

Write-Host ""
Write-Host "Machine B (MinIO): run on Linux/WSL with mc installed:"
Write-Host "  chmod +x scripts/setup-minio-prefix.sh && ./scripts/setup-minio-prefix.sh"
Write-Host ""
Write-Host "See README-MACHINE-B.md for full steps."
